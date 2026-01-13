"""
Custom exceptions for the database sync tool
"""

class BaseSyncException(Exception):
    """Base exception for all sync-related errors"""
    pass


class DatabaseConnectionError(BaseSyncException):
    """Raised when database connection fails"""
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


class ValidationError(BaseSyncException):
    """Raised when data validation fails"""
    pass

