import os
# import google.generativeai as genai  # Removed - using 100% OpenRouter
import time
import json
import re
import concurrent.futures
import threading
from multiprocessing import cpu_count
from itertools import cycle

# Import rate limiter for Google AI
try:
    from .rate_limiter import get_rate_limiter, exponential_backoff_sleep, is_rate_limit_error, _get_key_hash
except ImportError:
    try:
        from rate_limiter import get_rate_limiter, exponential_backoff_sleep, is_rate_limit_error, _get_key_hash
    except ImportError:
        print("⚠️ Rate limiter module not found")
        def get_rate_limiter(*args, **kwargs):
            return None
        def exponential_backoff_sleep(retry_count, base_delay=1.0, max_delay=60.0):
            time.sleep(min(base_delay * (2 ** retry_count), max_delay))
        def is_rate_limit_error(error_message):
            return "429" in str(error_message).lower() or "rate limit" in str(error_message).lower()
        def _get_key_hash(api_key):
            import hashlib
            return hashlib.md5(api_key.encode()).hexdigest()[:8]

# Import reformat function
try:
    from .reformat import fix_text_format
    CAN_REFORMAT = True
    print("Da import thanh cong chuc nang reformat")
except ImportError:
    CAN_REFORMAT = False
    print("Khong the import reformat.py - chuc nang reformat se bi tat")

# --- CẤU HÌNH CÁC HẰNG SỐ ---
MAX_RETRIES_ON_SAFETY_BLOCK = 5
MAX_RETRIES_ON_BAD_TRANSLATION = 5
MAX_RETRIES_ON_RATE_LIMIT = 3  # Số lần retry khi gặp rate limit
RETRY_DELAY_SECONDS = 2
PROGRESS_FILE_SUFFIX = ".progress.json"
CHUNK_SIZE = 1024 * 1024  # 1MB (Không còn dùng trực tiếp CHUNK_SIZE cho việc đọc file nữa)

# Kích thước cửa sổ ngữ cảnh (số đoạn văn bản trước đó dùng làm ngữ cảnh)
CONTEXT_WINDOW_SIZE = 5
# Ký tự đặc biệt để đánh dấu phần cần dịch trong prompt gửi đến AI
TRANSLATE_TAG_START = "<translate_this>"
TRANSLATE_TAG_END = "</translate_this>"

# Số dòng gom lại thành một chunk để dịch
CHUNK_SIZE_LINES = 100

# Global stop event để dừng tiến trình dịch
_stop_event = threading.Event()

# Global quota exceeded flag
_quota_exceeded = threading.Event()

# Key rotation class for Google AI multiple keys
class KeyRotator:
    """
    Thread-safe key rotator cho Google AI multiple keys
    Sử dụng round-robin để xoay vòng giữa các keys
    """
    def __init__(self, api_keys):
        """
        Args:
            api_keys: list of API keys hoặc single API key string
        """
        if isinstance(api_keys, list):
            self.keys = api_keys
            self.is_multi_key = len(api_keys) > 1
        else:
            self.keys = [api_keys]
            self.is_multi_key = False
        
        self.key_iterator = cycle(self.keys)
        self.lock = threading.Lock()
        self.key_usage = {key: 0 for key in self.keys}  # Track usage count
        
        if self.is_multi_key:
            print(f"🔄 Key Rotator: Đã khởi tạo với {len(self.keys)} keys")
            print(f"💡 Hệ thống sẽ tự động xoay vòng giữa các keys để tối ưu RPM")
    
    def get_next_key(self):
        """Get next API key trong rotation"""
        with self.lock:
            key = next(self.key_iterator)
            self.key_usage[key] += 1
            return key
    
    def get_usage_stats(self):
        """Get usage statistics for all keys"""
        with self.lock:
            return dict(self.key_usage)
    
    def print_stats(self):
        """Print usage statistics"""
        if not self.is_multi_key:
            return
        
        stats = self.get_usage_stats()
        print("\n📊 Key Usage Statistics:")
        for idx, (key, count) in enumerate(stats.items(), 1):
            masked_key = key[:10] + "***" + key[-10:] if len(key) > 20 else "***"
            print(f"   Key #{idx} ({masked_key}): {count} requests")
        print()

def set_stop_translation():
    """Dừng tiến trình dịch"""
    global _stop_event
    _stop_event.set()
    print("🛑 Đã yêu cầu dừng tiến trình dịch...")

def clear_stop_translation():
    """Xóa flag dừng để có thể tiếp tục dịch"""
    global _stop_event, _quota_exceeded
    _stop_event.clear()
    _quota_exceeded.clear()
    print("▶️ Đã xóa flag dừng, sẵn sàng tiếp tục...")

def is_translation_stopped():
    """Kiểm tra xem có yêu cầu dừng không"""
    global _stop_event
    return _stop_event.is_set()

def set_quota_exceeded():
    """Đánh dấu API đã hết quota"""
    global _quota_exceeded, _stop_event
    _quota_exceeded.set()
    _stop_event.set()  # Cũng dừng dịch
    print("API đã hết quota - dừng tiến trình dịch")

def is_quota_exceeded():
    """Kiểm tra xem API có hết quota không"""
    global _quota_exceeded
    return _quota_exceeded.is_set()

def check_quota_error(error_message):
    """Kiểm tra xem có phải lỗi quota exceeded không"""
    error_str = str(error_message).lower()
    quota_keywords = [
        "429",
        "exceeded your current quota",
        "quota exceeded", 
        "rate limit",
        "billing",
        "please check your plan"
    ]
    
    return any(keyword in error_str for keyword in quota_keywords)

def check_api_key_error(error_message):
    """Kiểm tra xem lỗi có phải là API key không hợp lệ không"""
    error_str = str(error_message).lower()
    api_key_keywords = [
        "api key not valid", "invalid api key", "unauthorized", "authentication failed",
        "api_key_invalid", "invalid_api_key", "api key is invalid", "bad api key",
        "400", "401", "403"
    ]
    return any(keyword in error_str for keyword in api_key_keywords)

def validate_api_key_before_translation(api_key, model_name, provider="OpenRouter"):
    """Validate API key trước khi bắt đầu translation"""
    try:
        if provider == "Google AI":
            # Test Google AI API
            import google.generativeai as genai
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            
            response = model.generate_content("Test")
            
            if response and response.text:
                return True, "Google AI API key hợp lệ"
            else:
                return False, "Google AI API trả về response rỗng"
                
        elif provider == "OpenRouter":
            # Test OpenRouter API
            import requests
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/TranslateNovelAI",
                "X-Title": "TranslateNovelAI"
            }
            
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": "Test"}],
                "max_tokens": 10
            }
            
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                return True, "OpenRouter API key hợp lệ"
            elif response.status_code == 401:
                return False, "OpenRouter API Key không hợp lệ hoặc đã hết hạn"
            elif response.status_code == 402:
                return False, "Tài khoản OpenRouter hết credit"
            else:
                return False, f"Lỗi OpenRouter API: HTTP {response.status_code}"
        else:
            return False, f"Provider không hợp lệ: {provider}"
            
    except Exception as e:
        error_msg = str(e)
        if check_api_key_error(error_msg):
            return False, f"API Key không hợp lệ: {error_msg}"
        elif check_quota_error(error_msg):
            return False, f"API hết quota: {error_msg}"
        else:
            return False, f"Lỗi kết nối API: {error_msg}"

def get_optimal_threads():
    """
    Tự động tính toán số threads tối ưu dựa trên cấu hình máy.
    """
    try:
        # Lấy số CPU cores
        cpu_cores = cpu_count()
        
        # Tính toán threads tối ưu:
        # - Với API calls, I/O bound nên có thể dùng nhiều threads hơn số cores
        # - Nhưng không nên quá nhiều để tránh rate limiting
        # - Formula: min(max(cpu_cores * 2, 4), 20)
        optimal_threads = min(max(cpu_cores * 2, 4), 20)
        
        print(f"Phat hien {cpu_cores} CPU cores")
        print(f"Threads toi uu duoc de xuat: {optimal_threads}")
        
        return optimal_threads
        
    except Exception as e:
        print(f"Loi khi phat hien CPU cores: {e}")
        return 10  # Default fallback

def validate_threads(num_threads):
    """
    Validate số threads để đảm bảo trong khoảng hợp lý.
    """
    try:
        num_threads = int(num_threads)
        if num_threads < 1:
            return 1
        elif num_threads > 50:  # Giới hạn tối đa để tránh rate limiting
            return 50
        return num_threads
    except (ValueError, TypeError):
        return get_optimal_threads()

def validate_chunk_size(chunk_size):
    """
    Validate chunk size để đảm bảo trong khoảng hợp lý.
    """
    try:
        chunk_size = int(chunk_size)
        if chunk_size < 10:
            return 10
        elif chunk_size > 500:  # Tránh chunks quá lớn
            return 500
        return chunk_size
    except (ValueError, TypeError):
        return 100  # Default

# Default values
NUM_WORKERS = get_optimal_threads()  # Tự động tính theo máy

def format_error_chunk(error_type: str, error_message: str, original_lines: list, line_range: str) -> str:
    """
    Format chunk bị lỗi với nội dung gốc để lưu vào file
    
    Args:
        error_type: Loại lỗi (API, QUOTA, SAFETY, etc.)
        error_message: Thông báo lỗi chi tiết
        original_lines: Nội dung gốc của chunk
        line_range: Line range (ví dụ: "123:223")
    
    Returns:
        Formatted error text với nội dung gốc
    """
    original_text = ''.join(original_lines)  # Join lines, giữ nguyên line breaks
    
    error_output = f"""[[LỖI {error_type}: {error_message}

--- NỘI DUNG GỐC CẦN DỊCH LẠI ---
{original_text}
--- HẾT NỘI DUNG GỐC ---
] [lines: {line_range}]]

"""
    return error_output


def is_bad_translation(text):
    """
    Kiểm tra xem bản dịch của chunk có đạt yêu cầu không (kiểm tra đơn giản dựa vào độ rỗng và từ chối).
    Trả về True nếu bản dịch không đạt yêu cầu (ví dụ: rỗng hoặc chứa từ từ chối), False nếu đạt yêu cầu.
    """
    if text is None or text.strip() == "":
        # Chunk dịch ra rỗng hoặc chỉ trắng => coi là bad translation
        return True

    # Các từ khóa chỉ báo bản dịch không đạt yêu cầu
    # Các từ khóa này thường xuất hiện khi AI từ chối dịch
    bad_keywords = [
        "tôi không thể dịch",
        "không thể dịch",
        "xin lỗi, tôi không",
        "tôi xin lỗi",
        "nội dung bị chặn", # Thêm kiểm tra thông báo chặn cũng là bản dịch xấu cần retry
        "as an ai", # Từ chối bằng tiếng Anh
        "as a language model",
        "i am unable",
        "i cannot",
        "i'm sorry"
    ]

    text_lower = text.lower()
    for keyword in bad_keywords:
        if keyword in text_lower:
            return True

    return False

def translate_chunk(model, chunk_lines):
    """
    Dịch một chunk gồm nhiều dòng văn bản.
    chunk_lines: danh sách các dòng văn bản
    Trả về (translated_text, is_safety_blocked_flag, is_bad_translation_flag).
    """
    # Gom các dòng thành một chuỗi lớn để gửi đi
    full_text_to_translate = "\n".join(chunk_lines)
    
    # Bỏ qua các chunk chỉ chứa các dòng trống hoặc chỉ trắng
    if not full_text_to_translate.strip():
        return ("", False, False) # Trả về chuỗi rỗng, không bị chặn, không bad translation

    try:
        # Prompt cho dịch chunk
        prompt = f"Dịch đoạn văn bản sau sang tiếng Việt một cách trực tiếp, Danh xưng nhân vật dẫn truyện xưng 'tôi' theo bối cảnh hiện đại hoặc 'ta' theo bối cảnh cổ đại,xác định mối quan hệ và danh xưng phù hợp trước tiên, không từ chối hoặc bình luận, giữ nguyên văn phong gốc và chi tiết nội dung:\n\n{full_text_to_translate}"

        response = model.generate_content(
            contents=[{
                "role": "user",
                "parts": [prompt],
            }],
            generation_config={
                "response_mime_type": "text/plain",
                # Có thể thêm các tham số khác nếu cần
                # "temperature": 0.5,
                # "top_p": 0.95,
                # "top_k": 64,
                # "max_output_tokens": 8192,
            },
        )

        # 1. Kiểm tra xem prompt (đầu vào) có bị chặn không
        if response.prompt_feedback and response.prompt_feedback.safety_ratings:
            blocked_categories = [
                rating.category.name for rating in response.prompt_feedback.safety_ratings
                if rating.blocked
            ]
            if blocked_categories:
                return (f"[NỘI DUNG GỐC BỊ CHẶN BỞI BỘ LỌC AN TOÀN - PROMPT: {', '.join(blocked_categories)}]", True, False)

        # 2. Kiểm tra xem có bất kỳ ứng cử viên nào được tạo ra không
        if not response.candidates:
            return ("[NỘI DỊCH BỊ CHẶN HOÀN TOÀN BỞI BỘ LỌC AN TOÀN - KHÔNG CÓ ỨNG CỬ VIÊN]", True, False)

        # 3. Kiểm tra lý do kết thúc của ứng cử viên đầu tiên (nếu có)
        first_candidate = response.candidates[0]
        if first_candidate.finish_reason == 'SAFETY':
            blocked_categories = [
                rating.category.name for rating in first_candidate.safety_ratings
                if rating.blocked
            ]
            return (f"[NỘI DỊCH BỊ CHẶN BỞI BỘ LỌC AN TOÀN - OUTPUT: {', '.join(blocked_categories)}]", True, False)

        # Nếu không bị chặn, trả về văn bản dịch
        translated_text = response.text
        is_bad = is_bad_translation(translated_text)
        return (translated_text, False, is_bad)

    except Exception as e:
        # Bắt các lỗi khác (ví dụ: lỗi mạng, lỗi API)
        error_message = str(e)
        
        # Kiểm tra lỗi quota exceeded
        if check_quota_error(error_message):
            set_quota_exceeded()
            return (f"[API HẾT QUOTA]", False, True)
        
        return (f"[LỖI API KHI DỊCH CHUNK: {e}]", False, True)

def get_progress(progress_file_path):
    """Đọc tiến độ dịch từ file (số chunk đã hoàn thành)."""
    if os.path.exists(progress_file_path):
        try:
            with open(progress_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Lưu số chunk đã hoàn thành
                return data.get('completed_chunks', 0)
        except json.JSONDecodeError:
            print(f"Cảnh báo: File tiến độ '{progress_file_path}' bị hỏng hoặc không đúng định dạng JSON. Bắt đầu từ đầu.")
            return 0
    return 0

def save_progress(progress_file_path, completed_chunks):
    """Lưu tiến độ dịch (số chunk đã hoàn thành) vào file."""
    try:
        with open(progress_file_path, 'w', encoding='utf-8') as f:
            json.dump({
                'completed_chunks': completed_chunks
            }, f)
    except Exception as e:
        print(f"⚠️ Lỗi khi lưu file tiến độ: {e}")

def save_progress_with_line_info(progress_file_path, completed_chunks, current_chunk_info=None, error_info=None):
    """Lưu tiến độ dịch với thông tin line range và error details"""
    try:
        progress_data = {
            'completed_chunks': completed_chunks,
            'timestamp': time.time()
        }
        
        # Thêm thông tin chunk hiện tại nếu có
        if current_chunk_info:
            progress_data['current_chunk'] = current_chunk_info
        
        # Thêm thông tin lỗi nếu có
        if error_info:
            progress_data['last_error'] = error_info
        
        with open(progress_file_path, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        print(f"⚠️ Lỗi khi lưu file tiến độ: {e}")

def load_progress_with_info(progress_file_path):
    """Tải tiến độ với thông tin chi tiết"""
    if os.path.exists(progress_file_path):
        try:
            with open(progress_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except json.JSONDecodeError:
            print(f"Cảnh báo: File tiến độ '{progress_file_path}' bị hỏng. Bắt đầu từ đầu.")
            return {'completed_chunks': 0}
    return {'completed_chunks': 0}

def process_chunk(api_key, model_name, system_instruction, chunk_data, provider="OpenRouter", log_callback=None, key_rotator=None):
    """
    Xử lý dịch một chunk với retry logic và rate limiting.
    chunk_data: tuple (chunk_index, chunk_lines, chunk_start_line_index)
    Trả về: (chunk_index, translated_text, lines_count, line_range)
    
    Args:
        key_rotator: KeyRotator instance nếu sử dụng multiple keys (Google AI only)
    """
    chunk_index, chunk_lines, chunk_start_line_index = chunk_data
    
    # Tính toán line range cho chunk hiện tại
    chunk_end_line_index = chunk_start_line_index + len(chunk_lines) - 1
    line_range = f"{chunk_start_line_index + 1}:{chunk_end_line_index + 1}"  # +1 vì line numbers bắt đầu từ 1
    
    # Get current API key (from rotator if available)
    current_api_key = key_rotator.get_next_key() if key_rotator else api_key
    
    # Get rate limiter cho Google AI với specific key (None cho OpenRouter)
    rate_limiter = get_rate_limiter(model_name, provider, current_api_key if provider == "Google AI" else None)
    
    # Debug logging
    if rate_limiter and provider == "Google AI":
        current_usage = rate_limiter.get_current_usage()
        wait_time = rate_limiter.get_wait_time()
        if wait_time > 0:
            print(f"⏱️ Chunk {chunk_index}: Current usage {current_usage} requests, cần đợi {wait_time:.1f}s")
    
    # Kiểm tra flag dừng và quota exceeded trước khi bắt đầu
    if is_translation_stopped() or is_quota_exceeded():
        if is_quota_exceeded():
            error_text = format_error_chunk("API HẾT QUOTA", "API đã hết quota, cần nạp thêm credit hoặc đổi API key", chunk_lines, line_range)
            return (chunk_index, error_text, len(chunk_lines), line_range)
        else:
            error_text = format_error_chunk("DỪNG BỞI NGƯỜI DÙNG", "Người dùng đã dừng quá trình dịch", chunk_lines, line_range)
            return (chunk_index, error_text, len(chunk_lines), line_range)
    
    # Determine which API to use based on provider
    use_google_ai = (provider == "Google AI")
    use_openrouter = (provider == "OpenRouter")
    
    if use_google_ai:
        # Setup Google AI (với current API key từ rotator)
        try:
            import google.generativeai as genai
            genai.configure(api_key=current_api_key)
            model = genai.GenerativeModel(model_name)
        except ImportError:
            error_text = format_error_chunk("IMPORT ERROR", "Google AI module không tìm thấy. Vui lòng cài đặt: pip install google-generativeai", chunk_lines, line_range)
            return (chunk_index, error_text, len(chunk_lines), line_range)
    elif use_openrouter:
        # Import OpenRouter translate function
        try:
            from .open_router_translate import translate_chunk as openrouter_translate_chunk
        except ImportError:
            try:
                from open_router_translate import translate_chunk as openrouter_translate_chunk
            except ImportError:
                error_text = format_error_chunk("IMPORT ERROR", "OpenRouter module không tìm thấy", chunk_lines, line_range)
                return (chunk_index, error_text, len(chunk_lines), line_range)
    
    # Thử lại với lỗi bảo mật
    safety_retries = 0
    is_safety_blocked = False  # Khởi tạo biến
    while safety_retries < MAX_RETRIES_ON_SAFETY_BLOCK:
        # Kiểm tra flag dừng và quota exceeded trong quá trình retry
        if is_translation_stopped() or is_quota_exceeded():
            if is_quota_exceeded():
                error_text = format_error_chunk("API HẾT QUOTA", "API đã hết quota trong quá trình retry", chunk_lines, line_range)
                return (chunk_index, error_text, len(chunk_lines), line_range)
            else:
                error_text = format_error_chunk("DỪNG BỞI NGƯỜI DÙNG", "Người dùng đã dừng quá trình dịch trong retry", chunk_lines, line_range)
                return (chunk_index, error_text, len(chunk_lines), line_range)
            
        # Thử lại với bản dịch xấu  
        bad_translation_retries = 0
        while bad_translation_retries < MAX_RETRIES_ON_BAD_TRANSLATION:
            # Kiểm tra flag dừng và quota exceeded trong quá trình retry
            if is_translation_stopped() or is_quota_exceeded():
                if is_quota_exceeded():
                    error_text = format_error_chunk("API HẾT QUOTA", "API đã hết quota trong bad translation retry", chunk_lines, line_range)
                    return (chunk_index, error_text, len(chunk_lines), line_range)
                else:
                    error_text = format_error_chunk("DỪNG BỞI NGƯỜI DÙNG", "Người dùng đã dừng trong bad translation retry", chunk_lines, line_range)
                    return (chunk_index, error_text, len(chunk_lines), line_range)
                
            try:
                # Retry logic for rate limit errors
                rate_limit_retry = 0
                while rate_limit_retry <= MAX_RETRIES_ON_RATE_LIMIT:
                    try:
                        # Rate limit cho Google AI - Multi-threading safe
                        if rate_limiter and use_google_ai:
                            rate_limiter.acquire()  # Non-blocking multi-thread acquire
                        
                        if use_google_ai:
                            # Gom các dòng thành một chuỗi lớn để gửi đi
                            full_text_to_translate = "\n".join(chunk_lines)
                            
                            # Bỏ qua các chunk chỉ chứa các dòng trống
                            if not full_text_to_translate.strip():
                                return (chunk_index, "", len(chunk_lines), line_range)
                            
                            # Dịch với Google AI
                            prompt = f"{system_instruction}\n\n{full_text_to_translate}"
                            response = model.generate_content(prompt)
                            
                            # Kiểm tra safety blocks
                            if response.prompt_feedback and hasattr(response.prompt_feedback, 'block_reason'):
                                is_safety_blocked = True
                                translated_text = f"[NỘI DUNG BỊ CHẶN BỞI BỘ LỌC AN TOÀN]"
                                is_bad = False
                            elif response.candidates and response.candidates[0].finish_reason.name == 'SAFETY':
                                is_safety_blocked = True
                                translated_text = f"[NỘI DỊCH BỊ CHẶN BỞI BỘ LỌC AN TOÀN]"
                                is_bad = False
                            else:
                                translated_text = response.text
                                is_safety_blocked = False
                                is_bad = is_bad_translation(translated_text)
                            
                            # Báo success cho adaptive throttling
                            if rate_limiter:
                                rate_limiter.on_success()
                            
                            break  # Success, thoát khỏi rate limit retry loop
                                
                        elif use_openrouter:
                            translated_text, is_safety_blocked, is_bad = openrouter_translate_chunk(api_key, model_name, system_instruction, chunk_lines)
                            break  # Success, thoát khỏi rate limit retry loop
                        else:
                            error_text = format_error_chunk("PROVIDER ERROR", f"Provider không được hỗ trợ: {provider}", chunk_lines, line_range)
                            return (chunk_index, error_text, len(chunk_lines), line_range)
                            
                    except Exception as rate_error:
                        error_msg = str(rate_error)
                        
                        # Kiểm tra nếu là rate limit error
                        if is_rate_limit_error(error_msg) and rate_limit_retry < MAX_RETRIES_ON_RATE_LIMIT:
                            rate_limit_retry += 1
                            print(f"⚠️ Rate limit error ở chunk {chunk_index}, retry {rate_limit_retry}/{MAX_RETRIES_ON_RATE_LIMIT}")
                            
                            # Báo rate limit error cho adaptive throttling
                            if rate_limiter and use_google_ai:
                                rate_limiter.on_rate_limit_error()
                            
                            exponential_backoff_sleep(rate_limit_retry - 1, base_delay=5.0)
                            continue
                        else:
                            # Không phải rate limit error hoặc hết retry
                            raise  # Re-raise để xử lý ở catch block bên ngoài
                
                # Kiểm tra quota exceeded sau khi dịch
                if is_quota_exceeded():
                    error_text = format_error_chunk("API HẾT QUOTA", "API đã hết quota sau khi dịch", chunk_lines, line_range)
                    return (chunk_index, error_text, len(chunk_lines), line_range)
                
                if is_safety_blocked:
                    break # Thoát khỏi vòng lặp bad translation, sẽ retry safety
                    
                if not is_bad:
                    return (chunk_index, translated_text, len(chunk_lines), line_range) # Thành công
                    
                # Bản dịch xấu, thử lại
                bad_translation_retries += 1
                if bad_translation_retries < MAX_RETRIES_ON_BAD_TRANSLATION:
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    # Hết lần thử bad translation, dùng bản dịch cuối
                    return (chunk_index, translated_text + " [KHÔNG CẢI THIỆN ĐƯỢC]", len(chunk_lines), line_range)
                    
            except Exception as e:
                error_msg = str(e)
                
                # Kiểm tra quota error
                if check_quota_error(error_msg):
                    set_quota_exceeded()
                    error_text = format_error_chunk("API HẾT QUOTA", f"API quota exceeded: {error_msg}", chunk_lines, line_range)
                    return (chunk_index, error_text, len(chunk_lines), line_range)
                
                # Kiểm tra API key error
                if check_api_key_error(error_msg):
                    error_text = format_error_chunk("API KEY ERROR", f"API key không hợp lệ: {error_msg}", chunk_lines, line_range)
                    return (chunk_index, error_text, len(chunk_lines), line_range)
                
                # Lỗi khác - lưu lại với nội dung gốc
                error_text = format_error_chunk("API ERROR", f"Lỗi khi gọi API: {error_msg}", chunk_lines, line_range)
                return (chunk_index, error_text, len(chunk_lines), line_range)
        
        # Nếu bị chặn safety, thử lại
        if is_safety_blocked:
            safety_retries += 1
            if safety_retries < MAX_RETRIES_ON_SAFETY_BLOCK:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                # Hết lần thử safety, trả về với nội dung gốc
                error_text = format_error_chunk("SAFETY BLOCKED", f"Nội dung bị chặn bởi bộ lọc an toàn sau {MAX_RETRIES_ON_SAFETY_BLOCK} lần thử. Dịch thủ công: {translated_text}", chunk_lines, line_range)
                return (chunk_index, error_text, len(chunk_lines), line_range)
    
    # Fallback (không nên đến đây)
    error_text = format_error_chunk("UNKNOWN ERROR", "Không thể dịch chunk sau tất cả các lần thử", chunk_lines, line_range)
    return (chunk_index, error_text, len(chunk_lines), line_range)

def generate_output_filename(input_filepath):
    """
    Tự động tạo tên file output từ input file.
    Ví dụ: "test.txt" -> "test_TranslateAI.txt"
    """
    # Tách tên file và phần mở rộng
    file_dir = os.path.dirname(input_filepath)
    file_name = os.path.basename(input_filepath)
    name_without_ext, ext = os.path.splitext(file_name)
    
    # Tạo tên file mới
    new_name = f"{name_without_ext}_TranslateAI{ext}"
    
    # Kết hợp với thư mục (nếu có)
    if file_dir:
        return os.path.join(file_dir, new_name)
    else:
        return new_name

def translate_file_optimized(input_file, output_file=None, api_key=None, model_name="gemini-2.0-flash", system_instruction=None, num_workers=None, chunk_size_lines=None, provider="OpenRouter"):
    """
    Phiên bản dịch file với multi-threading chunks.
    
    Args:
        api_key: String (OpenRouter) hoặc List (Google AI multiple keys)
    """
    # Clear stop flag khi bắt đầu dịch mới
    clear_stop_translation()
    
    # Setup key rotator nếu có multiple Google AI keys
    key_rotator = None
    if provider == "Google AI" and isinstance(api_key, list) and len(api_key) > 1:
        key_rotator = KeyRotator(api_key)
        # Dùng key đầu tiên để validate
        validation_key = api_key[0]
    elif provider == "Google AI" and isinstance(api_key, list):
        # Chỉ có 1 key trong list
        validation_key = api_key[0] if api_key else None
    else:
        validation_key = api_key
    
    # Validate và thiết lập parameters
    if num_workers is None:
        num_workers = NUM_WORKERS
    else:
        num_workers = validate_threads(num_workers)
    
    # Tính toán threads cho Google AI dựa trên số lượng keys
    if provider == "Google AI":
        # Xác định base RPM dựa trên model
        if "1.5-pro" in model_name.lower():
            base_rpm = 2  # Pro model có RPM rất thấp
            base_threads = 1
        elif "2.0-flash" in model_name.lower() or "2.0flash" in model_name.lower():
            base_rpm = 10
            base_threads = 2
        elif "1.5-flash" in model_name.lower() or "1.5flash" in model_name.lower():
            base_rpm = 15
            base_threads = 3
        else:
            base_rpm = 10  # Default safe
            base_threads = 2
        
        # Tính số keys để scale threads
        num_keys = 1
        if isinstance(api_key, list):
            num_keys = len(api_key)
        
        # Scale threads dựa trên số keys (mỗi key có thể handle base_threads)
        max_threads_google = min(base_threads * num_keys, 20)  # Cap tại 20 threads
        
        if num_workers > max_threads_google:
            print(f"🔧 Google AI với {num_keys} keys:")
            print(f"   📊 Base RPM: {base_rpm} × {num_keys} keys = {base_rpm * num_keys} RPM tổng")
            print(f"   ⚡ Threads: {num_workers} → {max_threads_google} (tối ưu cho {num_keys} keys)")
            print(f"   🌐 Tham khảo: https://ai.google.dev/gemini-api/docs/rate-limits?hl=vi")
            num_workers = max_threads_google
        elif num_keys > 1:
            print(f"🚀 Google AI Multi-Key Setup:")
            print(f"   🔑 Keys: {num_keys} keys")
            print(f"   📊 Total RPM: ~{base_rpm * num_keys} RPM")
            print(f"   ⚡ Threads: {num_workers} (tối ưu cho multi-threading)")
        
    if chunk_size_lines is None:
        chunk_size_lines = CHUNK_SIZE_LINES
    else:
        chunk_size_lines = validate_chunk_size(chunk_size_lines)
    
    # Tự động tạo tên file output nếu không được cung cấp
    if output_file is None:
        output_file = generate_output_filename(input_file)
        print(f"📝 Tự động tạo tên file output: {output_file}")
    
    print(f"Bắt đầu dịch file: {input_file}")
    print(f"File output: {output_file}")
    print(f"Provider: {provider}")
    print(f"Số worker threads: {num_workers}")
    print(f"Kích thước chunk: {chunk_size_lines} dòng")
    
    # Validate API key trước khi bắt đầu translation
    print("🔑 Đang kiểm tra API key...")
    is_valid, validation_message = validate_api_key_before_translation(validation_key, model_name, provider)
    if not is_valid:
        print(f"❌ {validation_message}")
        return False
    else:
        print(f"✅ {validation_message}")

    progress_file_path = f"{input_file}{PROGRESS_FILE_SUFFIX}"

    # Lấy tiến độ từ file với thông tin chi tiết
    progress_data = load_progress_with_info(progress_file_path)
    completed_chunks = progress_data.get('completed_chunks', 0)
    
    # Hiển thị thông tin lỗi cuối nếu có
    if 'last_error' in progress_data:
        last_error = progress_data['last_error']
        print(f"⚠️ Lỗi cuối: {last_error['message']} (chunk {last_error['chunk_index']}, lines {last_error['line_range']})")
    
    print(f"Đã hoàn thành {completed_chunks} chunk trước đó.")

    # Thời gian bắt đầu để tính hiệu suất
    start_time = time.time()
    
    # System instruction cho AI - sử dụng custom hoặc default
    if system_instruction is None:
        system_instruction = "Dịch văn bản sau sang tiếng Việt. Bối cảnh hiện đại. Đảm bảo các câu thoại nhân vật được dịch chính xác và đặc trong dấu "". Đảm bảo giữ nguyên chi tiết nội dung. Giữ nguyên các từ ngữ thô tục, tình dục."
    
    print(f"🎯 System instruction: {system_instruction[:100]}...")  # Log first 100 chars

    try:
        # Đọc toàn bộ file và chia thành chunks
        with open(input_file, 'r', encoding='utf-8', errors='replace') as infile:
            all_lines = infile.readlines()
        
        total_lines = len(all_lines)
        print(f"Tổng số dòng trong file: {total_lines}")
        
        # Chia thành chunks
        chunks = []
        for i in range(0, total_lines, chunk_size_lines):
            chunk_lines = all_lines[i:i + chunk_size_lines]
            chunks.append((len(chunks), chunk_lines, i))  # (chunk_index, chunk_lines, start_line_index)
        
        total_chunks = len(chunks)
        print(f"Tổng số chunks: {total_chunks}")
        
        # Kiểm tra nếu đã dịch hết file rồi
        if completed_chunks >= total_chunks:
            print(f"✅ File đã được dịch hoàn toàn ({completed_chunks}/{total_chunks} chunks).")
            if os.path.exists(progress_file_path):
                os.remove(progress_file_path)
                print(f"Đã xóa file tiến độ: {os.path.basename(progress_file_path)}")
            return True

        # Mở file output để ghi kết quả
        mode = 'a' if completed_chunks > 0 else 'w'  # Append nếu có tiến độ cũ, write nếu bắt đầu mới
        with open(output_file, mode, encoding='utf-8') as outfile:
            
            # Dictionary để lưu trữ kết quả dịch theo thứ tự chunk index
            translated_chunks_results = {}
            next_expected_chunk_to_write = completed_chunks
            total_lines_processed = completed_chunks * chunk_size_lines

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                
                futures = {} # Lưu trữ các future: {future_object: chunk_index}
                
                # Gửi các chunks cần dịch đến thread pool
                chunks_to_process = chunks[completed_chunks:]  # Chỉ xử lý chunks chưa hoàn thành
                
                print(f"Gửi {len(chunks_to_process)} chunks đến thread pool...")
                
                for chunk_data in chunks_to_process:
                    # Kiểm tra flag dừng trước khi submit
                    if is_translation_stopped():
                        print("🛑 Dừng gửi chunks mới do người dùng yêu cầu")
                        break
                        
                    # Submit với key_rotator nếu có
                    future = executor.submit(process_chunk, api_key, model_name, system_instruction, chunk_data, provider, None, key_rotator)
                    futures[future] = chunk_data[0]  # chunk_index
                
                # Thu thập kết quả khi các threads hoàn thành
                for future in concurrent.futures.as_completed(futures):
                    # Kiểm tra flag dừng và quota exceeded
                    if is_translation_stopped():
                        if is_quota_exceeded():
                            print("Dừng xử lý kết quả do API hết quota")
                        else:
                            print("🛑 Dừng xử lý kết quả do người dùng yêu cầu")
                        
                        # Hủy các future chưa hoàn thành
                        for f in futures:
                            if not f.done():
                                f.cancel()
                        break
                        
                    chunk_index = futures[future]
                    try:
                        result = future.result()  # (chunk_index, translated_text, lines_count, line_range)
                        
                        # Handle result với line info
                        if len(result) == 4:  # New format with line_range
                            processed_chunk_index, translated_text, lines_count, line_range = result
                        else:  # Old format fallback
                            processed_chunk_index, translated_text, lines_count = result
                            # Tính toán line_range từ chunk data
                            chunk_data = chunks[processed_chunk_index]
                            start_line = chunk_data[2]
                            line_range = f"{start_line + 1}:{start_line + len(chunk_data[1])}"
                        
                        # Check for errors
                        if translated_text.startswith('[') and ('HẾT QUOTA' in translated_text or 'LỖI' in translated_text):
                            # Lưu lỗi với line info
                            error_info = {
                                'message': translated_text,
                                'chunk_index': processed_chunk_index,
                                'line_range': line_range,
                                'timestamp': time.time()
                            }
                            save_progress_with_line_info(progress_file_path, next_expected_chunk_to_write, None, error_info)
                            print(f"❌ Lỗi tại chunk {processed_chunk_index + 1} (lines {line_range}): {translated_text}")
                            # Continue processing other chunks
                        
                        # Lưu kết quả vào buffer tạm chờ ghi theo thứ tự
                        translated_chunks_results[processed_chunk_index] = (translated_text, lines_count, line_range)
                        
                        print(f"✅ Hoàn thành chunk {processed_chunk_index + 1}/{total_chunks}")
                        
                        # Ghi các chunks đã hoàn thành vào file output theo đúng thứ tự
                        while next_expected_chunk_to_write in translated_chunks_results:
                            chunk_text, chunk_lines_count, chunk_line_range = translated_chunks_results.pop(next_expected_chunk_to_write)
                            outfile.write(chunk_text)
                            if not chunk_text.endswith('\n'):
                                outfile.write('\n')
                            outfile.flush()
                            
                            # Cập nhật tiến độ
                            next_expected_chunk_to_write += 1
                            total_lines_processed += chunk_lines_count
                            
                            # Lưu tiến độ sau mỗi chunk hoàn thành với line info
                            current_chunk_info = {
                                'chunk_index': next_expected_chunk_to_write - 1,
                                'line_range': chunk_line_range,
                                'lines_count': chunk_lines_count
                            }
                            save_progress_with_line_info(progress_file_path, next_expected_chunk_to_write, current_chunk_info)
                            
                            # Hiển thị thông tin tiến độ
                            current_time = time.time()
                            elapsed_time = current_time - start_time
                            progress_percent = (next_expected_chunk_to_write / total_chunks) * 100
                            avg_speed = total_lines_processed / elapsed_time if elapsed_time > 0 else 0
                            
                            print(f"Tiến độ: {next_expected_chunk_to_write}/{total_chunks} chunks ({progress_percent:.1f}%) - {avg_speed:.1f} dòng/giây")
                            
                    except Exception as e:
                        print(f"❌ Lỗi khi xử lý chunk {chunk_index}: {e}")
                
                # Ghi nốt các chunks còn sót lại trong buffer (nếu có)
                if translated_chunks_results:
                    print("⚠️ Ghi các chunks còn sót lại...")
                    sorted_remaining_chunks = sorted(translated_chunks_results.items())
                    for chunk_idx, chunk_data in sorted_remaining_chunks:
                        try:
                            if len(chunk_data) == 3:  # New format with line_range
                                chunk_text, chunk_lines_count, chunk_line_range = chunk_data
                            else:  # Old format fallback
                                chunk_text, chunk_lines_count = chunk_data
                                chunk_line_range = f"unknown"
                            
                            outfile.write(chunk_text)
                            if not chunk_text.endswith('\n'):
                                outfile.write('\n')
                            outfile.flush()
                            next_expected_chunk_to_write += 1
                            
                            # Lưu progress với line info
                            current_chunk_info = {
                                'chunk_index': chunk_idx,
                                'line_range': chunk_line_range,
                                'lines_count': chunk_lines_count
                            }
                            save_progress_with_line_info(progress_file_path, next_expected_chunk_to_write, current_chunk_info)
                            print(f"✅ Ghi chunk bị sót: {chunk_idx + 1} (lines {chunk_line_range})")
                        except Exception as e:
                            print(f"❌ Lỗi khi ghi chunk {chunk_idx}: {e}")

        # Kiểm tra xem có bị dừng giữa chừng không
        if is_translation_stopped():
            if is_quota_exceeded():
                print(f"API đã hết quota!")
                print(f"Để tiếp tục dịch, vui lòng:")
                print(f" 1. Tạo tài khoản Google Cloud mới")
                print(f" 2. Nhận 300$ credit miễn phí") 
                print(f" 3. Tạo API key mới từ ai.google.dev")
                print(f" 4. Cập nhật API key và tiếp tục dịch")
                print(f"Đã xử lý {next_expected_chunk_to_write}/{total_chunks} chunks.")
                print(f"Tiến độ đã được lưu để tiếp tục sau.")
                return False
            else:
                print(f"🛑 Tiến trình dịch đã bị dừng bởi người dùng.")
                print(f"Đã xử lý {next_expected_chunk_to_write}/{total_chunks} chunks.")
                print(f"💾 Tiến độ đã được lưu. Bạn có thể tiếp tục dịch sau.")
                return False

        # Hoàn thành
        total_time = time.time() - start_time
        if next_expected_chunk_to_write >= total_chunks:
            print(f"✅ Dịch hoàn thành file: {os.path.basename(input_file)}")
            print(f"Đã dịch {total_chunks} chunks ({total_lines} dòng) trong {total_time:.2f}s")
            print(f"Tốc độ trung bình: {total_lines / total_time:.2f} dòng/giây")
            print(f"File dịch đã được lưu tại: {output_file}")
            
            # Print key usage stats if using key rotator
            if key_rotator:
                key_rotator.print_stats()
            
            # Print rate limiter stats for Google AI
            if provider == "Google AI" and key_rotator:
                print("\n📊 Rate Limiter Statistics:")
                for i, key in enumerate(key_rotator.keys, 1):
                    limiter = get_rate_limiter(model_name, provider, key)
                    if limiter:
                        stats = limiter.get_stats()
                        key_display = f"key_***{_get_key_hash(key)}"
                        print(f"   Key #{i} ({key_display}):")
                        print(f"     Usage: {stats['current_usage']}/{stats['max_requests']} ({stats['utilization']:.1%})")
                        print(f"     Throttle: {stats['throttle_factor']:.1%} (errors: {stats['consecutive_errors']})")
                print()

            # Xóa file tiến độ khi hoàn thành
            if os.path.exists(progress_file_path):
                os.remove(progress_file_path)
                print(f"Đã xóa file tiến độ: {os.path.basename(progress_file_path)}")
            
            # Tự động reformat file sau khi dịch xong
            if CAN_REFORMAT:
                print("\n🔧 Bắt đầu reformat file đã dịch...")
                try:
                    fix_text_format(output_file)
                    print("✅ Reformat hoàn thành!")
                except Exception as e:
                    print(f"⚠️ Lỗi khi reformat: {e}")
            else:
                print("⚠️ Chức năng reformat không khả dụng")
            
            return True
        else:
            print(f"⚠️ Quá trình dịch bị gián đoạn.")
            print(f"Đã xử lý {next_expected_chunk_to_write}/{total_chunks} chunks.")
            print(f"Tiến độ đã được lưu. Bạn có thể chạy lại chương trình để tiếp tục.")
            return False

    except FileNotFoundError:
        print(f"❌ Lỗi: Không tìm thấy file đầu vào '{input_file}'.")
        return False
    except Exception as e:
        print(f"❌ Đã xảy ra lỗi không mong muốn: {e}")
        print("Tiến độ đã được lưu. Bạn có thể chạy lại chương trình để tiếp tục.")
        return False


def load_api_key():
    """Tự động load API key từ environment variable hoặc file config"""
    # Thử load từ environment variable
    import os
    api_key = os.getenv('GOOGLE_AI_API_KEY')
    if api_key:
        print(f"✅ Đã load API key từ environment variable")
        return api_key
    
    # Thử load từ file config.json
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                api_key = config.get('api_key')
                if api_key:
                    print(f"✅ Đã load API key từ config.json")
                    return api_key
    except:
        pass
    
    return None

def main():
    """Interactive main function for command line usage"""
    print("=== TranslateNovelAI - Command Line Version ===\n")
    
    # Thử tự động load API Key
    api_key = load_api_key()
    
    if not api_key:
        # Nhập API Key manually
        api_key = input("Nhập Google AI API Key: ").strip()
        if not api_key:
            print("❌ API Key không được để trống!")
            return
        
        # Hỏi có muốn lưu vào config.json không
        save_key = input("💾 Lưu API key vào config.json? (y/N): ").lower().strip()
        if save_key == 'y':
            try:
                config = {'api_key': api_key}
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)
                print("✅ Đã lưu API key vào config.json")
            except Exception as e:
                print(f"⚠️ Lỗi lưu config: {e}")
    else:
        print(f"🔑 API Key: {api_key[:10]}***{api_key[-10:]}")
    
    # Nhập đường dẫn file input
    input_file = input("Nhập đường dẫn file truyện cần dịch: ").strip()
    if not input_file:
        print("❌ Đường dẫn file không được để trống!")
        return
    
    # Kiểm tra file tồn tại
    if not os.path.exists(input_file):
        print(f"❌ File không tồn tại: {input_file}")
        return
    
    # Tùy chọn file output (có thể để trống)
    output_file = input("Nhập đường dẫn file output (để trống để tự động tạo): ").strip()
    if not output_file:
        output_file = None
        print("📝 Sẽ tự động tạo tên file output")
    
    # Tùy chọn model
    print("\nChọn model:")
    print("1. gemini-2.0-flash (khuyến nghị)")
    print("2. gemini-1.5-flash")
    print("3. gemini-1.5-pro")
    
    model_choice = input("Nhập lựa chọn (1-3, mặc định 1): ").strip()
    model_map = {
        "1": "gemini-2.0-flash",
        "2": "gemini-1.5-flash", 
        "3": "gemini-1.5-pro",
        "": "gemini-2.0-flash"  # Default
    }
    
    model_name = model_map.get(model_choice, "gemini-2.0-flash")
    print(f"📱 Sử dụng model: {model_name}")
    
    # Xác nhận trước khi bắt đầu
    print(f"\n📋 Thông tin dịch:")
    print(f"  Input: {input_file}")
    print(f"  Output: {output_file or 'Tự động tạo'}")
    print(f"  Model: {model_name}")
    print(f"  Threads: {get_optimal_threads()}")
    print(f"  Chunk size: {CHUNK_SIZE_LINES} dòng")
    
    confirm = input("\n🚀 Bắt đầu dịch? (y/N): ").lower().strip()
    if confirm != 'y':
        print("❌ Hủy bỏ.")
        return
    
    # Bắt đầu dịch
    print("\n" + "="*50)
    try:
        success = translate_file_optimized(
            input_file=input_file,
            output_file=output_file,
            api_key=api_key,
            model_name=model_name
        )
        
        if success:
            print("\n🎉 Dịch hoàn thành thành công!")
        else:
            print("\n⚠️ Dịch chưa hoàn thành.")
            
    except KeyboardInterrupt:
        print("\n\n⏹️ Người dùng dừng chương trình.")
        print("💾 Tiến độ đã được lưu, có thể tiếp tục sau.")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}")


if __name__ == "__main__":
    main()