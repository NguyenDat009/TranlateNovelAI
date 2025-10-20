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
        def exponential_backoff_sleep(retry_count, base_delay=2.0, max_delay=120.0):
            """
            Improved exponential backoff với jitter để tránh thundering herd
            """
            import random
            
            # Tính delay cơ bản với exponential backoff
            delay = base_delay * (2 ** retry_count)
            
            # Thêm jitter (random factor) để tránh nhiều thread retry cùng lúc
            jitter = random.uniform(0.1, 0.5)  # 10-50% jitter
            delay = delay * (1 + jitter)
            
            # Giới hạn max delay
            delay = min(delay, max_delay)
            
            print(f"💤 Exponential backoff: {delay:.1f}s (retry #{retry_count + 1})")
            time.sleep(delay)
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
MAX_RETRIES_ON_RATE_LIMIT = 5  # Tăng số lần retry khi gặp rate limit để xử lý tốt hơn
RETRY_DELAY_SECONDS = 2
PROGRESS_FILE_SUFFIX = ".progress.json"
CHUNK_SIZE = 1024 * 1024  # 1MB (Không còn dùng trực tiếp CHUNK_SIZE cho việc đọc file nữa)

# --- ADAPTIVE THREAD SCALING ---
class AdaptiveThreadManager:
    """
    Quản lý adaptive thread scaling - tự động điều chỉnh threads dựa trên rate limit
    """
    def __init__(self, initial_threads, min_threads=2, max_threads=50):
        self.current_threads = initial_threads
        self.initial_threads = initial_threads
        self.min_threads = min_threads
        self.max_threads = max_threads
        
        # Tracking rate limit
        self.rate_limit_count = 0
        self.total_requests = 0
        self.successful_requests = 0
        
        # Scaling parameters
        self.rate_limit_threshold = 0.3  # 30% rate limit triggers scaling down
        self.scale_down_factor = 0.6     # Giảm 40% threads
        self.scale_up_factor = 1.2       # Tăng 20% threads
        self.min_requests_for_scaling = 20  # Tối thiểu requests để đánh giá
        
        # Cooldown để tránh oscillation
        self.last_scale_time = 0
        self.scale_cooldown = 30  # 30 giây cooldown
        
        import threading
        self.lock = threading.Lock()
        
    def report_rate_limit(self):
        """Báo cáo gặp rate limit"""
        with self.lock:
            self.rate_limit_count += 1
            self.total_requests += 1
            self._evaluate_scaling()
    
    def report_success(self):
        """Báo cáo request thành công"""
        with self.lock:
            self.successful_requests += 1
            self.total_requests += 1
            self._evaluate_scaling()
    
    def report_other_error(self):
        """Báo cáo lỗi khác (không phải rate limit)"""
        with self.lock:
            self.total_requests += 1
    
    def _evaluate_scaling(self):
        """Đánh giá và thực hiện scaling nếu cần"""
        import time
        
        # Chỉ đánh giá sau khi có đủ data
        if self.total_requests < self.min_requests_for_scaling:
            return
            
        # Kiểm tra cooldown
        current_time = time.time()
        if current_time - self.last_scale_time < self.scale_cooldown:
            return
        
        # Tính rate limit ratio
        rate_limit_ratio = self.rate_limit_count / self.total_requests
        success_ratio = self.successful_requests / self.total_requests
        
        print(f"📊 Thread Manager Stats: Rate Limit: {rate_limit_ratio:.1%}, Success: {success_ratio:.1%}, Current Threads: {self.current_threads}")
        
        # Scale down nếu rate limit cao
        if rate_limit_ratio > self.rate_limit_threshold and self.current_threads > self.min_threads:
            new_threads = max(int(self.current_threads * self.scale_down_factor), self.min_threads)
            if new_threads < self.current_threads:
                self.current_threads = new_threads
                self.last_scale_time = current_time
                self._reset_stats()
                print(f"🔻 SCALE DOWN: Giảm threads xuống {self.current_threads} do rate limit cao ({rate_limit_ratio:.1%})")
                return True
        
        # Scale up nếu success rate cao và ít rate limit
        elif rate_limit_ratio < 0.1 and success_ratio > 0.8 and self.current_threads < self.initial_threads:
            new_threads = min(int(self.current_threads * self.scale_up_factor), self.initial_threads)
            if new_threads > self.current_threads:
                self.current_threads = new_threads
                self.last_scale_time = current_time
                self._reset_stats()
                print(f"🔺 SCALE UP: Tăng threads lên {self.current_threads} do performance tốt")
                return True
                
        return False
    
    def _reset_stats(self):
        """Reset statistics sau khi scale"""
        self.rate_limit_count = 0
        self.total_requests = 0
        self.successful_requests = 0
    
    def get_current_threads(self):
        """Lấy số threads hiện tại"""
        with self.lock:
            return self.current_threads
    
    def should_restart_with_new_threads(self):
        """Kiểm tra xem có cần restart với threads mới không"""
        with self.lock:
            return self.current_threads != self.initial_threads

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
            print(f"Key Rotator: Da khoi tao voi {len(self.keys)} keys")
            print(f"He thong se tu dong xoay vong giua cac keys de toi uu RPM")
    
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

def check_openrouter_rate_limit_error(error_message):
    """Kiểm tra lỗi Rate Limit (429) - có thể retry"""
    error_str = str(error_message).lower()
    rate_limit_keywords = [
        "rate limit exceeded",
        "rate_limit_exceeded", 
        "429",
        "too many requests",
        "requests per minute",
        "requests per second"
    ]
    return any(keyword in error_str for keyword in rate_limit_keywords)

def check_openrouter_quota_error(error_message):
    """Kiểm tra lỗi Quota/Credit Insufficient (402) - cần nạp credit"""
    error_str = str(error_message).lower()
    quota_keywords = [
        "402",
        "insufficient credits",
        "insufficient_credits",
        "exceeded your current quota", 
        "quota exceeded",
        "billing",
        "please check your plan",
        "credits",
        "balance"
    ]
    # KHÔNG BAO GỒM "429" và "rate limit" - đó là lỗi khác!
    return any(keyword in error_str for keyword in quota_keywords)

def check_openrouter_api_key_error(error_message):
    """Kiểm tra lỗi API Key không hợp lệ (401)"""
    error_str = str(error_message).lower()
    api_key_keywords = [
        "401",
        "unauthorized", 
        "invalid credentials",
        "invalid_credentials",
        "api key not valid", 
        "invalid api key", 
        "authentication failed",
        "api_key_invalid", 
        "invalid_api_key", 
        "api key is invalid", 
        "bad api key"
    ]
    return any(keyword in error_str for keyword in api_key_keywords)

def check_openrouter_moderation_error(error_message):
    """Kiểm tra lỗi Moderation (403) - nội dung bị cấm"""
    error_str = str(error_message).lower()
    moderation_keywords = [
        "403",
        "moderation",
        "content policy",
        "content_policy",
        "policy violation",
        "blocked content",
        "inappropriate content"
    ]
    return any(keyword in error_str for keyword in moderation_keywords)

def check_openrouter_timeout_error(error_message):
    """Kiểm tra lỗi Timeout (408) - có thể retry"""
    error_str = str(error_message).lower()
    timeout_keywords = [
        "408",
        "timeout",
        "request timeout",
        "gateway timeout",
        "timed out"
    ]
    return any(keyword in error_str for keyword in timeout_keywords)

def check_openrouter_service_error(error_message):
    """Kiểm tra lỗi Service (502, 503) - có thể retry"""
    error_str = str(error_message).lower()
    service_keywords = [
        "502",
        "503", 
        "bad gateway",
        "service unavailable",
        "server error",
        "internal server error",
        "model unavailable",
        "provider unavailable"
    ]
    return any(keyword in error_str for keyword in service_keywords)

# Legacy functions for backward compatibility
def check_quota_error(error_message):
    """Legacy function - sử dụng check_openrouter_quota_error thay thế"""
    return check_openrouter_quota_error(error_message)

def check_api_key_error(error_message):
    """Legacy function - sử dụng check_openrouter_api_key_error thay thế"""
    return check_openrouter_api_key_error(error_message)

def validate_api_key_before_translation(api_key, model_name, provider="OpenRouter"):
    """Validate API key trước khi bắt đầu translation"""
    try:
        if provider == "Google AI":
            # Test Google AI API
            import google.generativeai as genai
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            
            # Test với content nhỏ để kiểm tra quota
            test_content = "Hello, test quota"
            response = model.generate_content(test_content)
            
            if response and response.text:
                # Thêm thông tin về project ID nếu có thể
                masked_key = api_key[:10] + "***" + api_key[-10:] if len(api_key) > 20 else "***"
                return True, f"Google AI API key hợp lệ ({masked_key})"
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
                return False, "OpenRouter API Key không hợp lệ (401: Invalid Credentials)"
            elif response.status_code == 402:
                return False, "Tài khoản OpenRouter hết credit (402: Insufficient Credits)"
            elif response.status_code == 403:
                return False, "OpenRouter API bị chặn (403: Moderation Error)"
            elif response.status_code == 429:
                return False, "OpenRouter API bị rate limit (429: Too Many Requests) - thử lại sau"
            elif response.status_code in [502, 503]:
                return False, f"OpenRouter service tạm thời lỗi ({response.status_code}) - thử lại sau"
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

def get_optimal_threads(num_api_keys=1, provider="OpenRouter"):
    """
    Tự động tính toán số threads tối ưu dựa trên cấu hình máy và số lượng API keys.
    
    Args:
        num_api_keys: Số lượng API keys (để tính toán threads phù hợp)
        provider: Provider đang sử dụng
    """
    try:
        # Lấy số CPU cores
        cpu_cores = cpu_count()
        
        if provider == "Google AI" and num_api_keys > 1:
            # Với Google AI multiple keys, tính toán dựa trên keys
            base_threads_per_key = 1.5  # Trung bình 1.5 threads/key
            threads_from_keys = int(num_api_keys * base_threads_per_key)
            threads_from_cpu = min(cpu_cores * 3, 50)  # I/O bound
            
            optimal_threads = min(threads_from_keys, threads_from_cpu)
            optimal_threads = max(optimal_threads, min(num_api_keys, 5))  # Tối thiểu
            optimal_threads = min(optimal_threads, 50)  # Tối đa
            
            print(f"Phat hien {cpu_cores} CPU cores")
            print(f"Google AI voi {num_api_keys} keys:")
            print(f"  Keys: {num_api_keys} x {base_threads_per_key} = {threads_from_keys} threads")
            print(f"  CPU: {cpu_cores} x 3 = {threads_from_cpu} threads")
            print(f"  Threads toi uu: {optimal_threads}")
        else:
            # Logic cũ cho single key hoặc OpenRouter
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
        elif chunk_size > 2000:  # Tránh chunks quá lớn
            return 2000
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


def is_bad_translation(text, input_text=None):
    """
    Kiểm tra xem bản dịch của chunk có đạt yêu cầu không.
    
    Args:
        text: Văn bản đã dịch
        input_text: Văn bản gốc để so sánh kích thước
        
    Returns:
        True nếu bản dịch không đạt yêu cầu, False nếu đạt yêu cầu.
    """
    if text is None or text.strip() == "":
        # Chunk dịch ra rỗng hoặc chỉ trắng => coi là bad translation
        return True

    # Các từ khóa chỉ báo bản dịch không đạt yêu cầu
    bad_keywords = [
        "tôi không thể dịch",
        "không thể dịch",
        "xin lỗi, tôi không",
        "tôi xin lỗi",
        "nội dung bị chặn",
        "as an ai",
        "as a language model",
        "i am unable",
        "i cannot",
        "i'm sorry",
        "[bị cắt - cần chunk nhỏ hơn]",
        "[có thể bị thiếu]"
    ]

    text_lower = text.lower()
    for keyword in bad_keywords:
        if keyword in text_lower:
            return True

    text_stripped = text.strip()
    
    # Kiểm tra response có hoàn chỉnh không dựa trên ký tự cuối
    if len(text_stripped) > 20:  # Chỉ check với text đủ dài
        last_char = text_stripped[-1]
        
        # Ký tự cuối hợp lệ (response hoàn chỉnh)
        valid_ending_chars = '.!?。！？"』」)）…—'
        
        # Ký tự cuối không hợp lệ (response chưa hoàn chỉnh)
        invalid_ending_chars = ' \t\n'  # space, tab, newline
        
        # Nếu kết thúc bằng ký tự không hợp lệ -> response chưa hoàn chỉnh
        if last_char in invalid_ending_chars:
            print(f"⚠️ Response chưa hoàn chỉnh: kết thúc bằng ký tự trắng '{repr(last_char)}'")
            return True
            
    # User request: Nếu response dài từ 80-100% so với gốc, bỏ qua kiểm tra ký tự cuối
    if input_text:
        input_length = len(input_text.strip())
        output_length = len(text_stripped)
        ratio = output_length / input_length if input_length > 0 else 0
        if 0.8 < ratio < 1.0:
            print(f"✅ Response có độ dài phù hợp ({ratio:.1%}), bỏ qua kiểm tra ký tự cuối.")
            return False # Coi là hoàn thành
            
    # Kiểm tra trường hợp ngoại lệ: tiêu đề chương và nội dung chương
    text_lower = text_stripped.lower()
    is_chapter_title = False
    is_chapter_content = False
    
    # Các pattern tiêu đề chương (thường ở đầu dòng)
    chapter_patterns = [
        r'^chương\s+\d+',          # "chương 1", "chương 23"
        r'^chương\s+[ivxlc]+',     # "chương i", "chương iv"  
        r'^chapter\s+\d+',         # "chapter 1", "chapter 23"
        r'^第\d+章',                # "第1章", "第23章"
        r'^phần\s+\d+',            # "phần 1", "phần 2"
        r'^tập\s+\d+',             # "tập 1", "tập 2"
    ]
    
    # Kiểm tra xem có phải tiêu đề chương thuần túy không (ngắn, chỉ có tiêu đề)
    for pattern in chapter_patterns:
        if re.search(pattern, text_lower) and len(text_stripped) < 200:
            is_chapter_title = True
            break
    
    # Nếu không phải tiêu đề chương thuần túy, kiểm tra có phải nội dung chứa chương không
    if not is_chapter_title:
        chapter_keywords = ['chương', 'chapter', '第', 'phần', 'tập']
        for keyword in chapter_keywords:
            if keyword in text_lower:
                is_chapter_content = True
                break
    
    # Xử lý theo loại nội dung
    if is_chapter_title:
        # Tiêu đề chương thuần túy (ngắn) - có thể kết thúc bằng chữ cái/số
        valid_chapter_endings = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:-–—')
        if last_char in valid_chapter_endings or last_char in valid_ending_chars:
            print(f"✅ Phát hiện tiêu đề chương, cho phép kết thúc bằng '{last_char}'")
            # Tiêu đề chương không cần kiểm tra strict về ký tự cuối
            pass  
        else:
            print(f"⚠️ Tiêu đề chương nhưng kết thúc bất thường: '{last_char}'")
            return True
    elif is_chapter_content:
        # Nội dung có chứa chương (dài) - áp dụng rule thông thường nhưng linh hoạt hơn
        if last_char in valid_ending_chars:
            print(f"✅ Nội dung chương kết thúc hợp lệ bằng '{last_char}'")
            # Dấu câu hợp lệ, không coi là bad
            pass
        elif last_char.isalpha():
            print(f"⚠️ Nội dung chương có thể chưa hoàn chỉnh: kết thúc bằng chữ cái '{last_char}'")
            return True
        elif last_char.isdigit():
            print(f"ℹ️ Nội dung chương kết thúc bằng số '{last_char}' - có thể hợp lệ")
            # Số có thể hợp lệ trong nội dung chương, không coi là bad
            pass
        else:
            print(f"⚠️ Nội dung chương kết thúc bất thường: '{last_char}'")
            return True
    else:
        # Nội dung thông thường - áp dụng rule nghiêm ngặt
        if last_char.isalpha():
            print(f"⚠️ Response có thể chưa hoàn chỉnh: kết thúc bằng chữ cái '{last_char}'")
            return True
        
    # Nếu kết thúc bằng dấu câu hợp lệ -> response có thể hoàn chỉnh
    if last_char in valid_ending_chars:
        # Nhưng vẫn cần kiểm tra kích thước nếu có input_text
        pass
    
    # Kiểm tra kích thước output so với input (50-60% threshold)
    if input_text and len(input_text.strip()) > 50:  # Chỉ check với input đủ dài
        input_length = len(input_text.strip())
        output_length = len(text_stripped)
        
        # Tính tỷ lệ output/input
        ratio = output_length / input_length if input_length > 0 else 0
        
        # Sử dụng cờ is_chapter_content hoặc is_chapter_title đã được xác định ở trên
        # Nếu chưa được xác định, kiểm tra lại
        if not (is_chapter_content or is_chapter_title):
            text_lower = text_stripped.lower()
            input_lower = input_text.lower()
            chapter_keywords = ['chương', 'chapter', '第', 'phần', 'tập']
            for keyword in chapter_keywords:
                if keyword in text_lower or keyword in input_lower:
                    is_chapter_content = True
                    break
        
        # Nếu là nội dung có chương, áp dụng threshold linh hoạt hơn
        if is_chapter_content or is_chapter_title:
            # Tiêu đề chương thường ngắn hơn, threshold thấp hơn (30% thay vì 50%)
            min_ratio = 0.3
            warning_ratio = 0.4
            
            if ratio < min_ratio:
                print(f"⚠️ Output quá ngắn so với input (chương): {ratio:.2%} (Input: {input_length} chars, Output: {output_length} chars)")
                return True
            elif ratio < warning_ratio:
                print(f"ℹ️ Output hơi ngắn nhưng có thể là tiêu đề chương: {ratio:.2%} (Input: {input_length} chars, Output: {output_length} chars)")
                # Đối với tiêu đề chương, chỉ coi là bad nếu kết thúc rất bất thường
                if len(text_stripped) > 20:
                    last_char = text_stripped[-1]
                    if last_char in ' \t\n':  # Chỉ coi là bad nếu kết thúc bằng whitespace
                        return True
        else:
            # Nội dung thông thường, áp dụng threshold chuẩn
            if ratio < 0.5:
                print(f"⚠️ Output quá ngắn so với input: {ratio:.2%} (Input: {input_length} chars, Output: {output_length} chars)")
                return True
            elif ratio < 0.6:
                print(f"⚠️ Output hơi ngắn so với input: {ratio:.2%} (Input: {input_length} chars, Output: {output_length} chars)")
                # Chỉ coi là bad nếu kết thúc không hợp lệ
                if len(text_stripped) > 20:
                    last_char = text_stripped[-1]
                    if last_char.isalpha() or last_char in ' \t\n':
                        return True
    
    return False

def translate_chunk(model, chunk_lines, system_instruction, context="modern"):
    """
    Dịch một chunk gồm nhiều dòng văn bản.
    chunk_lines: danh sách các dòng văn bản
    context: "modern" (hiện đại) hoặc "ancient" (cổ đại)
    system_instruction: Chỉ dẫn hệ thống đầy đủ từ GUI
    Trả về (translated_text, is_safety_blocked_flag, is_bad_translation_flag).
    """
    # Gom các dòng thành một chuỗi lớn để gửi đi
    full_text_to_translate = "\n".join(chunk_lines)
    
    # Bỏ qua các chunk chỉ chứa các dòng trống hoặc chỉ trắng
    if not full_text_to_translate.strip():
        return ("", False, False) # Trả về chuỗi rỗng, không bị chặn, không bad translation

    try:
        # Sử dụng system_instruction được truyền vào và thêm văn bản cần dịch
        # Điều này đảm bảo prompt từ GUI được sử dụng
        prompt = f"{system_instruction}\n\n{full_text_to_translate}"
        
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
        
        # 4. Kiểm tra nếu response bị cắt do vượt quá max_tokens
        finish_reason_name = str(first_candidate.finish_reason)
        if 'MAX_TOKENS' in finish_reason_name or finish_reason_name == 'LENGTH':
            print(f"⚠️ Cảnh báo Google AI: Response bị cắt (finish_reason={finish_reason_name})")
            translated_text = response.text
            # Đánh dấu là bad translation để trigger re-chunk logic
            return (translated_text + " [BỊ CẮT - CẦN CHUNK NHỎ HƠN]", False, True)

        # Nếu không bị chặn, trả về văn bản dịch
        translated_text = response.text
        is_bad = is_bad_translation(translated_text, full_text_to_translate)
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

def split_large_chunk(chunk_lines, max_lines=50):
    """
    Chia một chunk lớn thành các chunks nhỏ hơn khi gặp lỗi context length exceeded
    """
    if len(chunk_lines) <= max_lines:
        return [chunk_lines]
    
    sub_chunks = []
    for i in range(0, len(chunk_lines), max_lines):
        sub_chunk = chunk_lines[i:i + max_lines]
        sub_chunks.append(sub_chunk)
    
    return sub_chunks

def translate_sub_chunk_recursive(model, sub_chunk, system_instruction, context, chunk_index, sub_index, 
                                   level=1, max_level=3, use_google_ai=True, use_openrouter=False, 
                                   api_key=None, model_name=None, openrouter_translate_chunk=None, 
                                   key_rotator=None, tried_keys=None):
    """
    Dịch sub-chunk với khả năng chia nhỏ recursive đến 3 cấp độ.
    Nếu chia 3 levels vẫn thất bại, thử retry với API key khác (Google AI only).
    
    Args:
        level: Cấp độ hiện tại (1, 2, hoặc 3)
        max_level: Cấp độ tối đa (default 3)
        key_rotator: KeyRotator object để lấy key khác khi cần retry
        tried_keys: Set các keys đã thử để tránh retry lặp lại
        
    Returns:
        (translated_text, success_flag)
    """
    level_prefix = "   " * level  # Indent theo level
    
    # Initialize tried_keys tracking
    if tried_keys is None:
        tried_keys = set()
    
    if level > max_level:
        print(f"{level_prefix}⚠️ Đã đạt cấp độ tối đa ({max_level}), lưu kết quả hiện tại")
        return (f"[CẤP ĐỘ TỐI ĐA - KHÔNG THỂ CHIA NHỎ HƠN]", False)
    
    # Kiểm tra chunk quá nhỏ
    min_lines_per_level = [10, 5, 3]  # Level 1: 10, Level 2: 5, Level 3: 3
    min_lines = min_lines_per_level[min(level - 1, len(min_lines_per_level) - 1)]
    
    if len(sub_chunk) < min_lines:
        print(f"{level_prefix}⚠️ Sub-chunk quá nhỏ ({len(sub_chunk)} dòng), không thể chia thêm")
        return (f"[QUÁ NHỎ - {len(sub_chunk)} DÒNG]", False)
    
    try:
        print(f"{level_prefix}🔄 Level {level} - Đang dịch sub-chunk {sub_index} ({len(sub_chunk)} dòng)...")
        
        # Thử dịch sub-chunk
        if use_google_ai:
            translated_sub, safety_sub, is_bad_sub = translate_chunk(model, sub_chunk, system_instruction, context)
        elif use_openrouter:
            translated_sub, safety_sub, is_bad_sub = openrouter_translate_chunk(api_key, model_name, system_instruction, sub_chunk, context)
        else:
            return (f"[PROVIDER ERROR]", False)
        
        # Xử lý các trường hợp response
        if safety_sub:
            print(f"{level_prefix}⚠️ Level {level} - Bị safety block, vẫn lưu kết quả")
            return (translated_sub + f" [SAFETY-L{level}]", True)  # True vì vẫn có kết quả
        
        # Kiểm tra nếu bị cắt
        if "[BỊ CẮT - CẦN CHUNK NHỎ HƠN]" in translated_sub:
            print(f"{level_prefix}🔄 Level {level} - Bị cắt, chia nhỏ xuống level {level + 1}...")
            return split_and_translate_recursive(model, sub_chunk, system_instruction, context, 
                                                chunk_index, sub_index, level + 1, max_level,
                                                use_google_ai, use_openrouter, api_key, model_name, 
                                                openrouter_translate_chunk, key_rotator, tried_keys)
        
        if not is_bad_sub:
            print(f"{level_prefix}✅ Level {level} - Sub-chunk {sub_index} thành công")
            return (translated_sub, True)
        else:
            # Bad translation - retry 1 lần rồi chia nhỏ
            print(f"{level_prefix}⚠️ Level {level} - Bad translation, retry 1 lần...")
            time.sleep(1)
            
            if use_google_ai:
                translated_retry, safety_retry, is_bad_retry = translate_chunk(model, sub_chunk, system_instruction, context)
            elif use_openrouter:
                translated_retry, safety_retry, is_bad_retry = openrouter_translate_chunk(api_key, model_name, system_instruction, sub_chunk, context)
            
            if not is_bad_retry and not safety_retry:
                print(f"{level_prefix}✅ Level {level} - Retry thành công")
                return (translated_retry, True)
            else:
                # Vẫn bad sau retry - chia nhỏ
                print(f"{level_prefix}🔄 Level {level} - Vẫn bad sau retry, chia nhỏ xuống level {level + 1}...")
                return split_and_translate_recursive(model, sub_chunk, system_instruction, context,
                                                    chunk_index, sub_index, level + 1, max_level,
                                                    use_google_ai, use_openrouter, api_key, model_name,
                                                    openrouter_translate_chunk, key_rotator, tried_keys)
    
    except Exception as e:
        error_msg = str(e)
        print(f"{level_prefix}❌ Level {level} - Lỗi: {error_msg[:100]}")
        
        # Kiểm tra các lỗi có thể chia nhỏ
        if ("context" in error_msg.lower() and "length" in error_msg.lower()) or \
           ("too long" in error_msg.lower()) or \
           ("maximum" in error_msg.lower()):
            print(f"{level_prefix}🔄 Level {level} - Context/length error, chia nhỏ xuống level {level + 1}...")
            return split_and_translate_recursive(model, sub_chunk, system_instruction, context,
                                                chunk_index, sub_index, level + 1, max_level,
                                                use_google_ai, use_openrouter, api_key, model_name,
                                                openrouter_translate_chunk, key_rotator, tried_keys)
        else:
            # Lỗi khác - không thể xử lý
            return (f"[LỖI L{level}: {error_msg[:100]}]", False)

def split_and_translate_recursive(model, chunk_lines, system_instruction, context, chunk_index, 
                                   parent_index, level, max_level, use_google_ai, use_openrouter, 
                                   api_key, model_name, openrouter_translate_chunk, 
                                   key_rotator=None, tried_keys=None):
    """
    Chia chunk và dịch recursive từng phần.
    Nếu thất bại ở level tối đa, thử retry với API key khác (Google AI only).
    
    Returns:
        (combined_text, success_flag)
    """
    level_prefix = "   " * level
    
    # Initialize tried_keys tracking
    if tried_keys is None:
        tried_keys = set()
    
    # Chia chunk thành 2 phần
    mid_point = len(chunk_lines) // 2
    if mid_point < 3:  # Quá nhỏ để chia
        print(f"{level_prefix}⚠️ Chunk quá nhỏ ({len(chunk_lines)} dòng), không thể chia thêm")
        return (f"[QUÁ NHỎ - {len(chunk_lines)} DÒNG]", False)
    
    first_half = chunk_lines[:mid_point]
    second_half = chunk_lines[mid_point:]
    
    print(f"{level_prefix}📦 Chia thành 2 phần: {len(first_half)} + {len(second_half)} dòng")
    
    # Dịch phần 1
    first_result, first_success = translate_sub_chunk_recursive(
        model, first_half, system_instruction, context, chunk_index, f"{parent_index}.1",
        level, max_level, use_google_ai, use_openrouter, api_key, model_name, openrouter_translate_chunk,
        key_rotator, tried_keys
    )
    
    # Dịch phần 2
    second_result, second_success = translate_sub_chunk_recursive(
        model, second_half, system_instruction, context, chunk_index, f"{parent_index}.2",
        level, max_level, use_google_ai, use_openrouter, api_key, model_name, openrouter_translate_chunk,
        key_rotator, tried_keys
    )
    
    # Kết hợp kết quả
    combined = first_result
    if not first_result.endswith('\n'):
        combined += '\n'
    combined += second_result
    
    success = first_success and second_success
    
    # Nếu thất bại ở level tối đa và có key_rotator (Google AI), thử với key khác
    if not success and level == max_level and use_google_ai and key_rotator and key_rotator.is_multi_key:
        current_key_hash = _get_key_hash(api_key) if api_key else None
        
        # Đánh dấu key hiện tại đã thử
        if current_key_hash:
            tried_keys.add(current_key_hash)
        
        # Thử lấy key khác chưa thử
        available_keys = [k for k in key_rotator.keys if _get_key_hash(k) not in tried_keys]
        
        if available_keys:
            new_key = available_keys[0]
            new_key_hash = _get_key_hash(new_key)
            tried_keys.add(new_key_hash)
            
            print(f"{level_prefix}🔄 Chia 3 levels vẫn thất bại, thử lại với API key khác (Key #{len(tried_keys)})...")
            
            # Tạo model mới với key mới
            import google.generativeai as genai
            genai.configure(api_key=new_key)
            new_model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                },
                safety_settings={
                    "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
                }
            )
            
            # Retry toàn bộ chunk với key mới từ level 1
            retry_result, retry_success = split_and_translate_recursive(
                new_model, chunk_lines, system_instruction, context, chunk_index,
                parent_index, 1, max_level, use_google_ai, use_openrouter,
                new_key, model_name, openrouter_translate_chunk,
                key_rotator, tried_keys
            )
            
            if retry_success:
                print(f"{level_prefix}✅ Retry với key khác THÀNH CÔNG!")
                return (retry_result, True)
            else:
                print(f"{level_prefix}❌ Retry với key khác vẫn thất bại")
                # Trả về kết quả ban đầu với marker
                return (combined + f"\n[ĐÃ THỬ {len(tried_keys)} KEYS - VẪN THẤT BẠI]", False)
        else:
            print(f"{level_prefix}⚠️ Đã thử hết {len(tried_keys)} keys, không còn key nào khác")
    
    return (combined, success)

def process_chunk(api_key, model_name, system_instruction, chunk_data, provider="OpenRouter", log_callback=None, key_rotator=None, context="modern", is_paid_key=False, adaptive_thread_manager=None):
    """
    Xử lý dịch một chunk với retry logic, rate limiting và re-chunking.
    chunk_data: tuple (chunk_index, chunk_lines, chunk_start_line_index)
    Trả về: (chunk_index, translated_text, lines_count, line_range)
    
    Args:
        key_rotator: KeyRotator instance nếu sử dụng multiple keys (Google AI only)
        context: "modern" (hiện đại) hoặc "ancient" (cổ đại) để xác định danh xưng người kể chuyện
    """
    chunk_index, chunk_lines, chunk_start_line_index = chunk_data
    
    # Tính toán line range cho chunk hiện tại
    chunk_end_line_index = chunk_start_line_index + len(chunk_lines) - 1
    line_range = f"{chunk_start_line_index + 1}:{chunk_end_line_index + 1}"  # +1 vì line numbers bắt đầu từ 1
    
    # Get current API key (from rotator if available)
    current_api_key = key_rotator.get_next_key() if key_rotator else api_key
    
    # Get rate limiter cho Google AI với specific key (None cho OpenRouter)
    rate_limiter = get_rate_limiter(model_name, provider, current_api_key if provider == "Google AI" else None, is_paid_key=is_paid_key)
    
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
    
    # Khởi tạo biến openrouter_translate_chunk trước (để tránh lỗi UnboundLocalError)
    openrouter_translate_chunk = None
    
    if use_google_ai:
        # Setup Google AI (với current API key từ rotator)
        try:
            import google.generativeai as genai
            genai.configure(api_key=current_api_key)
            model = genai.GenerativeModel(model_name)
        except ImportError:
            error_text = format_error_chunk("IMPORT ERROR", "Google AI module không tìm thấy. Vui lòng cài đặt: pip install google-generativeai", chunk_lines, line_range)
            return (chunk_index, error_text, len(chunk_lines), line_range)
    
    if use_openrouter:
        # Import OpenRouter translate function - dùng tên tạm để tránh UnboundLocalError
        try:
            from .open_router_translate import translate_chunk as _openrouter_func
            openrouter_translate_chunk = _openrouter_func
        except ImportError:
            try:
                from open_router_translate import translate_chunk as _openrouter_func
                openrouter_translate_chunk = _openrouter_func
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
                            # Dịch với Google AI sử dụng hàm translate_chunk với system_instruction đầy đủ
                            translated_text, is_safety_blocked, is_bad = translate_chunk(model, chunk_lines, system_instruction, context)
                            
                            # Báo success cho adaptive throttling
                            if rate_limiter:
                                rate_limiter.on_success()
                            
                            # Báo success cho adaptive thread manager
                            if adaptive_thread_manager:
                                adaptive_thread_manager.report_success()
                            
                            break  # Success, thoát khỏi rate limit retry loop
                                
                        elif use_openrouter:
                            translated_text, is_safety_blocked, is_bad = openrouter_translate_chunk(api_key, model_name, system_instruction, chunk_lines, context)
                            
                            # Báo success cho adaptive thread manager
                            if adaptive_thread_manager:
                                adaptive_thread_manager.report_success()
                            
                            break  # Success, thoát khỏi rate limit retry loop
                        else:
                            error_text = format_error_chunk("PROVIDER ERROR", f"Provider không được hỗ trợ: {provider}", chunk_lines, line_range)
                            return (chunk_index, error_text, len(chunk_lines), line_range)
                            
                    except Exception as rate_error:
                        error_msg = str(rate_error)
                        
                        # Kiểm tra nếu là rate limit error
                        if is_rate_limit_error(error_msg) and rate_limit_retry < MAX_RETRIES_ON_RATE_LIMIT:
                            rate_limit_retry += 1
                            print(f"🔄 Rate limit error ở chunk {chunk_index}, retry {rate_limit_retry}/{MAX_RETRIES_ON_RATE_LIMIT}")
                            print(f"📝 Error detail: {error_msg[:200]}...")  # Log chi tiết lỗi
                            
                            # Báo rate limit error cho adaptive throttling
                            if rate_limiter and use_google_ai:
                                rate_limiter.on_rate_limit_error()
                            
                            # Báo rate limit cho adaptive thread manager
                            if adaptive_thread_manager:
                                adaptive_thread_manager.report_rate_limit()
                            
                            # Sử dụng exponential backoff tốt hơn với base delay cao hơn cho rate limit
                            exponential_backoff_sleep(rate_limit_retry - 1, base_delay=8.0, max_delay=300.0)
                            continue
                        else:
                            # Không phải rate limit error hoặc hết retry
                            # Báo lỗi khác cho adaptive thread manager
                            if adaptive_thread_manager:
                                adaptive_thread_manager.report_other_error()
                            raise  # Re-raise để xử lý ở catch block bên ngoài
                
                # Kiểm tra quota exceeded sau khi dịch
                if is_quota_exceeded():
                    error_text = format_error_chunk("API HẾT QUOTA", "API đã hết quota sau khi dịch", chunk_lines, line_range)
                    return (chunk_index, error_text, len(chunk_lines), line_range)
                
                # Log successful request với key info để track quota usage
                if use_google_ai and current_api_key:
                    key_hash = _get_key_hash(current_api_key)
                    print(f"✅ Chunk {chunk_index}: Key ***{key_hash} - Success")
                
                if is_safety_blocked:
                    break # Thoát khỏi vòng lặp bad translation, sẽ retry safety
                    
                if not is_bad:
                    return (chunk_index, translated_text, len(chunk_lines), line_range) # Thành công
                    
                # Bản dịch xấu, thử lại
                bad_translation_retries += 1
                
                # Kiểm tra nếu bị cắt do max_tokens - chia nhỏ ngay lập tức với recursive 3 level
                if "[BỊ CẮT - CẦN CHUNK NHỎ HƠN]" in translated_text and len(chunk_lines) > 3:
                    print(f"🔄 Chunk {chunk_index} bị cắt (max_tokens), sử dụng recursive splitting...")
                    
                    # Sử dụng recursive splitting với key_rotator support
                    combined_result, success = split_and_translate_recursive(
                        model, chunk_lines, system_instruction, context, chunk_index, "cut",
                        level=1, max_level=3, use_google_ai=use_google_ai, use_openrouter=use_openrouter,
                        api_key=api_key, model_name=model_name, openrouter_translate_chunk=openrouter_translate_chunk,
                        key_rotator=key_rotator
                    )
                    
                    if success:
                        print(f"✅ Chunk {chunk_index} đã được chia nhỏ recursive và dịch thành công")
                    else:
                        print(f"⚠️ Chunk {chunk_index} đã chia nhỏ recursive nhưng một số phần thất bại")
                    
                    return (chunk_index, combined_result, len(chunk_lines), line_range)
                
                if bad_translation_retries < MAX_RETRIES_ON_BAD_TRANSLATION:
                    print(f"⚠️ Chunk {chunk_index} - bản dịch xấu lần {bad_translation_retries}, thử lại...")
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    # Hết lần thử bad translation, thử chia nhỏ chunk với recursive 3 level
                    if len(chunk_lines) > 3:
                        print(f"🔄 Chunk {chunk_index} vẫn bad sau {MAX_RETRIES_ON_BAD_TRANSLATION} lần thử, sử dụng recursive splitting...")
                        
                        # Sử dụng recursive splitting với key_rotator support
                        combined_result, success = split_and_translate_recursive(
                            model, chunk_lines, system_instruction, context, chunk_index, "bad",
                            level=1, max_level=3, use_google_ai=use_google_ai, use_openrouter=use_openrouter,
                            api_key=api_key, model_name=model_name, openrouter_translate_chunk=openrouter_translate_chunk,
                            key_rotator=key_rotator
                        )
                        
                        if success:
                            print(f"✅ Chunk {chunk_index} đã được chia nhỏ recursive và dịch thành công")
                        else:
                            print(f"⚠️ Chunk {chunk_index} đã chia nhỏ recursive nhưng một số phần thất bại")
                        
                        return (chunk_index, combined_result, len(chunk_lines), line_range)
                    else:
                        # Chunk đã nhỏ, không thể chia thêm
                        print(f"💾 Chunk {chunk_index} - đã thử {MAX_RETRIES_ON_BAD_TRANSLATION} lần và quá nhỏ để chia, lưu kết quả hiện tại")
                        return (chunk_index, translated_text + " [KHÔNG CẢI THIỆN ĐƯỢC]", len(chunk_lines), line_range)
                    
            except Exception as e:
                error_msg = str(e)
                
                # Xử lý lỗi theo provider
                if use_google_ai:
                    # Google AI specific error handling
                    if check_quota_error(error_msg):
                        # Google AI quota exceeded
                        set_quota_exceeded()
                        error_text = format_error_chunk("API HẾT QUOTA", f"Google AI hết quota: {error_msg}", chunk_lines, line_range)
                        return (chunk_index, error_text, len(chunk_lines), line_range)
                    elif is_rate_limit_error(error_msg):
                        # Google AI rate limit - có thể retry
                        print(f"⚠️ Google AI rate limit tại chunk {chunk_index}, sẽ retry...")
                        continue
                    elif "context_length" in error_msg.lower() or "too long" in error_msg.lower() or "maximum" in error_msg.lower():
                        # Context length error - chia nhỏ chunk với recursive 3 level
                        if len(chunk_lines) > 3:
                            print(f"🔄 Chunk {chunk_index} quá lớn cho Google AI (context_length), sử dụng recursive splitting...")
                            
                            # Sử dụng recursive splitting với key_rotator support
                            combined_result, success = split_and_translate_recursive(
                                model, chunk_lines, system_instruction, context, chunk_index, "ctx",
                                level=1, max_level=3, use_google_ai=use_google_ai, use_openrouter=use_openrouter,
                                api_key=api_key, model_name=model_name, openrouter_translate_chunk=openrouter_translate_chunk,
                                key_rotator=key_rotator
                            )
                            
                            if success:
                                print(f"✅ Chunk {chunk_index} context_length đã được xử lý thành công")
                            else:
                                print(f"⚠️ Chunk {chunk_index} context_length xử lý nhưng có một số phần thất bại")
                            
                            return (chunk_index, combined_result, len(chunk_lines), line_range)
                        else:
                            # Chunk quá nhỏ nhưng vẫn context_length error - lỗi nghiêm trọng
                            error_text = format_error_chunk("CONTEXT LENGTH ERROR", f"Chunk quá nhỏ ({len(chunk_lines)} dòng) nhưng vẫn bị context_length: {error_msg}", chunk_lines, line_range)
                            return (chunk_index, error_text, len(chunk_lines), line_range)
                    else:
                        # Google AI generic error
                        error_text = format_error_chunk("GOOGLE AI ERROR", f"Lỗi Google AI: {error_msg}", chunk_lines, line_range)
                        return (chunk_index, error_text, len(chunk_lines), line_range)
                
                elif use_openrouter:
                    # OpenRouter specific error handling (existing logic)
                    if check_openrouter_quota_error(error_msg):
                        # 402: Insufficient Credits - dừng hoàn toàn
                        set_quota_exceeded()
                        error_text = format_error_chunk("API HẾT QUOTA", f"OpenRouter hết credit (402): {error_msg}", chunk_lines, line_range)
                        return (chunk_index, error_text, len(chunk_lines), line_range)
                
                    elif check_openrouter_api_key_error(error_msg):
                        # 401: Invalid Credentials - dừng hoàn toàn
                        error_text = format_error_chunk("API KEY ERROR", f"API key không hợp lệ (401): {error_msg}", chunk_lines, line_range)
                        return (chunk_index, error_text, len(chunk_lines), line_range)
                
                    elif check_openrouter_rate_limit_error(error_msg):
                        # 429: Rate Limit - có thể retry
                        print(f"⚠️ Rate limit (429) tại chunk {chunk_index}, sẽ retry...")
                        # Để tiếp tục retry loop thay vì return ngay
                        continue
                
                    elif check_openrouter_moderation_error(error_msg):
                        # 403: Moderation - content bị block
                        error_text = format_error_chunk("MODERATION ERROR", f"Nội dung vi phạm chính sách (403): {error_msg}", chunk_lines, line_range)
                        return (chunk_index, error_text, len(chunk_lines), line_range)
                
                    elif check_openrouter_timeout_error(error_msg):
                        # 408: Timeout - có thể retry
                        print(f"⚠️ Timeout (408) tại chunk {chunk_index}, sẽ retry...")
                        continue
                
                    elif check_openrouter_service_error(error_msg):
                        # 502, 503: Service errors - có thể retry
                        print(f"⚠️ Service error (502/503) tại chunk {chunk_index}, sẽ retry...")
                        continue
                
                else:
                    # Generic error cho cả hai provider
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

def retry_failed_chunks(input_file, output_file, progress_file_path, api_key, model_name, system_instruction, provider="OpenRouter", context="modern", is_paid_key=False):
    """
    Retry các chunks đã failed từ lần dịch trước
    Trả về: số chunks đã retry thành công
    """
    if not os.path.exists(progress_file_path):
        return 0
    
    try:
        progress_data = load_progress_with_info(progress_file_path)
        if 'last_error' not in progress_data:
            return 0
        
        print("🔄 Đang retry các chunks bị lỗi từ lần dịch trước...")
        
        # Đọc file để tìm các chunks có error markers
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Tìm các error chunks
        error_pattern = r'\[\[LỖI.*?\]\]'
        error_matches = re.findall(error_pattern, content, re.DOTALL)
        
        if not error_matches:
            print("✅ Không tìm thấy chunks lỗi cần retry")
            return 0
        
        print(f"📝 Tìm thấy {len(error_matches)} chunks cần retry")
        
        # TODO: Implement logic retry các chunks cụ thể
        # Hiện tại chỉ return 0 để không break existing code
        return 0
        
    except Exception as e:
        print(f"⚠️ Lỗi khi retry failed chunks: {e}")
        return 0

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

def translate_file_optimized(input_file, output_file=None, api_key=None, model_name="gemini-2.0-flash", system_instruction=None, num_workers=None, chunk_size_lines=None, provider="OpenRouter", context="modern", is_paid_key=False):
    """
    Phiên bản dịch file với multi-threading chunks.
    
    Args:
        api_key: String (OpenRouter) hoặc List (Google AI multiple keys)
        context: "modern" (hiện đại - dùng "tôi") hoặc "ancient" (cổ đại - dùng "ta")
        is_paid_key: True nếu sử dụng Google AI key trả phí
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
        is_multi_key = isinstance(api_key, list) and len(api_key) > 1
        
        if is_multi_key:
            num_keys = len(api_key)
            
            # Ước tính RPM dựa trên model để hiển thị log cho người dùng
            if "pro" in model_name.lower():
                base_rpm = 2
            else:
                base_rpm = 10 # Ước tính an toàn cho các model Flash
            
            # NEW: Nếu số keys > 5, TIN TƯỞNG vào user input, không điều chỉnh tự động
            if num_keys > 5:
                print(f"Google AI (Nhiều Keys - {num_keys} keys):")
                print(f"   Tổng RPM ước tính: ~{base_rpm * num_keys} RPM")
                print(f"   ✅ Sử dụng {num_workers} threads theo cài đặt của người dùng.")
                print(f"   💡 Với {num_keys} keys, bạn có thể tăng threads để tối ưu hiệu suất.")
                print(f"   📌 Khuyến nghị: {num_keys * 2}-{num_keys * 3} threads cho hiệu suất tốt nhất.")
                # Không điều chỉnh num_workers, dùng input của user
            else:
                # Chỉ tự động điều chỉnh số threads khi có <= 5 keys (chế độ free)
                # để tránh chạm vào giới hạn rate limit quá nhanh.
                
                # Tính toán threads thông minh dựa trên số keys và cấu hình máy
                cpu_cores = cpu_count()
                
                # Base threads: 1-1.5 threads per key, nhưng cân nhắc CPU cores
                base_threads_per_key = 1.2  # Trung bình 1.2 threads/key
                threads_from_keys = int(num_keys * base_threads_per_key)
                
                # Threads từ CPU: I/O bound nên có thể dùng nhiều hơn cores
                threads_from_cpu = min(cpu_cores * 3, 50)  # Tối đa 50 threads
                
                # Lấy min của 2 giá trị để cân bằng
                max_threads_for_free_keys = min(threads_from_keys, threads_from_cpu)
                
                # Đảm bảo tối thiểu và tối đa hợp lý
                max_threads_for_free_keys = max(max_threads_for_free_keys, min(num_keys, 5))  # Tối thiểu 5 hoặc số keys
                max_threads_for_free_keys = min(max_threads_for_free_keys, 50)  # Tối đa 50 threads
                
                print(f"   Tính toán threads:")
                print(f"     • {num_keys} keys x {base_threads_per_key} = {threads_from_keys} threads")
                print(f"     • {cpu_cores} CPU cores x 3 = {threads_from_cpu} threads")
                print(f"     • Chọn min({threads_from_keys}, {threads_from_cpu}) = {max_threads_for_free_keys} threads")
                
                if num_workers > max_threads_for_free_keys:
                    print(f"Google AI (Chế độ Free - {num_keys} keys):")
                    print(f"   Tổng RPM ước tính: ~{base_rpm * num_keys} RPM")
                    print(f"   Điều chỉnh Threads: {num_workers} -> {max_threads_for_free_keys} (tối ưu cho {num_keys} keys)")
                    print(f"   Tham khảo rate limits tại trang chủ Google AI.")
                    num_workers = max_threads_for_free_keys
                else:
                    print(f"Google AI (Chế độ Free - {num_keys} keys):")
                    print(f"   Tổng RPM ước tính: ~{base_rpm * num_keys} RPM")
                    print(f"   Sử dụng {num_workers} threads theo cài đặt.")
        else:
            # Với 1 key (chế độ trả phí hoặc 1 key free), tin tưởng vào setting của người dùng.
            # Key trả phí có RPM cao hơn nhiều.
            print(f"Google AI (Chế độ 1 Key - Paid/Free):")
            print(f"   Sử dụng {num_workers} threads theo cài đặt của người dùng.")
            print(f"   Lưu ý: Nếu dùng key trả phí, bạn có thể tăng số threads để dịch nhanh hơn.")
            print(f"   Nếu dùng key free, hãy cẩn thận với rate limit.")
        
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
    
    # Test từng key riêng biệt để xác định quota isolation
    if isinstance(api_key, list) and len(api_key) > 1:
        print(f"🧪 Testing quota isolation với {len(api_key)} keys...")
        for i, key in enumerate(api_key[:3], 1):  # Test 3 keys đầu
            is_valid, validation_message = validate_api_key_before_translation(key, model_name, provider)
            if is_valid:
                print(f"✅ Key #{i}: {validation_message}")
            else:
                print(f"❌ Key #{i}: {validation_message}")
    else:
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
        system_instruction = """NHIỆM VỤ: Dịch văn bản sang tiếng Việt hiện đại, tự nhiên.

QUY TẮC QUAN TRỌNG:
1. VĂN PHONG: Dịch như người Việt nói chuyện hàng ngày, tránh từ Hán Việt cứng nhắc
2. NGƯỜI KỂ CHUYỆN: Luôn xưng "tôi" (hiện đại) hoặc "ta" (cổ đại). TUYỆT ĐỐI KHÔNG dùng "ba/bố/anh/chị/em/con"
3. LỜI THOẠI: Đặt trong dấu ngoặc kép "...", xưng hô tự nhiên theo quan hệ nhân vật
4. TỪNG NGỮ HIỆN ĐẠI: "Cảm thấy" thay vì "cảm nhận", "Anh ấy/Cô ấy" thay vì "Hắn/Nàng"

⚠️ QUAN TRỌNG: CHỈ TRẢ VỀ BẢN DỊCH, KHÔNG GIẢI THÍCH GÌ THÊM!

Văn bản cần dịch:"""
    
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

        # Tạo adaptive thread manager để quản lý threads động
        adaptive_thread_manager = AdaptiveThreadManager(
            initial_threads=num_workers,
            min_threads=max(1, num_workers // 4),  # Tối thiểu 25% threads ban đầu
            max_threads=num_workers * 2  # Tối đa 2x threads ban đầu
        )
        
        # Mở file output để ghi kết quả
        mode = 'a' if completed_chunks > 0 else 'w'  # Append nếu có tiến độ cũ, write nếu bắt đầu mới
        with open(output_file, mode, encoding='utf-8') as outfile:
            
            # Loop chính với adaptive thread management
            current_workers = num_workers
            restart_needed = False
            translation_completed = False  # Flag để track completion
            
            while not translation_completed:
                print(f"🔧 Khởi động thread pool với {current_workers} workers...")
                
                # Dictionary để lưu trữ kết quả dịch theo thứ tự chunk index
                translated_chunks_results = {}
                next_expected_chunk_to_write = completed_chunks
                total_lines_processed = completed_chunks * chunk_size_lines

                with concurrent.futures.ThreadPoolExecutor(max_workers=current_workers) as executor:
                    
                    futures = {} # Lưu trữ các future: {future_object: chunk_index}
                    
                    # Gửi các chunks cần dịch đến thread pool
                    chunks_to_process = chunks[completed_chunks:]  # Chỉ xử lý chunks chưa hoàn thành
                    
                    # Context đã được truyền từ GUI
                    print(f"🎯 Sử dụng context: {context} ({'hiện đại - tôi' if context == 'modern' else 'cổ đại - ta'})")
                    
                    print(f"Gửi {len(chunks_to_process)} chunks đến thread pool...")
                    
                    for chunk_data in chunks_to_process:
                        # Kiểm tra flag dừng trước khi submit
                        if is_translation_stopped():
                            print("🛑 Dừng gửi chunks mới do người dùng yêu cầu")
                            break
                            
                        # Submit với key_rotator, context và adaptive_thread_manager
                        future = executor.submit(process_chunk, api_key, model_name, system_instruction, chunk_data, provider, None, key_rotator, context, is_paid_key, adaptive_thread_manager)
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
                                
                                # Nếu là lỗi quota thì dừng ngay
                                if 'HẾT QUOTA' in translated_text:
                                    set_quota_exceeded()
                                    break
                                # Các lỗi khác vẫn lưu vào buffer để ghi (với error message)
                            
                            # Lưu kết quả vào buffer tạm chờ ghi theo thứ tự (bao gồm cả lỗi)
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
                
                # Sau khi ThreadPoolExecutor hoàn thành, kiểm tra xem đã dịch hết chưa
                if next_expected_chunk_to_write >= total_chunks:
                    print(f"🎉 Đã hoàn thành tất cả {total_chunks} chunks!")
                    translation_completed = True
                    break  # Thoát vòng lặp while
                
                # Kiểm tra nếu bị dừng
                if is_translation_stopped():
                    print(f"⚠️ Phát hiện yêu cầu dừng, thoát vòng lặp...")
                    translation_completed = True  # Đánh dấu để thoát
                    break
            
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
                    print("⚠️ Chức năng reformat không khả dụ")
                
                # Kết thúc ThreadPoolExecutor - hoàn thành
                print(f"✅ Dịch hoàn thành!")
                return True  # Exit function successfully
            
        # Thoát khỏi adaptive loop khi hoàn thành
        return True

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