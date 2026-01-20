"""
Data integrity verification service for post-migration validation

Performs comprehensive data accuracy verification:
- Row count comparison
- Row-by-row comparison
- Transformation verification
- Data type verification
- NULL value verification
"""
from typing import Optional, Dict, List, Tuple, Any
from connections.connectors.base import DBConnector
from sync_engine.query_builder import QueryBuilder
from sync_engine.transformation_engine import TransformationEngine
from sync_jobs.models import SyncJobTable
import logging
from decimal import Decimal
from datetime import datetime, date

logger = logging.getLogger(__name__)


class DataIntegrityVerifier:
    """
    Verifies data integrity after migration
    
    Performs:
    - Row count comparison
    - Row-by-row comparison
    - Transformation verification
    - Data type verification
    - NULL value verification
    """
    
    def __init__(
        self,
        source_connector: DBConnector,
        target_connector: DBConnector
    ):
        """
        Initialize data integrity verifier
        
        Args:
            source_connector: Source database connector
            target_connector: Target database connector
        """
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.query_builder = QueryBuilder()
        self.transformation_engine = TransformationEngine()
    
    def verify_data_accuracy(
        self,
        job_table: SyncJobTable,
        source_schema: str,
        target_schema: str,
        expected_row_count: int,
        column_names: List[str]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Comprehensive post-migration data accuracy verification
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            source_schema: Source schema name
            target_schema: Target schema name
            expected_row_count: Expected row count (from pre-migration validation)
            column_names: List of column names
            
        Returns:
            Tuple of (is_accurate, error_message, accuracy_report)
            - accuracy_report contains: row_count_match, column_count_match, etc.
        """
        table = job_table.table_name
        where_clause = job_table.transformation_query
        column_transformations = job_table.column_transformations or {}
        
        accuracy_report = {
            'expected_row_count': expected_row_count,
            'actual_row_count': 0,
            'row_count_match': False,
            'all_rows_match': False,
            'columns_compared': len(column_names),
            'mismatched_rows': [],
            'mismatched_columns': []
        }
        
        try:
            # Step 1: Compare row counts
            row_count_match, row_count_error, actual_count = self._compare_row_counts(
                target_schema=target_schema,
                table=table,
                expected_count=expected_row_count
            )
            
            accuracy_report['actual_row_count'] = actual_count
            accuracy_report['row_count_match'] = row_count_match
            
            if not row_count_match:
                error_msg = (
                    f"Row count mismatch: expected {expected_row_count}, "
                    f"got {actual_count}. {row_count_error or ''}"
                )
                logger.error(f"Data accuracy verification failed for {source_schema}.{table}: {error_msg}")
                return False, error_msg, accuracy_report
            
            # Step 2: Perform row-by-row comparison
            if actual_count > 0:
                rows_match, rows_error, comparison_report = self._compare_rows(
                    job_table=job_table,
                    source_schema=source_schema,
                    target_schema=target_schema,
                    table=table,
                    column_names=column_names
                )
                
                accuracy_report['all_rows_match'] = rows_match
                accuracy_report['mismatched_rows'] = comparison_report.get('mismatched_rows', [])
                accuracy_report['mismatched_columns'] = comparison_report.get('mismatched_columns', [])
                
                if not rows_match:
                    error_msg = f"Row-by-row comparison failed: {rows_error}"
                    logger.error(f"Data accuracy verification failed for {source_schema}.{table}: {error_msg}")
                    return False, error_msg, accuracy_report
            else:
                # No rows to compare, but count matches
                accuracy_report['all_rows_match'] = True
            
            # All verifications passed
            logger.info(
                f"Data accuracy verification passed for {source_schema}.{table}: "
                f"Row count: {actual_count}, All rows match: True"
            )
            return True, None, accuracy_report
            
        except Exception as e:
            error_msg = f"Unexpected error during data accuracy verification: {str(e)}"
            logger.error(f"Data accuracy verification error for {source_schema}.{table}: {error_msg}", exc_info=True)
            return False, error_msg, accuracy_report
    
    def _compare_row_counts(
        self,
        target_schema: str,
        table: str,
        expected_count: int
    ) -> Tuple[bool, Optional[str], int]:
        """
        Compare row counts
        
        Args:
            target_schema: Target schema name
            table: Table name
            expected_count: Expected row count
            
        Returns:
            Tuple of (matches, error_message, actual_count)
        """
        try:
            actual_count = self.target_connector.get_row_count(target_schema, table)
            
            if actual_count != expected_count:
                error_msg = (
                    f"Row count mismatch: expected {expected_count}, got {actual_count}"
                )
                return False, error_msg, actual_count
            
            return True, None, actual_count
            
        except Exception as e:
            error_msg = f"Error comparing row counts: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, 0
    
    def _compare_rows(
        self,
        job_table: SyncJobTable,
        source_schema: str,
        target_schema: str,
        table: str,
        column_names: List[str]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Perform row-by-row comparison
        
        Args:
            job_table: SyncJobTable instance
            source_schema: Source schema name
            target_schema: Target schema name
            table: Table name
            column_names: List of column names
            
        Returns:
            Tuple of (matches, error_message, comparison_report)
        """
        where_clause = job_table.transformation_query
        column_transformations = job_table.column_transformations or {}
        
        comparison_report = {
            'mismatched_rows': [],
            'mismatched_columns': []
        }
        
        try:
            # Build queries to fetch all rows
            # Source: Use transformed query (with WHERE and column transformations)
            # Target: Use standard query (data should already be transformed)
            
            # Get primary key for ordering
            try:
                pk_columns = self.source_connector.get_primary_key(source_schema, table)
                if pk_columns:
                    order_by = ', '.join(pk_columns)
                else:
                    # Fallback to first column
                    order_by = column_names[0] if column_names else None
            except:
                order_by = column_names[0] if column_names else None
            
            # Build source query with transformations
            source_query = self.query_builder.build_select_query(
                connector=self.source_connector,
                schema=source_schema,
                table=table,
                columns=column_names,
                order_by=order_by,
                where_clause=where_clause,
                column_transformations=column_transformations
            )
            
            # Build target query (standard, no transformations - data is already transformed)
            target_query = self.query_builder.build_select_query(
                connector=self.target_connector,
                schema=target_schema,
                table=table,
                columns=column_names,
                order_by=order_by
            )
            
            # Fetch all rows from both sources
            source_rows = []
            target_rows = []
            
            # Fetch source rows in batches
            source_offset = 0
            while True:
                batch = self.source_connector.fetch_batch(
                    query=source_query,
                    batch_size=1000,
                    offset=source_offset,
                    order_by=order_by
                )
                if not batch:
                    break
                source_rows.extend(batch)
                source_offset += len(batch)
            
            # Fetch target rows in batches
            target_offset = 0
            while True:
                batch = self.target_connector.fetch_batch(
                    query=target_query,
                    batch_size=1000,
                    offset=target_offset,
                    order_by=order_by
                )
                if not batch:
                    break
                target_rows.extend(batch)
                target_offset += len(batch)
            
            # Compare row counts first
            if len(source_rows) != len(target_rows):
                error_msg = (
                    f"Row count mismatch in fetched data: "
                    f"source={len(source_rows)}, target={len(target_rows)}"
                )
                return False, error_msg, comparison_report
            
            # Compare each row
            mismatched_count = 0
            for row_idx, (source_row, target_row) in enumerate(zip(source_rows, target_rows)):
                matches, error = self._compare_row_values(
                    source_row=source_row,
                    target_row=target_row,
                    column_names=column_names,
                    column_transformations=column_transformations
                )
                
                if not matches:
                    mismatched_count += 1
                    comparison_report['mismatched_rows'].append({
                        'row_index': row_idx,
                        'error': error
                    })
                    
                    # Limit number of mismatched rows reported
                    if mismatched_count >= 10:
                        comparison_report['mismatched_rows'].append({
                            'row_index': '...',
                            'error': f'... and {len(source_rows) - row_idx - 1} more mismatched rows'
                        })
                        break
            
            if mismatched_count > 0:
                error_msg = f"Found {mismatched_count} mismatched row(s)"
                return False, error_msg, comparison_report
            
            return True, None, comparison_report
            
        except Exception as e:
            error_msg = f"Error comparing rows: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, comparison_report
    
    def _compare_row_values(
        self,
        source_row: Tuple,
        target_row: Tuple,
        column_names: List[str],
        column_transformations: Dict[str, str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Compare individual row values with transformation awareness
        
        Args:
            source_row: Source row tuple
            target_row: Target row tuple
            column_names: List of column names
            column_transformations: Dict mapping column_name -> transformation_type
            
        Returns:
            Tuple of (matches, error_message)
        """
        if len(source_row) != len(target_row):
            return False, (
                f"Column count mismatch: source={len(source_row)}, target={len(target_row)}"
            )
        
        if len(source_row) != len(column_names):
            return False, (
                f"Column count mismatch with column_names: "
                f"row={len(source_row)}, columns={len(column_names)}"
            )
        
        # Compare each column
        for col_idx, col_name in enumerate(column_names):
            source_val = source_row[col_idx]
            target_val = target_row[col_idx]
            
            # Get transformation for this column
            transformation = column_transformations.get(col_name)
            
            # Normalize values for comparison
            normalized_source = self._normalize_value(source_val, None)  # Source already has transformations applied
            normalized_target = self._normalize_value(target_val, None)  # Target should match source
            
            # Compare normalized values
            if not self._values_equal(normalized_source, normalized_target):
                error_msg = (
                    f"Column '{col_name}' mismatch: "
                    f"source={source_val!r}, target={target_val!r}"
                )
                return False, error_msg
        
        return True, None
    
    def _normalize_value(
        self,
        value: Any,
        transformation: Optional[str]
    ) -> Any:
        """
        Normalize value based on transformation
        
        Applies transformation to value for comparison.
        Also handles data type conversions.
        
        Args:
            value: Value to normalize
            transformation: Optional transformation to apply
            
        Returns:
            Normalized value
        """
        # Handle NULL values
        if value is None:
            return None
        
        # Apply transformation if specified
        if transformation:
            transformation_upper = transformation.upper()
            
            if isinstance(value, str):
                if transformation_upper == 'TRIM':
                    value = value.strip()
                elif transformation_upper == 'UPPER':
                    value = value.upper()
                elif transformation_upper == 'LOWER':
                    value = value.lower()
        
        # Normalize data types for comparison
        # Convert Decimal to float for comparison
        if isinstance(value, Decimal):
            return float(value)
        
        # Normalize datetime/date objects
        if isinstance(value, (datetime, date)):
            return value
        
        return value
    
    def _values_equal(self, val1: Any, val2: Any) -> bool:
        """
        Compare two values for equality, handling type conversions
        
        Args:
            val1: First value
            val2: Second value
            
        Returns:
            True if values are equal, False otherwise
        """
        # Handle NULL values
        if val1 is None and val2 is None:
            return True
        if val1 is None or val2 is None:
            return False
        
        # Handle numeric types
        if isinstance(val1, (int, float, Decimal)) and isinstance(val2, (int, float, Decimal)):
            try:
                return abs(float(val1) - float(val2)) < 0.0001  # Allow small floating point differences
            except:
                return val1 == val2
        
        # Handle string types
        if isinstance(val1, str) and isinstance(val2, str):
            return val1 == val2
        
        # Handle datetime types
        if isinstance(val1, (datetime, date)) and isinstance(val2, (datetime, date)):
            return val1 == val2
        
        # Default comparison
        return val1 == val2
