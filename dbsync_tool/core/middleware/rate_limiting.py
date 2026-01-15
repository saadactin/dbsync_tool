"""
Rate limiting middleware
"""
import time
import logging
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from core.error_responses import create_error_response, ErrorCode
from core.exceptions import RateLimitException

logger = logging.getLogger(__name__)


class RateLimitingMiddleware(MiddlewareMixin):
    """
    Rate limiting middleware to prevent abuse
    
    Rate limits:
    - Per-user: Login attempts (5 per 15 min), API requests (100 per min), Form submissions (10 per min)
    - Per-IP: General requests (200 per min), Login attempts (10 per hour)
    - Per-endpoint: Connection test (10 per min), Metadata loading (20 per min), Job execution (5 per hour)
    """
    
    # Rate limit configurations
    RATE_LIMITS = {
        'login': {
            'per_user': {'limit': 5, 'window': 900},  # 5 per 15 minutes
            'per_ip': {'limit': 10, 'window': 3600},  # 10 per hour
        },
        'api': {
            'per_user': {'limit': 100, 'window': 60},  # 100 per minute
        },
        'form': {
            'per_user': {'limit': 10, 'window': 60},  # 10 per minute
        },
        'connection_test': {
            'per_user': {'limit': 10, 'window': 60},  # 10 per minute
        },
        'metadata': {
            'per_user': {'limit': 20, 'window': 60},  # 20 per minute
        },
        'job_execution': {
            'per_user': {'limit': 5, 'window': 3600},  # 5 per hour
        },
        'general': {
            'per_ip': {'limit': 200, 'window': 60},  # 200 per minute
        },
    }
    
    def process_request(self, request):
        """Check rate limits before processing request"""
        # Skip rate limiting for static/media files
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return None
        
        # Determine rate limit type based on path
        rate_limit_type = self._get_rate_limit_type(request)
        
        if not rate_limit_type:
            return None
        
        # Get rate limit config
        config = self.RATE_LIMITS.get(rate_limit_type, {})
        
        # Check per-user rate limit (defensive check for request.user)
        if hasattr(request, 'user') and request.user.is_authenticated and 'per_user' in config:
            user_key = f"rate_limit:{rate_limit_type}:user:{request.user.id}"
            if self._is_rate_limited(user_key, config['per_user']):
                retry_after = self._get_retry_after(user_key, config['per_user']['window'])
                logger.warning(
                    f"Rate limit exceeded for user {request.user.id} on {rate_limit_type}",
                    extra={
                        'user_id': request.user.id,
                        'username': request.user.username,
                        'rate_limit_type': rate_limit_type,
                        'path': request.path,
                    }
                )
                return create_error_response(
                    code=ErrorCode.RATE_LIMIT_EXCEEDED,
                    message=f"Too many requests. Please try again in {retry_after} seconds.",
                    status_code=429,
                    retry_after=retry_after
                )
        
        # Check per-IP rate limit
        if 'per_ip' in config:
            ip_address = self._get_client_ip(request)
            ip_key = f"rate_limit:{rate_limit_type}:ip:{ip_address}"
            if self._is_rate_limited(ip_key, config['per_ip']):
                retry_after = self._get_retry_after(ip_key, config['per_ip']['window'])
                logger.warning(
                    f"Rate limit exceeded for IP {ip_address} on {rate_limit_type}",
                    extra={
                        'ip_address': ip_address,
                        'rate_limit_type': rate_limit_type,
                        'path': request.path,
                    }
                )
                return create_error_response(
                    code=ErrorCode.RATE_LIMIT_EXCEEDED,
                    message=f"Too many requests from your IP. Please try again in {retry_after} seconds.",
                    status_code=429,
                    retry_after=retry_after
                )
        
        return None
    
    def process_response(self, request, response):
        """Add rate limit headers to response"""
        # Only add headers for API requests
        if request.path.startswith('/api/'):
            # Get rate limit type
            rate_limit_type = self._get_rate_limit_type(request)
            if rate_limit_type:
                config = self.RATE_LIMITS.get(rate_limit_type, {})
                
                # Add per-user rate limit headers (defensive check for request.user)
                if hasattr(request, 'user') and request.user.is_authenticated and 'per_user' in config:
                    user_key = f"rate_limit:{rate_limit_type}:user:{request.user.id}"
                    limit = config['per_user']['limit']
                    window = config['per_user']['window']
                    remaining = self._get_remaining(user_key, limit, window)
                    reset_time = int(time.time()) + window
                    
                    response['X-RateLimit-Limit'] = str(limit)
                    response['X-RateLimit-Remaining'] = str(remaining)
                    response['X-RateLimit-Reset'] = str(reset_time)
        
        return response
    
    def _get_rate_limit_type(self, request):
        """Determine rate limit type based on request path and method"""
        path = request.path.lower()
        method = request.method
        
        # Login attempts
        if path.endswith('/login/') and method == 'POST':
            return 'login'
        
        # API requests
        if path.startswith('/api/'):
            return 'api'
        
        # Connection test
        if '/test-connection' in path or '/test/' in path:
            return 'connection_test'
        
        # Metadata loading
        if '/metadata/' in path or '/schemas/' in path or '/tables/' in path:
            return 'metadata'
        
        # Job execution
        if '/run/' in path or '/execute/' in path:
            return 'job_execution'
        
        # Form submissions
        if method in ['POST', 'PUT', 'PATCH'] and not path.startswith('/api/'):
            return 'form'
        
        # General requests
        return 'general'
    
    def _is_rate_limited(self, key, config):
        """Check if rate limit is exceeded"""
        limit = config['limit']
        window = config['window']
        
        # Get current count
        count = cache.get(key, 0)
        
        if count >= limit:
            return True
        
        # Increment count
        cache.set(key, count + 1, window)
        return False
    
    def _get_retry_after(self, key, window):
        """Get retry-after seconds"""
        # Get TTL of the cache key
        ttl = cache.ttl(key)
        if ttl is None:
            return window
        return max(1, int(ttl))
    
    def _get_remaining(self, key, limit, window):
        """Get remaining requests"""
        count = cache.get(key, 0)
        return max(0, limit - count)
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip

