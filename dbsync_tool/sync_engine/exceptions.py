"""
Custom exceptions for sync engine
"""
from core.exceptions import BaseSyncException

class SyncExecutionError(BaseSyncException):
    """Base exception for sync execution errors"""
    pass

class TableSyncError(SyncExecutionError):
    """Error during table synchronization"""
    pass

class SchemaCreationError(SyncExecutionError):
    """Error creating schema"""
    pass

class TableCreationError(SyncExecutionError):
    """Error creating table"""
    pass

class DataFetchError(SyncExecutionError):
    """Error fetching data from source"""
    pass

class DataInsertError(SyncExecutionError):
    """Error inserting data into target"""
    pass

class CheckpointError(SyncExecutionError):
    """Error managing checkpoints"""
    pass

class QueryBuilderError(SyncExecutionError):
    """Error building queries"""
    pass

class ValidationError(SyncExecutionError):
    """Data validation error"""
    pass


