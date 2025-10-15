"""
TranslateNovelAI - OpenRouter Version
Sử dụng OpenRouter API để dịch văn bản với nhiều AI models khác nhau.

Cách sử dụng:
1. Đăng ký tài khoản tại https://openrouter.ai
2. Lấy API key từ dashboard
3. Chạy script và nhập API key hoặc set environment variable OPENROUTER_API_KEY
4. Chọn model phù hợp với nhu cầu và ngân sách

Models khuyến nghị:
- anthropic/claude-3.5-sonnet: Cân bằng tốc độ/chất lượng
- anthropic/claude-3-haiku: Nhanh và rẻ
- google/gemini-2.0-flash-exp:free: Miễn phí (có giới hạn)
"""

import os
import requests
import time
import json
import re
import concurrent.futures
import threading
from multiprocessing import cpu_count

# Import reformat function
try:
    from .reformat import fix_text_format
    CAN_REFORMAT = True
    print("✅ Đã import thành công chức năng reformat")
except ImportError:
    CAN_REFORMAT = False
    print("⚠️ Không thể import reformat.py - chức năng reformat sẽ bị tắt")

# --- CẤU HÌNH CÁC HẰNG SỐ ---
MAX_RETRIES_ON_SAFETY_BLOCK = 5
MAX_RETRIES_ON_BAD_TRANSLATION = 5
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

# OpenRouter API configuration
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.0-flash-001"

# Global stop event để dừng tiến trình dịch
_stop_event = threading.Event()

# Global quota exceeded flag
_quota_exceeded = threading.Event()

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
    """Kiểm tra lỗi Quota/Credit Insufficient (402) - cần nạp credit - KHÔNG BAO GỒM rate limit"""
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
    # KHÔNG BAO GỒM "429" và "rate limit" - đó là lỗi tạm thời, có thể retry!
    return any(keyword in error_str for keyword in quota_keywords)

def get_optimal_threads(provider="OpenRouter", model_name=""):
    """
    Tự động tính toán số threads tối ưu dựa trên cấu hình máy và model cụ thể.
    """
    try:
        # Lấy số CPU cores
        cpu_cores = cpu_count()
        
        # Kiểm tra model cụ thể có rate limit chặt không
        is_gemini_free = "google/gemini-2.0-flash-exp:free" in model_name.lower()
        
        # Tính toán threads tối ưu dựa trên model cụ thể:
        if is_gemini_free:
            # Chỉ Gemini free model có rate limit cực chặt - giảm threads mạnh
            optimal_threads = min(max(cpu_cores // 2, 2), 6)
            print(f"🖥️ Phát hiện {cpu_cores} CPU cores")
            print(f"🔧 Gemini Free Model - Threads đã giảm để tránh rate limit: {optimal_threads}")
        elif provider == "OpenRouter":
            # Các OpenRouter models khác - giữ nguyên logic cũ
            optimal_threads = min(max(cpu_cores * 2, 4), 20)
            print(f"🖥️ Phát hiện {cpu_cores} CPU cores")
            print(f"🔧 OpenRouter - Threads tối ưu: {optimal_threads}")
        else:
            # Google AI hoặc provider khác - giữ nguyên logic cũ
            optimal_threads = min(max(cpu_cores * 2, 4), 20)
            print(f"🖥️ Phát hiện {cpu_cores} CPU cores")
            print(f"🔧 Threads tối ưu được đề xuất: {optimal_threads}")
        
        return optimal_threads
        
    except Exception as e:
        print(f"⚠️ Lỗi khi phát hiện CPU cores: {e}")
        return 10  # Default trở lại 10 như cũ

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

def translate_chunk(api_key, model_name, system_instruction, chunk_lines, context="modern"):
    """
    Dịch một chunk gồm nhiều dòng văn bản sử dụng OpenRouter API.
    chunk_lines: danh sách các dòng văn bản
    context: "modern" (hiện đại) hoặc "ancient" (cổ đại)
    Trả về (translated_text, is_safety_blocked_flag, is_bad_translation_flag).
    """
    # Gom các dòng thành một chuỗi lớn để gửi đi
    full_text_to_translate = "\n".join(chunk_lines)
    
    # Bỏ qua các chunk chỉ chứa các dòng trống hoặc chỉ trắng
    if not full_text_to_translate.strip():
        return ("", False, False) # Trả về chuỗi rỗng, không bị chặn, không bad translation

    try:
        # Tạo prompt khác nhau cho từng bối cảnh
        if context == "ancient":
            # Prompt cho bối cảnh cổ đại
            user_prompt = f"""Dịch đoạn văn bản sau sang tiếng Việt theo phong cách CỔ ĐẠI:

QUY TẮC DANH XƯNG CỔ ĐẠI:
- NGƯỜI KỂ CHUYỆN (narrator) LUÔN xưng "ta" - KHÔNG BAO GIỜ dùng "tôi", "thần", "hạ thần"
- KHÔNG dịch người kể chuyện thành "ba", "bố", "con", "anh", "chị"
- Lời thoại nhân vật trong "..." có thể dùng: ta/ngươi, hạ thần/thần tử, công tử/tiểu thư

PHONG CÁCH CỔ ĐẠI:
- Ngôn ngữ trang trọng, lịch thiệp
- Thuật ngữ võ thuật: công pháp, tâm pháp, tu vi, cảnh giới
- Chức vị: hoàng thượng, hoàng hậu, thái tử, đại thần
- Từ Hán Việt khi phù hợp

QUAN TRỌNG - OUTPUT:
- CHỈ trả về nội dung đã dịch
- KHÔNG thêm giải thích, phân tích, bình luận
- KHÔNG thêm "Bản dịch:", "Kết quả:", hay bất kỳ tiêu đề nào
- KHÔNG thêm ghi chú hay chú thích

VĂN BẢN CẦN DỊCH:
{full_text_to_translate}"""
        else:
            # Prompt cho bối cảnh hiện đại
            user_prompt = f"""Dịch đoạn văn bản sau sang tiếng Việt theo phong cách HIỆN ĐẠI:

QUY TẮC DANH XƯNG HIỆN ĐẠI:
- NGƯỜI KỂ CHUYỆN (narrator) LUÔN xưng "tôi" - KHÔNG BAO GIỜ dùng "ta", "ba", "bố", "con"
- KHÔNG dịch người kể chuyện thành danh xưng quan hệ
- Lời thoại nhân vật trong "..." có thể dùng: anh/chị, em, bạn, ba/mẹ, con

PHONG CÁCH HIỆN ĐẠI:
- Ngôn ngữ tự nhiên, gần gũi
- Thuật ngữ công nghệ, đời sống đô thị
- Giữ từ ngữ thô tục, slang nếu có
- Không quá trang trọng

QUAN TRỌNG - OUTPUT:
- CHỈ trả về nội dung đã dịch
- KHÔNG thêm giải thích, phân tích, bình luận
- KHÔNG thêm "Bản dịch:", "Kết quả:", hay bất kỳ tiêu đề nào
- KHÔNG thêm ghi chú hay chú thích

VĂN BẢN CẦN DỊCH:
{full_text_to_translate}"""

        # Chuẩn bị messages cho OpenRouter API
        messages = []
        if system_instruction:
            messages.append({
                "role": "system",
                "content": system_instruction
            })
        messages.append({
            "role": "user",
            "content": user_prompt
        })

        # Chuẩn bị headers
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/TranslateNovelAI",  # Tùy chọn
            "X-Title": "TranslateNovelAI"  # Tùy chọn
        }

        # Chuẩn bị payload
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 8000,  # Tăng max_tokens để tránh bị cắt nội dung
            "top_p": 1,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "stream": False  # Đảm bảo không dùng streaming để tránh mất data
        }

        # Gửi request đến OpenRouter với timeout dài hơn và retry logic
        max_retries = 3
        retry_delay = 2
        
        # Tính toán kích thước input để điều chỉnh timeout
        input_size = len(full_text_to_translate)
        base_timeout = 120  # 2 phút cơ bản
        # Thêm thời gian cho input lớn (1 giây mỗi 1000 ký tự)
        dynamic_timeout = base_timeout + (input_size // 1000) * 1
        dynamic_timeout = min(dynamic_timeout, 300)  # Tối đa 5 phút
        
        print(f"🔄 Đang dịch chunk ({input_size} ký tự) với timeout {dynamic_timeout}s...")
        
        for attempt in range(max_retries):
            try:
                # Thêm delay nhỏ trước request để tránh rate limit (đặc biệt cho Gemini free)
                if "google/gemini-2.0-flash-exp:free" in model_name.lower():
                    # Chỉ Gemini free model: delay lâu hơn để tránh rate limit
                    time.sleep(0.5)  # 500ms delay cho Gemini free model
                else:
                    # Các models khác: delay ngắn hơn
                    time.sleep(0.1)  # 100ms delay cho các models khác
                
                response = requests.post(
                    OPENROUTER_BASE_URL,
                    headers=headers,
                    json=payload,
                    timeout=dynamic_timeout,  # Timeout động dựa trên kích thước
                    stream=False  # Đảm bảo không streaming
                )
                print(f"✅ Request thành công sau {attempt + 1} lần thử")
                break  # Thành công thì thoát loop
            except requests.exceptions.Timeout:
                if attempt == max_retries - 1:
                    return (f"[LỖI TIMEOUT SAU {max_retries} LẦN THỬ - TIMEOUT: {dynamic_timeout}s]", False, True)
                print(f"⚠️ Timeout lần {attempt + 1}/{max_retries} (timeout: {dynamic_timeout}s), thử lại sau {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                dynamic_timeout = min(dynamic_timeout * 1.5, 300)  # Tăng timeout cho lần thử tiếp theo
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    return (f"[LỖI REQUEST SAU {max_retries} LẦN THỬ: {e}]", False, True)
                print(f"⚠️ Lỗi request lần {attempt + 1}/{max_retries}: {e}, thử lại sau {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2

        # Kiểm tra status code chi tiết theo OpenRouter API specs
        if response.status_code == 400:
            return (f"[LỖI BAD REQUEST (400): {response.text}]", False, True)
        elif response.status_code == 401:
            return (f"[LỖI API KEY KHÔNG HỢP LỆ (401): {response.text}]", False, True) 
        elif response.status_code == 402:
            # 402 = Insufficient Credits - dừng hoàn toàn
            set_quota_exceeded()
            return (f"[API HẾT CREDIT (402): {response.text}]", False, True)
        elif response.status_code == 403:
            return (f"[LỖI MODERATION (403): {response.text}]", True, False)
        elif response.status_code == 408:
            return (f"[LỖI TIMEOUT (408): {response.text}]", False, True)
        elif response.status_code == 429:
            # 429 = Rate Limit - có thể retry, KHÔNG phải quota exceeded
            return (f"[LỖI RATE LIMIT (429): {response.text}]", False, True)
        elif response.status_code == 502:
            return (f"[LỖI BAD GATEWAY (502): {response.text}]", False, True)
        elif response.status_code == 503:
            return (f"[LỖI SERVICE UNAVAILABLE (503): {response.text}]", False, True)
        elif response.status_code != 200:
            return (f"[LỖI API HTTP {response.status_code}: {response.text}]", False, True)

        # Parse response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            return (f"[LỖI PARSE JSON: {response.text}]", False, True)

        # Kiểm tra lỗi trong response JSON
        if 'error' in response_data:
            error_msg = response_data['error'].get('message', 'Unknown error')
            error_code = response_data['error'].get('code', '')
            
            # Phân loại lỗi trong response message
            if 'insufficient credits' in error_msg.lower() or 'quota exceeded' in error_msg.lower():
                # Quota/Credit error - dừng hoàn toàn
                set_quota_exceeded()
                return (f"[API HẾT QUOTA: {error_msg}]", False, True)
            elif 'rate limit' in error_msg.lower() or 'too many requests' in error_msg.lower():
                # Rate limit - có thể retry
                return (f"[RATE LIMIT: {error_msg}]", False, True)
            elif 'unauthorized' in error_msg.lower() or 'invalid' in error_msg.lower():
                # API key error 
                return (f"[API KEY ERROR: {error_msg}]", False, True)
            elif 'moderation' in error_msg.lower() or 'policy' in error_msg.lower():
                # Content moderation
                return (f"[MODERATION ERROR: {error_msg}]", True, False)
            else:
                # Generic error
                return (f"[LỖI API: {error_msg}]", False, True)

        # Lấy nội dung dịch
        if 'choices' not in response_data or not response_data['choices']:
            return ("[KHÔNG CÓ KẾT QUẢ DỊCH]", True, False)

        choice = response_data['choices'][0]
        if 'message' not in choice or 'content' not in choice['message']:
            return ("[RESPONSE KHÔNG CÓ CONTENT]", True, False)
            
        translated_text = choice['message']['content']
        
        # Kiểm tra xem response có bị cắt không (finish_reason != "stop")
        finish_reason = choice.get('finish_reason', 'unknown')
        if finish_reason == 'length':
            print(f"⚠️ Cảnh báo: Response bị cắt do vượt quá max_tokens. Finish reason: {finish_reason}")
            # Vẫn trả về kết quả nhưng đánh dấu là bad translation để retry với chunk nhỏ hơn
            return (translated_text + " [BỊ CẮT - CẦN CHUNK NHỎ HƠN]", False, True)
        elif finish_reason not in ['stop', 'end_turn']:
            print(f"⚠️ Cảnh báo: Response kết thúc bất thường. Finish reason: {finish_reason}")
        
        # Kiểm tra độ dài và chất lượng response được xử lý trong is_bad_translation
        
        # Kiểm tra chất lượng bản dịch với input text để so sánh kích thước
        is_bad = is_bad_translation(translated_text, full_text_to_translate)
        return (translated_text, False, is_bad)

    except requests.exceptions.Timeout:
        return ("[LỖI TIMEOUT KHI GỬI REQUEST]", False, True)
    except requests.exceptions.RequestException as e:
        return (f"[LỖI REQUEST: {e}]", False, True)
    except Exception as e:
        # Bắt các lỗi khác (connection errors, etc.)
        error_message = str(e)
        
        # Kiểm tra lỗi quota exceeded (chỉ true quota, không phải rate limit)
        if check_quota_error(error_message):
            set_quota_exceeded()
            return (f"[API HẾT QUOTA: {error_message}]", False, True)
        
        # Các lỗi khác (network, timeout, etc.)
        return (f"[LỖI EXCEPTION KHI DỊCH CHUNK: {e}]", False, True)

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

def process_chunk(api_key, model_name, system_instruction, chunk_data, log_callback=None):
    """
    Xử lý dịch một chunk với retry logic và adaptive chunk size.
    chunk_data: tuple (chunk_index, chunk_lines, chunk_start_line_index)
    Trả về: (chunk_index, translated_text, lines_count)
    """
    chunk_index, chunk_lines, chunk_start_line_index = chunk_data
    
    # Kiểm tra flag dừng và quota exceeded trước khi bắt đầu
    if is_translation_stopped() or is_quota_exceeded():
        if is_quota_exceeded():
            return (chunk_index, f"[CHUNK {chunk_index} - API HẾT QUOTA]", len(chunk_lines))
        else:
            return (chunk_index, f"[CHUNK {chunk_index} BỊ DỪNG BỞI NGƯỜI DÙNG]", len(chunk_lines))
    
    # Adaptive chunk processing với retry logic mạnh mẽ
    def process_chunk_adaptive(lines_to_process, retry_count=0):
        """
        Xử lý chunk với retry logic và adaptive sizing.
        
        Args:
            lines_to_process: Danh sách các dòng cần dịch
            retry_count: Số lần đã retry (để tránh infinite recursion)
            
        Returns:
            (translated_text, is_safety_blocked, is_bad)
        """
        max_retries_for_incomplete = 3  # Tối đa 3 lần retry cho response không hoàn chỉnh
        
        translated_text, is_safety_blocked, is_bad = translate_chunk(api_key, model_name, system_instruction, lines_to_process, "modern")
        
        # Nếu có lỗi safety hoặc quota, return ngay
        if is_safety_blocked or is_quota_exceeded():
            return translated_text, is_safety_blocked, is_bad
        
        # Nếu response không hoàn chỉnh và chưa vượt quá số lần retry
        if is_bad and retry_count < max_retries_for_incomplete:
            # Kiểm tra nguyên nhân bad translation
            input_text = "\n".join(lines_to_process)
            
            # Log chi tiết lý do retry
            if translated_text:
                last_char = translated_text.strip()[-1] if translated_text.strip() else ''
                input_len = len(input_text)
                output_len = len(translated_text)
                ratio = output_len / input_len if input_len > 0 else 0
                
                print(f"🔄 Chunk {chunk_index} - Retry lần {retry_count + 1}/{max_retries_for_incomplete}")
                print(f"   Lý do: Kết thúc='{last_char}', Tỷ lệ={ratio:.1%} ({output_len}/{input_len} chars)")
            
            # Retry với cùng chunk
            return process_chunk_adaptive(lines_to_process, retry_count + 1)
        
        # Nếu vẫn bad sau max retries, thử chia nhỏ chunk (nếu có thể)
        if is_bad and len(lines_to_process) > 10:
            print(f"🔄 Chunk {chunk_index} vẫn không hoàn chỉnh sau {max_retries_for_incomplete} lần thử, chia nhỏ chunk...")
            
            # Chia chunk thành 2 phần
            mid_point = len(lines_to_process) // 2
            first_half = lines_to_process[:mid_point]
            second_half = lines_to_process[mid_point:]
            
            # Dịch từng phần (mỗi phần cũng có retry riêng)
            first_result, first_safety, first_bad = process_chunk_adaptive(first_half, 0)
            if first_safety:
                # Nếu có lỗi safety, vẫn lưu kết quả gốc thay vì báo lỗi
                print(f"💾 Chunk {chunk_index} - Lưu kết quả gốc do lỗi safety khi chia nhỏ")
                return translated_text + " [LƯU KẾT QUẢ DO LỖI SAFETY]", False, False
                
            second_result, second_safety, second_bad = process_chunk_adaptive(second_half, 0)
            if second_safety:
                # Kết hợp phần đầu và lưu kết quả
                print(f"💾 Chunk {chunk_index} - Lưu phần đầu do lỗi safety ở phần 2")
                return first_result + "\n[PHẦN 2 BỊ LỖI SAFETY - ĐÃ LƯU PHẦN 1]", False, False
                
            # Kết hợp 2 phần
            combined_result = first_result + "\n" + second_result
            
            # Kiểm tra chất lượng kết quả kết hợp
            combined_is_bad = is_bad_translation(combined_result, "\n".join(lines_to_process))
            
            if not combined_is_bad:
                print(f"✅ Chunk {chunk_index} đã được chia nhỏ và dịch thành công")
                return combined_result, False, False
            else:
                print(f"💾 Chunk {chunk_index} - Lưu kết quả kết hợp dù chưa hoàn chỉnh")
                return combined_result + " [ĐÃ LƯU SAU KHI CHIA NHỎ]", False, False  # Lưu dù chưa hoàn chỉnh
        
        # Nếu đã hết cách, lưu kết quả cuối cùng thay vì báo lỗi
        if is_bad and retry_count >= max_retries_for_incomplete:
            print(f"💾 Chunk {chunk_index} - Đã thử {max_retries_for_incomplete} lần, lưu kết quả hiện tại và tiếp tục")
            return translated_text + f" [ĐÃ LƯU SAU {max_retries_for_incomplete} LẦN THỬ]", False, False  # Lưu kết quả và tiếp tục
            
        return translated_text, is_safety_blocked, is_bad
    
    # OpenRouter API không cần cấu hình model riêng cho thread
    # Các parameters sẽ được truyền trực tiếp vào translate_chunk
    
    # Thử lại với lỗi bảo mật
    safety_retries = 0
    is_safety_blocked = False  # Khởi tạo biến
    while safety_retries < MAX_RETRIES_ON_SAFETY_BLOCK:
        # Kiểm tra flag dừng và quota exceeded trong quá trình retry
        if is_translation_stopped() or is_quota_exceeded():
            if is_quota_exceeded():
                return (chunk_index, f"[CHUNK {chunk_index} - API HẾT QUOTA]", len(chunk_lines))
            else:
                return (chunk_index, f"[CHUNK {chunk_index} BỊ DỪNG BỞI NGƯỜI DÙNG]", len(chunk_lines))
            
        # Thử lại với bản dịch xấu  
        bad_translation_retries = 0
        while bad_translation_retries < MAX_RETRIES_ON_BAD_TRANSLATION:
            # Kiểm tra flag dừng và quota exceeded trong quá trình retry
            if is_translation_stopped() or is_quota_exceeded():
                if is_quota_exceeded():
                    return (chunk_index, f"[CHUNK {chunk_index} - API HẾT QUOTA]", len(chunk_lines))
                else:
                    return (chunk_index, f"[CHUNK {chunk_index} BỊ DỪNG BỞI NGƯỜI DÙNG]", len(chunk_lines))
                
            try:
                # Sử dụng adaptive processing thay vì translate_chunk trực tiếp
                translated_text, is_safety_blocked, is_bad = process_chunk_adaptive(chunk_lines)
                
                # Kiểm tra quota exceeded sau khi dịch
                if is_quota_exceeded():
                    return (chunk_index, f"[CHUNK {chunk_index} - API HẾT QUOTA]", len(chunk_lines))
                
                if is_safety_blocked:
                    break # Thoát khỏi vòng lặp bad translation, sẽ retry safety
                    
                if not is_bad:
                    return (chunk_index, translated_text, len(chunk_lines)) # Thành công
                    
                # Bản dịch xấu, thử lại
                bad_translation_retries += 1
                if bad_translation_retries < MAX_RETRIES_ON_BAD_TRANSLATION:
                    print(f"⚠️ Chunk {chunk_index} - bản dịch xấu lần {bad_translation_retries}, thử lại...")
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    # Hết lần thử bad translation, lưu bản dịch cuối cùng
                    print(f"💾 Chunk {chunk_index} - đã thử {MAX_RETRIES_ON_BAD_TRANSLATION} lần, lưu kết quả hiện tại")
                    return (chunk_index, translated_text + " [ĐÃ LƯU SAU KHI THỬ CẢI THIỆN]", len(chunk_lines))
                    
            except Exception as e:
                error_msg = str(e)
                
                # Kiểm tra quota error (chỉ true quota 402, không phải rate limit 429)
                if check_quota_error(error_msg):
                    set_quota_exceeded()
                    return (chunk_index, f"[CHUNK {chunk_index} - API HẾT QUOTA (402)]", len(chunk_lines))
                
                return (chunk_index, f"[LỖI XỬ LÝ CHUNK {chunk_index}: {e}]", len(chunk_lines))
        
        # Nếu bị chặn safety, thử lại
        if is_safety_blocked:
            safety_retries += 1
            if safety_retries < MAX_RETRIES_ON_SAFETY_BLOCK:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                # Hết lần thử safety, lưu kết quả cuối cùng
                print(f"💾 Chunk {chunk_index} - đã thử {MAX_RETRIES_ON_SAFETY_BLOCK} lần với safety block, lưu kết quả")
                return (chunk_index, translated_text + " [ĐÃ LƯU SAU KHI BỊ SAFETY BLOCK]", len(chunk_lines))
    
    # Fallback (không nên đến đây)
    return (chunk_index, f"[KHÔNG THỂ DỊCH CHUNK {chunk_index}]", len(chunk_lines))

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

def translate_file_optimized(input_file, output_file=None, api_key=None, model_name=None, system_instruction=None, num_workers=None, chunk_size_lines=None):
    """
    Phiên bản dịch file với multi-threading chunks.
    """
    # Clear stop flag khi bắt đầu dịch mới
    clear_stop_translation()
    
    # Validate và thiết lập parameters
    if num_workers is None:
        num_workers = NUM_WORKERS
    else:
        num_workers = validate_threads(num_workers)
        
    if chunk_size_lines is None:
        chunk_size_lines = CHUNK_SIZE_LINES
    else:
        chunk_size_lines = validate_chunk_size(chunk_size_lines)
        
    # Sử dụng model mặc định nếu không được cung cấp
    if model_name is None:
        model_name = DEFAULT_MODEL
    
    # Tự động tạo tên file output nếu không được cung cấp
    if output_file is None:
        output_file = generate_output_filename(input_file)
        print(f"📝 Tự động tạo tên file output: {output_file}")
    
    print(f"Bắt đầu dịch file: {input_file}")
    print(f"File output: {output_file}")
    print(f"Số worker threads: {num_workers}")
    print(f"Kích thước chunk: {chunk_size_lines} dòng")

    progress_file_path = f"{input_file}{PROGRESS_FILE_SUFFIX}"

    # Lấy tiến độ từ file - số chunk đã hoàn thành
    completed_chunks = get_progress(progress_file_path)
    print(f"Đã hoàn thành {completed_chunks} chunk trước đó.")

    # Thời gian bắt đầu để tính hiệu suất
    start_time = time.time()
    
    # System instruction cho AI - sử dụng custom hoặc default
    if system_instruction is None:
        system_instruction = "Bạn là một dịch giả chuyên nghiệp. Dịch văn bản sau sang tiếng Việt một cách tự nhiên và chính xác. Bối cảnh hiện đại. Đảm bảo các câu thoại nhân vật được dịch chính xác và đặt trong dấu ngoặc kép. Đảm bảo giữ nguyên chi tiết nội dung và văn phong gốc. Giữ nguyên các từ ngữ thô tục, tình dục nếu có."
    
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
                        
                    future = executor.submit(process_chunk, api_key, model_name, system_instruction, chunk_data)
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
                        result = future.result()  # (chunk_index, translated_text, lines_count)
                        processed_chunk_index, translated_text, lines_count = result
                        
                        # Lưu kết quả vào buffer tạm chờ ghi theo thứ tự
                        translated_chunks_results[processed_chunk_index] = (translated_text, lines_count)
                        
                        print(f"✅ Hoàn thành chunk {processed_chunk_index + 1}/{total_chunks}")
                        
                        # Ghi các chunks đã hoàn thành vào file output theo đúng thứ tự
                        while next_expected_chunk_to_write in translated_chunks_results:
                            chunk_text, chunk_lines_count = translated_chunks_results.pop(next_expected_chunk_to_write)
                            outfile.write(chunk_text)
                            if not chunk_text.endswith('\n'):
                                outfile.write('\n')
                            outfile.flush()
                            
                            # Cập nhật tiến độ
                            next_expected_chunk_to_write += 1
                            total_lines_processed += chunk_lines_count
                            
                            # Lưu tiến độ sau mỗi chunk hoàn thành
                            save_progress(progress_file_path, next_expected_chunk_to_write)
                            
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
                    for chunk_idx, (chunk_text, chunk_lines_count) in sorted_remaining_chunks:
                        try:
                            outfile.write(chunk_text)
                            if not chunk_text.endswith('\n'):
                                outfile.write('\n')
                            outfile.flush()
                            next_expected_chunk_to_write += 1
                            save_progress(progress_file_path, next_expected_chunk_to_write)
                            print(f"✅ Ghi chunk bị sót: {chunk_idx + 1}")
                        except Exception as e:
                            print(f"❌ Lỗi khi ghi chunk {chunk_idx}: {e}")

        # Kiểm tra xem có bị dừng giữa chừng không
        if is_translation_stopped():
            if is_quota_exceeded():
                print(f"API đã hết quota!")
                print(f"Để tiếp tục dịch, vui lòng:")
                print(f" 1. Đăng ký tài khoản OpenRouter tại https://openrouter.ai")
                print(f" 2. Nạp credit hoặc sử dụng models miễn phí") 
                print(f" 3. Tạo API key mới từ OpenRouter")
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
    # Thử load từ environment variable - ưu tiên OpenRouter trước
    import os
    api_key = os.getenv('OPENROUTER_API_KEY')
    if api_key:
        print(f"✅ Đã load OpenRouter API key từ environment variable")
        return api_key
    
    # Fallback: thử Google AI key (để tương thích ngược)
    api_key = os.getenv('GOOGLE_AI_API_KEY')
    if api_key:
        print(f"✅ Đã load API key từ environment variable (Google AI)")
        return api_key
    
    # Thử load từ file config.json
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Ưu tiên OpenRouter API key
                api_key = config.get('openrouter_api_key') or config.get('api_key')
                if api_key:
                    print(f"✅ Đã load API key từ config.json")
                    return api_key
    except:
        pass
    
    return None

def main():
    """Interactive main function for command line usage"""
    print("=== TranslateNovelAI - OpenRouter Version ===\n")
    
    # Thử tự động load API Key
    api_key = load_api_key()
    
    if not api_key:
        # Nhập API Key manually
        api_key = input("Nhập OpenRouter API Key: ").strip()
        if not api_key:
            print("❌ API Key không được để trống!")
            return
        
        # Hỏi có muốn lưu vào config.json không
        save_key = input("💾 Lưu API key vào config.json? (y/N): ").lower().strip()
        if save_key == 'y':
            try:
                config = {'openrouter_api_key': api_key}
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
    print("1. google/gemini-2.5-flash (nhanh, rẻ, đa ngôn ngữ)")
    print("2. google/gemini-2.5-pro (dịch chuyên sâu, chính xác)")
    print("3. anthropic/claude-4-sonnet-20250522 (dịch sáng tạo, văn phong tự nhiên)")
    print("4. openai/gpt-4o-mini (dịch nhanh, chi phí thấp)")
    print("5. qwen/qwen-2.5-72b-instruct (mạnh về tiếng Trung, đa ngôn ngữ)")
    print("6. mistral/mistral-large (ổn định, giá hợp lý)")
    print("7. google/gemini-2.0-flash-001 (Gemini 2.0 Flash) (khuyến nghị - cân bằng tốc độ/chất lượng)")
    print("8. Nhập model tùy chỉnh")
    
    model_choice = input("Nhập lựa chọn (1-8, mặc định 7): ").strip()

    model_map = {
        "1": "google/gemini-2.5-flash",
        "2": "google/gemini-2.5-pro",
        "3": "anthropic/claude-4-sonnet-20250522",
        "4": "openai/gpt-4o-mini",
        "5": "qwen/qwen-2.5-72b-instruct",
        "6": "mistral/mistral-large",
        "7": "google/gemini-2.0-flash-001",
        "": "google/gemini-2.0-flash-001"  # Default
    }

    if model_choice == "8":
        # Custom model input
        print("\n📝 Nhập model tùy chỉnh:")
        print("Ví dụ: anthropic/claude-3.5-sonnet, openai/gpt-4, google/gemini-pro, v.v.")
        custom_model = input("Model: ").strip()
        if not custom_model:
            print("❌ Model không được để trống!")
            return
        # Validate model format (provider/model-name)
        if '/' not in custom_model:
            print("⚠️ Cảnh báo: Model nên có format 'provider/model-name' (ví dụ: anthropic/claude-3.5-sonnet)")
            confirm = input("Bạn có muốn tiếp tục với model này không? (y/N): ").lower().strip()
            if confirm != 'y':
                return
        model_name = custom_model
    else:
        model_name = model_map.get(model_choice, "google/gemini-2.0-flash-001")
    
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