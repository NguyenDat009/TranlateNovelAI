#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Threading Safe Rate Limiter cho Google AI API
Giúp tránh vượt quá giới hạn RPM (Requests Per Minute) của Google AI
Hỗ trợ thực sự multi-threading với adaptive throttling
"""

import time
import threading
from collections import deque
from datetime import datetime, timedelta


class MultiThreadRateLimiter:
    """
    Multi-threading safe rate limiter sử dụng sliding window
    
    Google AI Free Tier Limits:
    - Gemini 2.0 Flash: 10 RPM, 1,500,000 TPM
    - Gemini 1.5 Flash: 15 RPM, 1,000,000 TPM  
    - Gemini 1.5 Pro: 2 RPM, 32,000 TPM
    
    Features:
    - Thread-safe operations
    - Adaptive throttling khi gặp rate limit errors
    - Non-blocking acquire cho multi-threading
    """
    
    def __init__(self, requests_per_minute=10, window_seconds=60):
        """
        Initialize rate limiter
        
        Args:
            requests_per_minute: Số requests tối đa mỗi phút
            window_seconds: Kích thước cửa sổ thời gian (mặc định 60s)
        """
        self.base_max_requests = requests_per_minute
        self.max_requests = requests_per_minute
        self.window_seconds = window_seconds
        self.requests = deque()
        self.lock = threading.Lock()
        
        # Adaptive throttling
        self.consecutive_errors = 0
        self.last_error_time = None
        self.throttle_factor = 1.0
        self.min_throttle = 0.3  # Tối thiểu 30% RPM gốc
        self.max_throttle = 1.0  # Tối đa 100% RPM gốc
        
    def acquire(self):
        """
        Multi-threading safe acquire permission to make a request
        Sử dụng distributed timing thay vì blocking sleep
        """
        max_attempts = 10
        attempt = 0
        
        while attempt < max_attempts:
            with self.lock:
                now = datetime.now()
                self._cleanup_old_requests(now)
                
                # Kiểm tra xem có slot available không
                if len(self.requests) < self.max_requests:
                    # Có slot, thêm request và return
                    self.requests.append(now)
                    
                    # Log progress occasionally
                    if len(self.requests) % 3 == 0:
                        thread_id = threading.current_thread().ident
                        throttle_info = f" (throttled {self.throttle_factor:.1%})" if self.throttle_factor < 1.0 else ""
                        print(f"📊 Thread {thread_id}: {len(self.requests)}/{self.max_requests} requests{throttle_info}")
                    
                    return  # Success!
                
                # Không có slot, tính wait time
                oldest_request = self.requests[0]
                wait_time = (oldest_request + timedelta(seconds=self.window_seconds) - now).total_seconds()
            
            # Sleep NGOÀI lock với distributed timing
            if wait_time > 0:
                # Distributed sleep: mỗi thread sleep khác nhau để tránh thundering herd
                thread_id = threading.current_thread().ident or 0
                jitter = (thread_id % 1000) / 1000.0  # 0-1 second jitter
                actual_sleep = min(wait_time / 2 + jitter, 2.0)  # Max 2s sleep
                
                if attempt == 0:  # Chỉ log lần đầu
                    print(f"🚦 Thread {thread_id}: Rate limit, đợi {actual_sleep:.1f}s...")
                
                time.sleep(actual_sleep)
            else:
                # Ngắn sleep để tránh busy waiting
                time.sleep(0.1)
            
            attempt += 1
        
        # Fallback: nếu không get được slot sau max_attempts
        print(f"⚠️ Thread {threading.current_thread().ident}: Fallback acquire after {max_attempts} attempts")
        with self.lock:
            self.requests.append(datetime.now())
    
    def _calculate_wait_time(self):
        """Tính wait time mà không block threads khác"""
        with self.lock:
            now = datetime.now()
            self._cleanup_old_requests(now)
            
            if len(self.requests) < self.max_requests:
                return 0
            
            # Tính thời gian chờ
            oldest_request = self.requests[0]
            wait_time = (oldest_request + timedelta(seconds=self.window_seconds) - now).total_seconds()
            return max(0, wait_time)
    
    def _cleanup_old_requests(self, now):
        """Xóa các requests cũ ngoài window"""
        cutoff_time = now - timedelta(seconds=self.window_seconds)
        while self.requests and self.requests[0] < cutoff_time:
            self.requests.popleft()
    
    def get_current_usage(self):
        """Get current number of requests in the window"""
        with self.lock:
            now = datetime.now()
            self._cleanup_old_requests(now)
            return len(self.requests)
    
    def get_wait_time(self):
        """Get time to wait before next request is allowed"""
        return self._calculate_wait_time()
    
    def on_rate_limit_error(self):
        """Gọi khi gặp rate limit error để adaptive throttling"""
        with self.lock:
            self.consecutive_errors += 1
            self.last_error_time = datetime.now()
            
            # Giảm throttle factor
            if self.consecutive_errors == 1:
                self.throttle_factor = 0.8  # Giảm 20%
            elif self.consecutive_errors == 2:
                self.throttle_factor = 0.6  # Giảm 40%
            elif self.consecutive_errors >= 3:
                self.throttle_factor = self.min_throttle  # Giảm xuống minimum
            
            # Cập nhật max_requests
            old_max = self.max_requests
            self.max_requests = max(1, int(self.base_max_requests * self.throttle_factor))
            
            print(f"🚨 Rate limit error #{self.consecutive_errors}!")
            print(f"   📉 Throttling: {old_max} → {self.max_requests} RPM ({self.throttle_factor:.1%})")
    
    def on_success(self):
        """Gọi khi request thành công để recovery throttling"""
        with self.lock:
            if self.consecutive_errors > 0:
                # Chỉ recovery sau 30s không có lỗi
                if self.last_error_time and (datetime.now() - self.last_error_time).total_seconds() > 30:
                    self.consecutive_errors = max(0, self.consecutive_errors - 1)
                    
                    # Tăng dần throttle factor
                    if self.consecutive_errors == 0:
                        self.throttle_factor = min(self.max_throttle, self.throttle_factor + 0.1)
                    
                    # Cập nhật max_requests
                    old_max = self.max_requests
                    self.max_requests = max(1, int(self.base_max_requests * self.throttle_factor))
                    
                    if old_max != self.max_requests:
                        print(f"📈 Recovery throttling: {old_max} → {self.max_requests} RPM ({self.throttle_factor:.1%})")
    
    def get_stats(self):
        """Get rate limiter statistics"""
        with self.lock:
            return {
                'current_usage': len(self.requests),
                'max_requests': self.max_requests,
                'base_max_requests': self.base_max_requests,
                'throttle_factor': self.throttle_factor,
                'consecutive_errors': self.consecutive_errors,
                'utilization': len(self.requests) / self.max_requests if self.max_requests > 0 else 0
            }


# Backward compatibility alias
RateLimiter = MultiThreadRateLimiter


# Rate limiters cho các models Google AI khác nhau
# Format: {(model_name, api_key_hash): RateLimiter}
_rate_limiters = {}
_lock = threading.Lock()


def _get_key_hash(api_key: str) -> str:
    """Get a hash of API key for use as dictionary key"""
    import hashlib
    return hashlib.md5(api_key.encode()).hexdigest()[:8]


def get_rate_limiter(model_name: str, provider: str = "Google AI", api_key: str = None) -> MultiThreadRateLimiter:
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
            
            _rate_limiters[limiter_key] = MultiThreadRateLimiter(requests_per_minute=safe_rpm)
        
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

