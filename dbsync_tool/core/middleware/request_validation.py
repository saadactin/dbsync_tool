"""
Request validation middleware
"""
import logging
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from core.error_responses import create_error_response, ErrorCode
from core.sanitization import sanitize_string

logger = logging.getLogger(__name__)

# Snapshot/status endpoints pass many UUIDs in one query param; keep limit high enough
# that truncation does not trigger false "suspicious input" warnings.
MAX_QUERY_KEY_LENGTH = 100
MAX_QUERY_VALUE_LENGTH = getattr(
    settings,
    'REQUEST_VALIDATION_QUERY_VALUE_MAX_LENGTH',
    8192,
)


class RequestValidationMiddleware(MiddlewareMixin):
    """
    Middleware to validate requests before processing
    
    - Request size limits
    - Header validation
    - Query parameter validation
    - Basic input sanitization
    """
    
    # Maximum request size in bytes.
    # None disables request-size enforcement (unlimited).
    MAX_REQUEST_SIZE = getattr(settings, 'REQUEST_VALIDATION_MAX_REQUEST_SIZE', None)
    
    # Required headers for API requests
    API_REQUIRED_HEADERS = ['Content-Type']
    
    def process_request(self, request):
        """Validate request before processing"""
        # Skip validation for static/media files
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return None
        
        # Check request size
        content_length = request.META.get('CONTENT_LENGTH')
        if self.MAX_REQUEST_SIZE is not None and content_length:
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
            content_length = request.META.get('CONTENT_LENGTH', '0')

            # DEBUG LOGGING
            logger.info(f"[RequestValidation] Path: {request.path}, Method: {request.method}")
            logger.info(f"[RequestValidation] Content-Type: '{content_type}'")
            logger.info(f"[RequestValidation] Content-Length: '{content_length}'")

            # Allow empty body for PATCH/DELETE (toggle/delete operations)
            try:
                body_size = int(content_length)
                if body_size == 0 and request.method in ['PATCH', 'DELETE']:
                    logger.info(f"[RequestValidation] Allowing empty body PATCH/DELETE")
                    return None  # Skip validation for empty body PATCH/DELETE
            except (ValueError, TypeError):
                pass

            if not content_type:
                # Allow form submissions without explicit Content-Type
                if not request.path.startswith('/api/'):
                    return None

            # For API requests, validate Content-Type only if there's a body
            if request.path.startswith('/api/'):
                # Allow application/json, multipart/form-data, or form-urlencoded
                valid_types = ['application/json', 'multipart/form-data', 'application/x-www-form-urlencoded']
                if not any(ct in content_type for ct in valid_types):
                    logger.error(f"[RequestValidation] REJECTED - Content-Type '{content_type}' not in {valid_types}")
                    return create_error_response(
                        code=ErrorCode.BAD_REQUEST,
                        message=f"Invalid Content-Type: '{content_type}'. Expected application/json, multipart/form-data, or application/x-www-form-urlencoded.",
                        status_code=400
                    )
                else:
                    logger.info(f"[RequestValidation] Content-Type validation passed")
        
        # Log query params only when sanitization actually changes key or value
        # (previous code compared param names to sanitized values by mistake).
        if request.GET:
            for key in request.GET.keys():
                sanitized_key = sanitize_string(key, max_length=MAX_QUERY_KEY_LENGTH)
                key_suspicious = sanitized_key != key
                for value in request.GET.getlist(key):
                    sanitized_value = sanitize_string(
                        value, max_length=MAX_QUERY_VALUE_LENGTH
                    )
                    if key_suspicious or sanitized_value != value:
                        logger.warning(
                            f"Suspicious input detected in query parameters: {key}",
                            extra={
                                'path': request.path,
                                'method': request.method,
                                'ip': self.get_client_ip(request),
                            },
                        )
                        break
        
        return None
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip

