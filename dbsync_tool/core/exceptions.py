"""
Custom exceptions for the database sync tool
"""

class BaseSyncException(Exception):
    """Base exception for all sync-related errors"""
    def __init__(self, message, code=None, details=None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class ValidationException(BaseSyncException):
    """Base exception for all validation errors"""
    pass


class AuthenticationException(BaseSyncException):
    """Raised when authentication fails (login failures, expired sessions)"""
    pass


class AuthorizationException(BaseSyncException):
    """Raised when authorization fails (permission denied, role-based access)"""
    pass


class BusinessLogicException(BaseSyncException):
    """Raised when business rule violations occur"""
    pass


class DatabaseException(BaseSyncException):
    """Base exception for database-related errors"""
    pass


class DatabaseConnectionError(DatabaseException):
    """Raised when database connection fails"""
    pass


class DatabaseQueryError(DatabaseException):
    """Raised when database query execution fails"""
    pass


class DatabaseDeadlockError(DatabaseException):
    """Raised when database deadlock occurs"""
    pass


class DatabaseTimeoutError(DatabaseException):
    """Raised when database operation times out"""
    pass


class InvalidDatabaseTypeError(BaseSyncException):
    """Raised when database type is invalid or not supported"""
    pass


class TableNotFoundError(BaseSyncException):
    """Raised when a requested table is not found in the database"""
    pass


class SyncExecutionError(BaseSyncException):
    """Raised when sync execution fails"""
    pass


class EncryptionError(BaseSyncException):
    """Raised when encryption/decryption operations fail"""
    pass


class ValidationError(ValidationException):
    """Raised when data validation fails"""
    pass


class ExternalAPIException(BaseSyncException):
    """Raised when external API calls fail"""
    pass


class ConfigurationException(BaseSyncException):
    """Raised when configuration is missing or invalid"""
    pass


class RateLimitException(BaseSyncException):
    """Raised when rate limit is exceeded"""
    def __init__(self, message, retry_after=None, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class TimeoutException(BaseSyncException):
    """Raised when operation times out"""
    pass

