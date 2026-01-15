"""
Standardized error response format for the application
"""
from django.http import JsonResponse
from django.utils import timezone
import uuid
import logging

logger = logging.getLogger(__name__)


class ErrorCode:
    """Error code enumeration"""
    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    REQUIRED_FIELD = "REQUIRED_FIELD"
    INVALID_FORMAT = "INVALID_FORMAT"
    INVALID_LENGTH = "INVALID_LENGTH"
    INVALID_RANGE = "INVALID_RANGE"
    INVALID_ENUM = "INVALID_ENUM"
    UNIQUE_CONSTRAINT = "UNIQUE_CONSTRAINT"
    FOREIGN_KEY_ERROR = "FOREIGN_KEY_ERROR"
    
    # Authentication errors
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    TOO_MANY_LOGIN_ATTEMPTS = "TOO_MANY_LOGIN_ATTEMPTS"
    
    # Authorization errors
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    TENANT_ACCESS_DENIED = "TENANT_ACCESS_DENIED"
    
    # Business logic errors
    BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
    INVALID_STATE = "INVALID_STATE"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    
    # Database errors
    DATABASE_CONNECTION_ERROR = "DATABASE_CONNECTION_ERROR"
    DATABASE_QUERY_ERROR = "DATABASE_QUERY_ERROR"
    DATABASE_DEADLOCK = "DATABASE_DEADLOCK"
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"
    TRANSACTION_ERROR = "TRANSACTION_ERROR"
    
    # External errors
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    
    # Configuration errors
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    
    # Rate limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    
    # Timeout errors
    OPERATION_TIMEOUT = "OPERATION_TIMEOUT"
    
    # Generic errors
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    BAD_REQUEST = "BAD_REQUEST"


def create_error_response(
    code,
    message,
    details=None,
    trace_id=None,
    status_code=400,
    retry_after=None
):
    """
    Create a standardized error response
    
    Args:
        code: Error code from ErrorCode enum
        message: User-friendly error message
        details: Optional additional error details
        trace_id: Optional trace ID for correlation
        status_code: HTTP status code
        retry_after: Optional retry-after seconds for rate limiting
    
    Returns:
        JsonResponse with standardized error format
    """
    if trace_id is None:
        trace_id = str(uuid.uuid4())
    
    error_data = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "trace_id": trace_id
        },
        "timestamp": timezone.now().isoformat()
    }
    
    response = JsonResponse(error_data, status=status_code)
    
    if retry_after is not None:
        response['Retry-After'] = str(retry_after)
    
    return response


def error_response_from_exception(exception, trace_id=None, debug=False):
    """
    Create error response from exception
    
    Args:
        exception: Exception instance
        trace_id: Optional trace ID
        debug: If True, include stack trace in details
    
    Returns:
        JsonResponse with standardized error format
    """
    from core.exceptions import (
        ValidationException,
        AuthenticationException,
        AuthorizationException,
        BusinessLogicException,
        DatabaseException,
        DatabaseConnectionError,
        DatabaseQueryError,
        DatabaseDeadlockError,
        DatabaseTimeoutError,
        ExternalAPIException,
        ConfigurationException,
        RateLimitException,
        TimeoutException,
    )
    
    # Map exception types to error codes and status codes
    exception_mapping = {
        ValidationException: (ErrorCode.VALIDATION_ERROR, 400),
        AuthenticationException: (ErrorCode.AUTHENTICATION_FAILED, 401),
        AuthorizationException: (ErrorCode.PERMISSION_DENIED, 403),
        BusinessLogicException: (ErrorCode.BUSINESS_RULE_VIOLATION, 400),
        DatabaseConnectionError: (ErrorCode.DATABASE_CONNECTION_ERROR, 500),
        DatabaseQueryError: (ErrorCode.DATABASE_QUERY_ERROR, 500),
        DatabaseDeadlockError: (ErrorCode.DATABASE_DEADLOCK, 500),
        DatabaseTimeoutError: (ErrorCode.DATABASE_TIMEOUT, 504),
        ExternalAPIException: (ErrorCode.EXTERNAL_API_ERROR, 502),
        ConfigurationException: (ErrorCode.CONFIGURATION_ERROR, 500),
        RateLimitException: (ErrorCode.RATE_LIMIT_EXCEEDED, 429),
        TimeoutException: (ErrorCode.OPERATION_TIMEOUT, 504),
    }
    
    # Get error code and status
    error_code = ErrorCode.INTERNAL_SERVER_ERROR
    status_code = 500
    retry_after = None
    
    for exc_type, (code, status) in exception_mapping.items():
        if isinstance(exception, exc_type):
            error_code = code
            status_code = status
            if isinstance(exception, RateLimitException) and hasattr(exception, 'retry_after'):
                retry_after = exception.retry_after
            break
    
    # Get message
    message = str(exception) if str(exception) else "An error occurred"
    
    # Build details
    details = {}
    if hasattr(exception, 'details'):
        details.update(exception.details)
    
    if debug:
        import traceback
        details['stack_trace'] = traceback.format_exc()
    
    return create_error_response(
        code=error_code,
        message=message,
        details=details,
        trace_id=trace_id,
        status_code=status_code,
        retry_after=retry_after
    )

