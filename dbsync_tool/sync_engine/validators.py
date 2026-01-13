"""
Data validation utilities for sync operations
"""
from typing import List, Tuple, Any
from sync_engine.exceptions import ValidationError as SyncValidationError
import logging

logger = logging.getLogger(__name__)

class DataValidator:
    """Validates data before insertion"""
    
    @staticmethod
    def validate_row_count(
        source_count: int,
        target_count: int,
        table_name: str,
        strict: bool = False
    ):
        """
        Validate row counts match (optional validation)
        
        Args:
            source_count: Source row count
            target_count: Target row count
            table_name: Table name for logging
            strict: If True, raise error on mismatch
            
        Raises:
            SyncValidationError: If strict=True and counts don't match
        """
        if source_count != target_count:
            message = (
                f"Row count mismatch for {table_name}: "
                f"source={source_count}, target={target_count}"
            )
            if strict:
                raise SyncValidationError(message)
            else:
                logger.warning(message)
    
    @staticmethod
    def validate_data_types(
        row: Tuple,
        columns: List,
        table_name: str
    ):
        """
        Validate data types in a row
        
        Args:
            row: Row tuple
            columns: List of column info objects
            table_name: Table name for error messages
            
        Raises:
            SyncValidationError: If row length doesn't match columns
        """
        if len(row) != len(columns):
            raise SyncValidationError(
                f"Row length mismatch in {table_name}: "
                f"expected {len(columns)}, got {len(row)}"
            )
        
        # Additional type validation can be added here
        # For now, let the database handle type conversion
    
    @staticmethod
    def sanitize_batch(
        rows: List[Tuple],
        max_batch_size: int = 5000
    ) -> List[Tuple]:
        """
        Sanitize and limit batch size
        
        Args:
            rows: List of row tuples
            max_batch_size: Maximum batch size
            
        Returns:
            Sanitized batch of rows
        """
        if len(rows) > max_batch_size:
            logger.warning(
                f"Batch size {len(rows)} exceeds max {max_batch_size}, truncating"
            )
            return rows[:max_batch_size]
        return rows
    
    @staticmethod
    def validate_batch_not_empty(rows: List[Tuple], table_name: str):
        """
        Validate batch is not empty
        
        Args:
            rows: List of row tuples
            table_name: Table name for error messages
            
        Raises:
            SyncValidationError: If batch is empty
        """
        if not rows:
            raise SyncValidationError(f"Empty batch for table {table_name}")

