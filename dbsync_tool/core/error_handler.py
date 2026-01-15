"""
Centralized error handler for the application
"""
import logging
import uuid
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, IntegrityError, OperationalError
from django.utils import timezone

from core.exceptions import (
    ValidationException,
    AuthenticationException,
    AuthorizationException,
    BusinessLogicException,
    DatabaseException,
    RateLimitException,
    TimeoutException,
)
from core.error_responses import error_response_from_exception, ErrorCode, create_error_response

logger = logging.getLogger(__name__)


class ErrorHandler:
    """Centralized error handler"""
    
    @staticmethod
    def get_trace_id(request):
        """Get or generate trace ID from request"""
        if hasattr(request, 'trace_id'):
            return request.trace_id
        trace_id = str(uuid.uuid4())
        request.trace_id = trace_id
        return trace_id
    
    @staticmethod
    def handle_exception(request, exception):
        """
        Handle exception and return appropriate response
        
        Args:
            request: Django request object
            exception: Exception instance
        
        Returns:
            HttpResponse with error details
        """
        trace_id = ErrorHandler.get_trace_id(request)
        debug = getattr(settings, 'DEBUG', False)
        
        # Log the error
        ErrorHandler.log_error(request, exception, trace_id)
        
        # Handle Django built-in exceptions
        if isinstance(exception, DjangoValidationError):
            return ErrorHandler.handle_validation_error(request, exception, trace_id)
        
        if isinstance(exception, PermissionDenied):
            return ErrorHandler.handle_permission_denied(request, exception, trace_id)
        
        if isinstance(exception, DatabaseError):
            return ErrorHandler.handle_database_error(request, exception, trace_id)
        
        # Handle custom exceptions
        if isinstance(exception, (ValidationException, AuthenticationException, 
                                 AuthorizationException, BusinessLogicException,
                                 DatabaseException, RateLimitException, TimeoutException)):
            return error_response_from_exception(exception, trace_id, debug)
        
        # Handle unknown exceptions
        return ErrorHandler.handle_unknown_error(request, exception, trace_id, debug)
    
    @staticmethod
    def handle_validation_error(request, exception, trace_id):
        """Handle Django ValidationError"""
        errors = {}
        if hasattr(exception, 'error_dict'):
            errors = {k: [str(e) for e in v] for k, v in exception.error_dict.items()}
        elif hasattr(exception, 'error_list'):
            errors = {'__all__': [str(e) for e in exception.error_list]}
        else:
            errors = {'__all__': [str(exception)]}
        
        return create_error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message="Validation failed. Please check your input.",
            details={'field_errors': errors},
            trace_id=trace_id,
            status_code=400
        )
    
    @staticmethod
    def handle_permission_denied(request, exception, trace_id):
        """Handle PermissionDenied"""
        return create_error_response(
            code=ErrorCode.PERMISSION_DENIED,
            message=str(exception) or "You do not have permission to perform this action.",
            trace_id=trace_id,
            status_code=403
        )
    
    @staticmethod
    def handle_database_error(request, exception, trace_id):
        """Handle database errors"""
        debug = getattr(settings, 'DEBUG', False)
        
        if isinstance(exception, IntegrityError):
            error_code = ErrorCode.UNIQUE_CONSTRAINT
            message = "A record with this information already exists."
        elif isinstance(exception, OperationalError):
            error_code = ErrorCode.DATABASE_CONNECTION_ERROR
            message = "Database connection error. Please try again later."
        else:
            error_code = ErrorCode.DATABASE_QUERY_ERROR
            message = "Database error occurred. Please try again later."
        
        details = {}
        if debug:
            details['error'] = str(exception)
        
        return create_error_response(
            code=error_code,
            message=message,
            details=details,
            trace_id=trace_id,
            status_code=500
        )
    
    @staticmethod
    def handle_unknown_error(request, exception, trace_id, debug):
        """Handle unknown exceptions"""
        logger.error(
            f"Unhandled exception: {type(exception).__name__}",
            exc_info=True,
            extra={
                'trace_id': trace_id,
                'path': request.path,
                'method': request.method,
                'user': getattr(request.user, 'username', 'anonymous'),
            }
        )
        
        message = "An unexpected error occurred. Please try again later."
        if debug:
            message = f"An error occurred: {str(exception)}"
        
        details = {}
        if debug:
            import traceback
            details['stack_trace'] = traceback.format_exc()
            details['exception_type'] = type(exception).__name__
        
        return create_error_response(
            code=ErrorCode.INTERNAL_SERVER_ERROR,
            message=message,
            details=details,
            trace_id=trace_id,
            status_code=500
        )
    
    @staticmethod
    def log_error(request, exception, trace_id):
        """Log error with context"""
        log_data = {
            'trace_id': trace_id,
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'path': request.path,
            'method': request.method,
            'user': getattr(request.user, 'username', 'anonymous'),
            'user_id': getattr(request.user, 'id', None),
            'ip_address': ErrorHandler.get_client_ip(request),
            'timestamp': timezone.now().isoformat(),
        }
        
        # Add request data (excluding sensitive fields)
        if hasattr(request, 'POST'):
            log_data['post_data'] = {
                k: v for k, v in request.POST.items() 
                if k not in ['password', 'password1', 'password2', 'csrfmiddlewaretoken']
            }
        
        logger.error(
            f"Error: {type(exception).__name__} - {str(exception)}",
            exc_info=True,
            extra=log_data
        )
    
    @staticmethod
    def get_client_ip(request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip
    
    @staticmethod
    def format_user_message(exception):
        """
        Format user-friendly error message from exception
        
        Args:
            exception: Exception instance
        
        Returns:
            User-friendly error message
        """
        # Map exception types to user-friendly messages
        message_map = {
            ValidationException: "Please check your input and try again.",
            AuthenticationException: "Authentication failed. Please check your credentials.",
            AuthorizationException: "You do not have permission to perform this action.",
            BusinessLogicException: "This operation cannot be completed due to business rules.",
            DatabaseException: "A database error occurred. Please try again later.",
            RateLimitException: "Too many requests. Please try again later.",
            TimeoutException: "The operation timed out. Please try again.",
        }
        
        for exc_type, default_message in message_map.items():
            if isinstance(exception, exc_type):
                return str(exception) if str(exception) else default_message
        
        return "An error occurred. Please try again later."

