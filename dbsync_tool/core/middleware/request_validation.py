"""
Request validation middleware
"""
import logging
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from core.error_responses import create_error_response, ErrorCode
from core.sanitization import sanitize_string

logger = logging.getLogger(__name__)


class RequestValidationMiddleware(MiddlewareMixin):
    """
    Middleware to validate requests before processing
    
    - Request size limits
    - Header validation
    - Query parameter validation
    - Basic input sanitization
    """
    
    # Maximum request size (10MB)
    MAX_REQUEST_SIZE = 10 * 1024 * 1024
    
    # Required headers for API requests
    API_REQUIRED_HEADERS = ['Content-Type']
    
    def process_request(self, request):
        """Validate request before processing"""
        # Skip validation for static/media files
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return None
        
        # Check request size
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                size = int(content_length)
                if size > self.MAX_REQUEST_SIZE:
                    return create_error_response(
                        code=ErrorCode.BAD_REQUEST,
                        message=f"Request too large. Maximum size is {self.MAX_REQUEST_SIZE / 1024 / 1024}MB.",
                        status_code=413
                    )
            except (ValueError, TypeError):
                pass
        
        # Validate Content-Type for POST/PUT/PATCH requests
        if request.method in ['POST', 'PUT', 'PATCH']:
            content_type = request.META.get('CONTENT_TYPE', '')
            if not content_type:
                # Allow form submissions without explicit Content-Type
                if not request.path.startswith('/api/'):
                    return None
            
            # For API requests, validate Content-Type
            if request.path.startswith('/api/'):
                if 'application/json' not in content_type and 'multipart/form-data' not in content_type:
                    if 'application/x-www-form-urlencoded' not in content_type:
                        return create_error_response(
                            code=ErrorCode.BAD_REQUEST,
                            message="Invalid Content-Type. Expected application/json or multipart/form-data.",
                            status_code=400
                        )
        
        # Basic query parameter sanitization
        if request.GET:
            sanitized_get = {}
            for key, value in request.GET.items():
                # Sanitize key and value
                sanitized_key = sanitize_string(key, max_length=100)
                sanitized_value = sanitize_string(value, max_length=1000)
                sanitized_get[sanitized_key] = sanitized_value
            # Note: We can't modify request.GET directly, but we log suspicious inputs
            for key, value in request.GET.items():
                if key != sanitized_get.get(key, key) or value != sanitized_get.get(key, value):
                    logger.warning(
                        f"Suspicious input detected in query parameters: {key}",
                        extra={
                            'path': request.path,
                            'method': request.method,
                            'ip': self.get_client_ip(request),
                        }
                    )
        
        return None
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip

