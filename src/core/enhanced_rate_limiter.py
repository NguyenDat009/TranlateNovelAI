#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Rate Limiter với TPM (Tokens Per Minute) và RPD (Requests Per Day) tracking
Thêm các tính năng mới để tối ưu cho multi-key và multi-thread
"""

import time
import threading
from collections import deque
from datetime import datetime, timedelta
import hashlib


class EnhancedRateLimiter:
    """
    Enhanced rate limiter với RPM, TPM, và RPD tracking
    """
    
    def __init__(self, requests_per_minute=10, tokens_per_minute=None, 
                 requests_per_day=None, window_seconds=60):
        """
        Initialize enhanced rate limiter
        
        Args:
            requests_per_minute: Số requests tối đa mỗi phút
            tokens_per_minute: Số tokens tối đa mỗi phút (optional)
            requests_per_day: Số requests tối đa mỗi ngày (optional)
            window_seconds: Kích thước cửa sổ thời gian (mặc định 60s)
        """
        # RPM tracking (existing)
        self.base_max_requests = requests_per_minute
        self.max_requests = requests_per_minute
        self.window_seconds = window_seconds
        self.requests = deque()
        self.lock = threading.Lock()
        
        # TPM tracking (NEW)
        self.max_tokens = tokens_per_minute
        self.tokens_used = deque()  # (timestamp, token_count)
        self.token_lock = threading.Lock()
        
        # RPD tracking (NEW)
        self.max_daily_requests = requests_per_day
        self.daily_requests = {}  # {date_str: count}
        self.daily_lock = threading.Lock()
        
        # Adaptive throttling
        self.consecutive_errors = 0
        self.last_error_time = None
        self.throttle_factor = 1.0
        self.min_throttle = 0.3
        self.max_throttle = 1.0
        
    def acquire(self, estimated_tokens=0):
        """
        Multi-threading safe acquire với RPM, TPM, và RPD checking
        
        Args:
            estimated_tokens: Số tokens ước tính cho request này
        """
        # Check RPD first (nếu vượt RPD, không cần check RPM/TPM)
        if not self._check_rpd():
            print("⚠️ Đã vượt giới hạn Requests Per Day (RPD)!")
            raise Exception("RPD limit exceeded")
        
        # Get thread ID for distributed jitter
        thread_id = threading.current_thread().ident or 0
        
        # Check RPM
        max_attempts = 20  # Tăng max attempts
        attempt = 0
        
        while attempt < max_attempts:
            with self.lock:
                now = datetime.now()
                self._cleanup_old_requests(now)
                
                # Kiểm tra RPM slot
                if len(self.requests) < self.max_requests:
                    # Check TPM nếu có
                    if self.max_tokens and estimated_tokens > 0:
                        if not self._check_tpm(estimated_tokens):
                            # TPM full, wait
                            pass
                        else:
                            # Both RPM and TPM OK
                            self.requests.append(now)
                            self._record_tpm(estimated_tokens)
                            self._increment_rpd()
                            return
                    else:
                        # Không có TPM limit, chỉ check RPM
                        self.requests.append(now)
                        self._increment_rpd()
                        return
                
                # Không có slot, tính wait time
                oldest_request = self.requests[0]
                wait_time = (oldest_request + timedelta(seconds=self.window_seconds) - now).total_seconds()
            
            # Sleep với DISTRIBUTED jitter để tránh thundering herd
            if wait_time > 0:
                # Jitter dựa trên thread_id để phân tán wake-up time
                # Sử dụng modulo nhỏ hơn để jitter không quá lớn
                base_jitter = (thread_id % 50) / 100.0  # 0.00-0.49s
                attempt_jitter = attempt * 0.05  # Tăng nhẹ theo attempt
                total_jitter = base_jitter + attempt_jitter
                
                # Thêm buffer nhỏ để đảm bảo slot đã freed
                actual_sleep = wait_time + total_jitter + 0.2
                
                # Cap tối đa 5s cho mỗi sleep (tránh wait quá lâu)
                actual_sleep = min(actual_sleep, 5.0)
                
                if attempt == 0:
                    print(f"🚦 Rate limit (RPM: {len(self.requests)}/{self.max_requests}), đợi {actual_sleep:.1f}s...")
                elif attempt % 5 == 0:
                    print(f"⏳ Vẫn chờ rate limit... attempt {attempt}/{max_attempts}")
                
                time.sleep(actual_sleep)
            else:
                # Ngay cả khi wait_time <= 0, vẫn sleep một chút với jitter
                small_jitter = (thread_id % 50) / 1000.0  # 0-50ms
                time.sleep(0.05 + small_jitter)
            
            attempt += 1
        
        # Fallback: FORCE acquire (có thể vượt limit một chút)
        print(f"⚠️ Fallback acquire after {max_attempts} attempts - FORCING slot")
        with self.lock:
            # Cleanup trước khi force
            now = datetime.now()
            self._cleanup_old_requests(now)
            
            # Nếu vẫn full, xóa request cũ nhất
            if len(self.requests) >= self.max_requests:
                print(f"🔴 WARNING: Force removing oldest request to make room")
                self.requests.popleft()
            
            self.requests.append(now)
            self._increment_rpd()
    
    def _check_tpm(self, estimated_tokens):
        """Check xem còn TPM quota không"""
        with self.token_lock:
            now = datetime.now()
            self._cleanup_old_tokens(now)
            
            current_tpm = sum(t[1] for t in self.tokens_used)
            return current_tpm + estimated_tokens <= self.max_tokens
    
    def _record_tpm(self, tokens):
        """Ghi nhận tokens đã sử dụng"""
        with self.token_lock:
            self.tokens_used.append((datetime.now(), tokens))
    
    def _cleanup_old_tokens(self, now):
        """Xóa token records ngoài window"""
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self.tokens_used and self.tokens_used[0][0] < cutoff:
            self.tokens_used.popleft()
    
    def _check_rpd(self):
        """Check xem còn RPD quota không"""
        if not self.max_daily_requests:
            return True
        
        with self.daily_lock:
            today = datetime.now().strftime("%Y-%m-%d")
            if today not in self.daily_requests:
                self.daily_requests = {today: 0}  # Reset
            
            return self.daily_requests[today] < self.max_daily_requests
    
    def _increment_rpd(self):
        """Tăng RPD counter"""
        if not self.max_daily_requests:
            return
        
        with self.daily_lock:
            today = datetime.now().strftime("%Y-%m-%d")
            self.daily_requests[today] = self.daily_requests.get(today, 0) + 1
    
    def get_rpd_remaining(self):
        """Lấy số requests còn lại hôm nay"""
        if not self.max_daily_requests:
            return float('inf')
        
        with self.daily_lock:
            today = datetime.now().strftime("%Y-%m-%d")
            used = self.daily_requests.get(today, 0)
            return max(0, self.max_daily_requests - used)
    
    def _cleanup_old_requests(self, now):
        """Xóa các requests cũ ngoài window"""
        cutoff_time = now - timedelta(seconds=self.window_seconds)
        while self.requests and self.requests[0] < cutoff_time:
            self.requests.popleft()
    
    def get_stats(self):
        """Get comprehensive statistics"""
        with self.lock:
            rpm_usage = len(self.requests)
        
        with self.token_lock:
            now = datetime.now()
            self._cleanup_old_tokens(now)
            tpm_usage = sum(t[1] for t in self.tokens_used)
        
        with self.daily_lock:
            today = datetime.now().strftime("%Y-%m-%d")
            rpd_usage = self.daily_requests.get(today, 0)
        
        return {
            'rpm_usage': rpm_usage,
            'rpm_max': self.max_requests,
            'rpm_utilization': rpm_usage / self.max_requests if self.max_requests > 0 else 0,
            'tpm_usage': tpm_usage,
            'tpm_max': self.max_tokens,
            'tpm_utilization': tpm_usage / self.max_tokens if self.max_tokens else 0,
            'rpd_usage': rpd_usage,
            'rpd_max': self.max_daily_requests,
            'rpd_remaining': self.get_rpd_remaining(),
            'throttle_factor': self.throttle_factor,
            'consecutive_errors': self.consecutive_errors
        }
    
    def print_stats(self):
        """In thống kê ra console"""
        stats = self.get_stats()
        
        print("\n" + "="*60)
        print("📊 RATE LIMITER STATISTICS")
        print("="*60)
        print(f"RPM: {stats['rpm_usage']}/{stats['rpm_max']} ({stats['rpm_utilization']:.1%})")
        
        if stats['tpm_max']:
            print(f"TPM: {stats['tpm_usage']}/{stats['tpm_max']} ({stats['tpm_utilization']:.1%})")
        
        if stats['rpd_max']:
            print(f"RPD: {stats['rpd_usage']}/{stats['rpd_max']} ({stats['rpd_remaining']} remaining)")
        
        if stats['throttle_factor'] < 1.0:
            print(f"Throttle: {stats['throttle_factor']:.1%} (errors: {stats['consecutive_errors']})")
        
        print("="*60)
    
    def debug_state(self):
        """Print detailed debug state (for troubleshooting)"""
        with self.lock:
            now = datetime.now()
            self._cleanup_old_requests(now)
            
            print("\n" + "🔍"*30)
            print("🐛 RATE LIMITER DEBUG STATE")
            print("🔍"*30)
            print(f"⏰ Current Time: {now.strftime('%H:%M:%S.%f')[:-3]}")
            print(f"📊 Requests in window: {len(self.requests)}/{self.max_requests}")
            
            if self.requests:
                oldest = self.requests[0]
                newest = self.requests[-1]
                window_span = (newest - oldest).total_seconds()
                print(f"📅 Request window span: {window_span:.2f}s")
                print(f"   Oldest: {oldest.strftime('%H:%M:%S.%f')[:-3]}")
                print(f"   Newest: {newest.strftime('%H:%M:%S.%f')[:-3]}")
                
                # Show all requests timestamps
                if len(self.requests) <= 20:
                    print(f"📋 All requests:")
                    for i, req_time in enumerate(self.requests):
                        age = (now - req_time).total_seconds()
                        print(f"   [{i+1}] {req_time.strftime('%H:%M:%S.%f')[:-3]} (age: {age:.2f}s)")
        
        if self.max_tokens:
            with self.token_lock:
                now = datetime.now()
                self._cleanup_old_tokens(now)
                tpm_usage = sum(t[1] for t in self.tokens_used)
                print(f"🔤 TPM Usage: {tpm_usage:,}/{self.max_tokens:,}")
        
        with self.daily_lock:
            today = datetime.now().strftime("%Y-%m-%d")
            rpd_usage = self.daily_requests.get(today, 0)
            if self.max_daily_requests:
                print(f"📆 RPD Usage: {rpd_usage}/{self.max_daily_requests}")
            else:
                print(f"📆 RPD Usage: {rpd_usage} (unlimited)")
        
        print(f"⚙️ Throttle Factor: {self.throttle_factor:.2f}")
        print(f"❌ Consecutive Errors: {self.consecutive_errors}")
        print("🔍"*30 + "\n")
    
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


class ImprovedKeyRotator:
    """
    Improved key rotator với health tracking và smart rotation
    """
    
    def __init__(self, api_keys, same_project=True):
        """
        Initialize key rotator
        
        Args:
            api_keys: List of API keys
            same_project: Tất cả keys có cùng project không
        """
        self.api_keys = list(api_keys)  # Convert to list
        self.same_project = same_project
        self.current_index = 0
        self.lock = threading.Lock()
        self.is_multi_key = len(api_keys) > 1
        
        # Key health tracking
        self.key_stats = {
            key: {
                'success_count': 0,
                'error_count': 0,
                'rate_limit_errors': 0,
                'last_used': None,
                'last_error': None,
                'is_healthy': True,
                'consecutive_errors': 0
            }
            for key in api_keys
        }
    
    def get_next_key(self):
        """
        Lấy key tiếp theo
        
        Returns:
            API key string
        """
        with self.lock:
            if not self.api_keys:
                raise ValueError("No API keys available")
            
            if self.same_project:
                # Same project: Chọn key healthy nhất (ít lỗi nhất)
                best_key = min(
                    [k for k in self.api_keys if self.key_stats[k]['is_healthy']],
                    key=lambda k: (
                        self.key_stats[k]['error_count'],
                        -self.key_stats[k]['success_count']  # Ưu tiên key có nhiều success
                    ),
                    default=self.api_keys[0]  # Fallback
                )
                
                self.key_stats[best_key]['last_used'] = datetime.now()
                return best_key
            
            else:
                # Different projects: Round-robin với skip unhealthy keys
                attempts = 0
                max_attempts = len(self.api_keys) * 2
                
                while attempts < max_attempts:
                    key = self.api_keys[self.current_index]
                    self.current_index = (self.current_index + 1) % len(self.api_keys)
                    
                    # Bỏ qua keys không healthy
                    if self.key_stats[key]['is_healthy']:
                        self.key_stats[key]['last_used'] = datetime.now()
                        return key
                    
                    attempts += 1
                
                # Fallback: Return first key (even if unhealthy)
                print("⚠️ Warning: All keys unhealthy, using first key as fallback")
                return self.api_keys[0]
    
    def report_success(self, key):
        """Báo cáo key hoạt động tốt"""
        with self.lock:
            if key in self.key_stats:
                self.key_stats[key]['success_count'] += 1
                self.key_stats[key]['consecutive_errors'] = 0
                
                # Recovery: Mark healthy nếu có successes sau lỗi
                if self.key_stats[key]['error_count'] > 0:
                    success_ratio = self.key_stats[key]['success_count'] / (
                        self.key_stats[key]['success_count'] + self.key_stats[key]['error_count']
                    )
                    if success_ratio > 0.8:  # 80% success rate
                        self.key_stats[key]['is_healthy'] = True
    
    def report_error(self, key, is_rate_limit=False):
        """Báo cáo key gặp lỗi"""
        with self.lock:
            if key in self.key_stats:
                self.key_stats[key]['error_count'] += 1
                self.key_stats[key]['consecutive_errors'] += 1
                self.key_stats[key]['last_error'] = datetime.now()
                
                if is_rate_limit:
                    self.key_stats[key]['rate_limit_errors'] += 1
                
                # Mark unhealthy nếu nhiều consecutive errors
                if self.key_stats[key]['consecutive_errors'] >= 3:
                    self.key_stats[key]['is_healthy'] = False
                    print(f"⚠️ Key ***{key[-8:]} marked as unhealthy (3+ consecutive errors)")
    
    def get_usage_stats(self):
        """Lấy thống kê sử dụng keys"""
        with self.lock:
            return {
                key: {
                    'success': stats['success_count'],
                    'error': stats['error_count'],
                    'rate_limit': stats['rate_limit_errors'],
                    'healthy': stats['is_healthy']
                }
                for key, stats in self.key_stats.items()
            }
    
    def print_stats(self):
        """In thống kê chi tiết"""
        with self.lock:
            print("\n" + "="*60)
            print("🔑 KEY USAGE STATISTICS")
            print("="*60)
            print(f"Mode: {'Same Project' if self.same_project else 'Multi-Project'}")
            print(f"Total keys: {len(self.api_keys)}")
            print()
            
            for i, (key, stats) in enumerate(self.key_stats.items(), 1):
                key_display = f"***{key[-8:]}"
                health = "✅" if stats['is_healthy'] else "❌"
                
                total = stats['success_count'] + stats['error_count']
                success_rate = (stats['success_count'] / total * 100) if total > 0 else 0
                
                print(f"{health} Key {i}: {key_display}")
                print(f"   Success: {stats['success_count']} ({success_rate:.1f}%)")
                print(f"   Errors: {stats['error_count']} (consecutive: {stats['consecutive_errors']})")
                print(f"   Rate limits: {stats['rate_limit_errors']}")
                
                if stats['last_used']:
                    print(f"   Last used: {stats['last_used'].strftime('%H:%M:%S')}")
                if stats['last_error']:
                    print(f"   Last error: {stats['last_error'].strftime('%H:%M:%S')}")
                print()
            
            print("="*60)
    
    def get_health_summary(self):
        """Lấy summary về health của tất cả keys"""
        with self.lock:
            healthy_count = sum(1 for s in self.key_stats.values() if s['is_healthy'])
            total_success = sum(s['success_count'] for s in self.key_stats.values())
            total_error = sum(s['error_count'] for s in self.key_stats.values())
            total_rate_limit = sum(s['rate_limit_errors'] for s in self.key_stats.values())
            
            overall_success_rate = 0
            if total_success + total_error > 0:
                overall_success_rate = total_success / (total_success + total_error) * 100
            
            return {
                'healthy_keys': healthy_count,
                'total_keys': len(self.api_keys),
                'total_success': total_success,
                'total_error': total_error,
                'total_rate_limit': total_rate_limit,
                'success_rate': overall_success_rate
            }


# Example usage
if __name__ == "__main__":
    # Test enhanced rate limiter
    print("Testing Enhanced Rate Limiter...")
    
    # Create rate limiter với RPM=10, TPM=1000, RPD=100
    limiter = EnhancedRateLimiter(
        requests_per_minute=10,
        tokens_per_minute=1000,
        requests_per_day=100
    )
    
    # Simulate requests
    for i in range(5):
        print(f"\nRequest {i+1}:")
        limiter.acquire(estimated_tokens=100)
        print("✅ Request acquired")
        time.sleep(0.5)
    
    # Print stats
    limiter.print_stats()
    
    # Test key rotator
    print("\n\nTesting Key Rotator...")
    
    keys = ["key1", "key2", "key3", "key4", "key5"]
    rotator = ImprovedKeyRotator(keys, same_project=True)
    
    # Simulate usage
    for i in range(10):
        key = rotator.get_next_key()
        print(f"Using key: ***{key[-4:]}")
        
        # Simulate random success/error
        import random
        if random.random() > 0.2:  # 80% success
            rotator.report_success(key)
        else:
            rotator.report_error(key, is_rate_limit=(random.random() > 0.5))
    
    # Print stats
    rotator.print_stats()
    
    # Print health summary
    summary = rotator.get_health_summary()
    print(f"\n📊 Health Summary:")
    print(f"   Healthy keys: {summary['healthy_keys']}/{summary['total_keys']}")
    print(f"   Overall success rate: {summary['success_rate']:.1f}%")
