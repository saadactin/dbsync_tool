"""
Error logging middleware for structured error logging
"""
import logging
import uuid
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone

logger = logging.getLogger(__name__)


class ErrorLoggingMiddleware(MiddlewareMixin):
    """
    Middleware for structured error logging with correlation IDs
    """
    
    def process_request(self, request):
        """Generate correlation ID for request"""
        # Generate trace ID if not already set
        if not hasattr(request, 'trace_id'):
            request.trace_id = str(uuid.uuid4())
        
        # Log request start (optional, can be verbose)
        # logger.debug(f"Request started: {request.method} {request.path}", extra={
        #     'trace_id': request.trace_id,
        #     'user': getattr(request.user, 'username', 'anonymous'),
        # })
        
        return None
    
    def process_exception(self, request, exception):
        """Log exceptions with full context"""
        trace_id = getattr(request, 'trace_id', str(uuid.uuid4()))
        
        log_data = {
            'trace_id': trace_id,
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'path': request.path,
            'method': request.method,
            'user': getattr(request.user, 'username', 'anonymous') if hasattr(request, 'user') else 'anonymous',
            'user_id': getattr(request.user, 'id', None) if hasattr(request, 'user') else None,
            'ip_address': self._get_client_ip(request),
            'timestamp': timezone.now().isoformat(),
        }
        
        # Add query parameters (sanitized)
        if request.GET:
            log_data['query_params'] = dict(request.GET)
        
        # Add POST data (excluding sensitive fields)
        if hasattr(request, 'POST') and request.POST:
            sensitive_fields = ['password', 'password1', 'password2', 'csrfmiddlewaretoken']
            log_data['post_data'] = {
                k: '***' if k in sensitive_fields else v
                for k, v in request.POST.items()
            }
        
        logger.error(
            f"Exception in {request.method} {request.path}: {type(exception).__name__}",
            exc_info=True,
            extra=log_data
        )
        
        return None
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip

