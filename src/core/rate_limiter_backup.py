#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BACKUP - Rate Limiter cho Google AI API (Original Version)
Giúp tránh vượt quá giới hạn RPM (Requests Per Minute) của Google AI
"""

import time
import threading
from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """
    Rate limiter đơn giản sử dụng sliding window
    
    Google AI Free Tier Limits:
    - Gemini 2.0 Flash: 10 RPM, 1,500,000 TPM
    - Gemini 1.5 Flash: 15 RPM, 1,000,000 TPM  
    - Gemini 1.5 Pro: 2 RPM, 32,000 TPM
    """
    
    def __init__(self, requests_per_minute=10, window_seconds=60):
        """
        Initialize rate limiter
        
        Args:
            requests_per_minute: Số requests tối đa mỗi phút
            window_seconds: Kích thước cửa sổ thời gian (mặc định 60s)
        """
        self.max_requests = requests_per_minute
        self.window_seconds = window_seconds
        self.requests = deque()
        self.lock = threading.Lock()
        
    def acquire(self):
        """
        Acquire permission to make a request
        Blocks if rate limit would be exceeded
        """
        with self.lock:
            now = datetime.now()
            
            # Xóa các requests cũ ngoài window
            cutoff_time = now - timedelta(seconds=self.window_seconds)
            while self.requests and self.requests[0] < cutoff_time:
                self.requests.popleft()
            
            # Kiểm tra xem có vượt quá limit không
            if len(self.requests) >= self.max_requests:
                # Tính thời gian cần chờ
                oldest_request = self.requests[0]
                wait_time = (oldest_request + timedelta(seconds=self.window_seconds) - now).total_seconds()
                
                if wait_time > 0:
                    print(f"🚦 Rate limit: {len(self.requests)}/{self.max_requests} requests. Đợi {wait_time:.1f}s...")
                    time.sleep(wait_time + 0.1)  # Thêm 0.1s buffer
                    
                    # Xóa lại các requests cũ sau khi đợi
                    now = datetime.now()
                    cutoff_time = now - timedelta(seconds=self.window_seconds)
                    while self.requests and self.requests[0] < cutoff_time:
                        self.requests.popleft()
            
            # Thêm request hiện tại
            self.requests.append(now)
            current_count = len(self.requests)
            if current_count % 5 == 0:  # Log mỗi 5 requests
                print(f"📊 Rate limiter: {current_count}/{self.max_requests} requests trong 60s")
    
    def get_current_usage(self):
        """Get current number of requests in the window"""
        with self.lock:
            now = datetime.now()
            cutoff_time = now - timedelta(seconds=self.window_seconds)
            
            # Xóa các requests cũ
            while self.requests and self.requests[0] < cutoff_time:
                self.requests.popleft()
            
            return len(self.requests)
    
    def get_wait_time(self):
        """Get time to wait before next request is allowed"""
        with self.lock:
            now = datetime.now()
            cutoff_time = now - timedelta(seconds=self.window_seconds)
            
            # Xóa các requests cũ
            while self.requests and self.requests[0] < cutoff_time:
                self.requests.popleft()
            
            if len(self.requests) < self.max_requests:
                return 0
            
            # Tính thời gian chờ
            oldest_request = self.requests[0]
            wait_time = (oldest_request + timedelta(seconds=self.window_seconds) - now).total_seconds()
            return max(0, wait_time)


# Rate limiters cho các models Google AI khác nhau
# Format: {(model_name, api_key_hash): RateLimiter}
_rate_limiters = {}
_lock = threading.Lock()


def _get_key_hash(api_key: str) -> str:
    """Get a hash of API key for use as dictionary key"""
    import hashlib
    return hashlib.md5(api_key.encode()).hexdigest()[:8]


def get_rate_limiter(model_name: str, provider: str = "Google AI", api_key: str = None) -> RateLimiter:
    """
    Get hoặc tạo rate limiter cho model (và key cụ thể nếu có)
    
    Args:
        model_name: Tên model
        provider: Provider (chỉ áp dụng cho Google AI)
        api_key: API key (dùng để tạo rate limiter riêng cho mỗi key)
        
    Returns:
        RateLimiter instance hoặc None nếu không cần rate limiting
    """
    # Chỉ rate limit cho Google AI
    if provider != "Google AI":
        return None
    
    with _lock:
        # Tạo unique key cho rate limiter
        if api_key:
            # Mỗi API key có rate limiter riêng
            key_hash = _get_key_hash(api_key)
            limiter_key = f"{model_name}_{key_hash}"
        else:
            # Backward compatibility: dùng model_name làm key
            limiter_key = model_name
        
        if limiter_key not in _rate_limiters:
            # Xác định RPM dựa trên model
            # Free tier limits from: https://ai.google.dev/gemini-api/docs/rate-limits?hl=vi
            rpm = 10  # Default safe value
            
            if "2.0-flash" in model_name.lower() or "2.0flash" in model_name.lower() or "2.0_flash" in model_name.lower():
                rpm = 10
            elif "1.5-flash" in model_name.lower() or "1.5flash" in model_name.lower() or "1.5_flash" in model_name.lower():
                rpm = 15
            elif "1.5-pro" in model_name.lower() or "1.5_pro" in model_name.lower():
                rpm = 2  # Very low!
            elif "pro" in model_name.lower():
                rpm = 2  # Conservative for Pro models
            else:
                rpm = 10  # Default safe value
            
            # Giảm RPM xuống 80% để an toàn hơn
            safe_rpm = int(rpm * 0.8)
            if safe_rpm < 1:
                safe_rpm = 1
            
            key_display = f"key_***{key_hash}" if api_key else "default"
            print(f"🔧 Đã tạo rate limiter cho model: {model_name} ({key_display})")
            print(f"   📊 Giới hạn gốc: {rpm} RPM")
            print(f"   🛡️ Giới hạn an toàn: {safe_rpm} RPM (80% của gốc)")
            print(f"   🌐 Tham khảo: https://ai.google.dev/gemini-api/docs/rate-limits")
            
            _rate_limiters[limiter_key] = RateLimiter(requests_per_minute=safe_rpm)
        
        return _rate_limiters[limiter_key]


def clear_rate_limiters():
    """Clear all rate limiters (for testing or reset)"""
    global _rate_limiters
    with _lock:
        _rate_limiters.clear()


# Exponential backoff cho retry khi gặp rate limit errors
def exponential_backoff_sleep(retry_count: int, base_delay: float = 1.0, max_delay: float = 60.0):
    """
    Sleep với exponential backoff
    
    Args:
        retry_count: Số lần retry hiện tại (0-indexed)
        base_delay: Delay cơ bản (giây)
        max_delay: Delay tối đa (giây)
    """
    delay = min(base_delay * (2 ** retry_count), max_delay)
    print(f"⏱️ Exponential backoff: đợi {delay:.1f}s (retry #{retry_count + 1})")
    time.sleep(delay)


def is_rate_limit_error(error_message: str) -> bool:
    """
    Kiểm tra xem lỗi có phải là rate limit error không
    
    Args:
        error_message: Thông báo lỗi
        
    Returns:
        True nếu là rate limit error
    """
    error_lower = str(error_message).lower()
    rate_limit_keywords = [
        "rate limit",
        "quota exceeded",
        "429",
        "too many requests",
        "resource exhausted",
        "requests per minute",
        "rpm",
        "rate_limit_exceeded",
        "quota_exceeded",
        "too_many_requests",
        # Google AI specific errors
        "resource has been exhausted",
        "quota_exhausted",
        "rate_limit_error",
        # HTTP status codes
        "status: 429",
        "status code: 429",
        "http 429"
    ]
    
    is_rate_limit = any(keyword in error_lower for keyword in rate_limit_keywords)
    
    if is_rate_limit:
        print(f"🚨 Detected rate limit error: {error_message[:100]}...")
    
    return is_rate_limit

