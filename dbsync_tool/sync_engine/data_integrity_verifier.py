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
from datetime import datetime, date, timezone

logger = logging.getLogger(__name__)


def _utc_normalize(dt: Any) -> Optional[datetime]:
    """Normalize datetime to UTC for comparison. Returns None for non-datetime."""
    if dt is None:
        return None
    if not isinstance(dt, (datetime, date)):
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime.combine(dt, datetime.min.time(), tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
        column_names: List[str],
        target_column_names: Optional[List[str]] = None,
        target_table: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Comprehensive post-migration data accuracy verification
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            source_schema: Source schema name
            target_schema: Target schema name
            expected_row_count: Expected row count (from pre-migration validation)
            column_names: List of column names
            target_table: Target table name (e.g. with prefix). If None, use job_table.table_name.
            
        Returns:
            Tuple of (is_accurate, error_message, accuracy_report)
            - accuracy_report contains: row_count_match, column_count_match, etc.
        """
        table = job_table.table_name
        if target_table is None:
            target_table = table
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
                table=target_table,
                expected_count=expected_row_count
            )
            
            accuracy_report['actual_row_count'] = actual_count
            accuracy_report['row_count_match'] = row_count_match
            
            if not row_count_match:
                source_db = QueryBuilder.get_db_type(self.source_connector)
                target_db = QueryBuilder.get_db_type(self.target_connector)
                db_context = ""
                if source_db == 'oracle' or target_db == 'oracle':
                    db_context = " (Oracle ADW involved; schema=%s, table=%s)" % (target_schema, table)
                error_msg = (
                    f"Row count mismatch: expected {expected_row_count}, "
                    f"got {actual_count}. {row_count_error or ''}{db_context}"
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
                    column_names=column_names,
                    target_column_names=target_column_names,
                    target_table=target_table,
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
        column_names: List[str],
        target_column_names: Optional[List[str]] = None,
        target_table: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Perform row-by-row comparison
        
        Args:
            job_table: SyncJobTable instance
            source_schema: Source schema name
            target_schema: Target schema name
            table: Source table name
            column_names: List of column names
            target_table: Target table name (e.g. with prefix). If None, use table.
            
        Returns:
            Tuple of (matches, error_message, comparison_report)
        """
        if target_table is None:
            target_table = table
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
            except:
                pk_columns = []

            if pk_columns:
                order_by_source = ', '.join(pk_columns)
                # PK columns are protected by the rename feature, so target order-by should match.
                order_by_target = order_by_source
            else:
                order_by_source = column_names[0] if column_names else None
                order_by_target = (
                    (target_column_names or column_names)[0]
                    if column_names else None
                )
            
            # Build source query with transformations
            source_query = self.query_builder.build_select_query(
                connector=self.source_connector,
                schema=source_schema,
                table=table,
                columns=column_names,
                order_by=order_by_source,
                where_clause=where_clause,
                column_transformations=column_transformations
            )
            
            # Build target query (standard, no transformations - data is already transformed)
            target_query = self.query_builder.build_select_query(
                connector=self.target_connector,
                schema=target_schema,
                table=target_table,
                columns=(target_column_names or column_names),
                order_by=order_by_target
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
                    order_by=order_by_source
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
                    order_by=order_by_target
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
            
            # Log query details for debugging
            logger.debug(
                f"Comparing rows: source_query={source_query}, target_query={target_query}, "
                f"source_rows_count={len(source_rows)}, target_rows_count={len(target_rows)}, "
                f"column_names={column_names}"
            )
            
            # Compare each row
            mismatched_count = 0
            for row_idx, (source_row, target_row) in enumerate(zip(source_rows, target_rows)):
                # Log first row for debugging
                if row_idx == 0:
                    logger.debug(
                        f"First row comparison: source={source_row}, target={target_row}, "
                        f"source_types={[type(v).__name__ for v in source_row]}, "
                        f"target_types={[type(v).__name__ for v in target_row]}"
                    )
                
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
                        'error': error,
                        'source_row': str(source_row),
                        'target_row': str(target_row)
                    })
                    
                    # Log first mismatch in detail
                    if mismatched_count == 1:
                        logger.error(
                            f"First mismatch at row {row_idx}: {error}\n"
                            f"Source row: {source_row}\n"
                            f"Target row: {target_row}\n"
                            f"Source types: {[type(v).__name__ for v in source_row]}\n"
                            f"Target types: {[type(v).__name__ for v in target_row]}\n"
                            f"Columns: {column_names}"
                        )
                    
                    # Limit number of mismatched rows reported
                    if mismatched_count >= 10:
                        comparison_report['mismatched_rows'].append({
                            'row_index': '...',
                            'error': f'... and {len(source_rows) - row_idx - 1} more mismatched rows'
                        })
                        break
            
            if mismatched_count > 0:
                source_db = QueryBuilder.get_db_type(self.source_connector)
                target_db = QueryBuilder.get_db_type(self.target_connector)
                db_context = " (Oracle ADW involved)" if (source_db == 'oracle' or target_db == 'oracle') else ""
                for mismatch in comparison_report['mismatched_rows'][:3]:
                    logger.error(
                        f"Mismatch details: {mismatch.get('error', 'Unknown error')}, "
                        f"row_index: {mismatch.get('row_index', 'unknown')}, "
                        f"source: {mismatch.get('source_row', 'N/A')}, "
                        f"target: {mismatch.get('target_row', 'N/A')}"
                    )
                error_msg = f"Found {mismatched_count} mismatched row(s){db_context}"
                return False, error_msg, comparison_report
            
            return True, None, comparison_report
            
        except Exception as e:
            source_db = QueryBuilder.get_db_type(self.source_connector)
            target_db = QueryBuilder.get_db_type(self.target_connector)
            db_context = " Oracle ADW:" if (source_db == 'oracle' or target_db == 'oracle') else " "
            error_msg = f"Error comparing rows:{db_context}{str(e)}"
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
                # Log detailed mismatch for debugging
                logger.warning(
                    f"Value mismatch in column '{col_name}': "
                    f"source={source_val!r} (type={type(source_val).__name__}), "
                    f"target={target_val!r} (type={type(target_val).__name__}), "
                    f"normalized_source={normalized_source!r}, normalized_target={normalized_target!r}"
                )
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
        
        # Keep Decimal for exact high-precision comparison (Oracle NUMBER, etc.)
        if isinstance(value, Decimal):
            return value
        
        # Normalize datetime to UTC for cross-DB comparison (Oracle TIMESTAMP WITH TIME ZONE, etc.)
        if isinstance(value, (datetime, date)):
            return _utc_normalize(value)
        
        return value
    
    def _values_equal(self, val1: Any, val2: Any) -> bool:
        """
        Compare two values for equality, handling type conversions and cross-DB differences.
        Oracle NUMBER, timestamps, and text are compared in a type-safe way.
        """
        # Handle NULL values
        if val1 is None and val2 is None:
            return True
        if val1 is None or val2 is None:
            return False
        
        # Exact Decimal comparison (Oracle NUMBER, high-precision numerics)
        if isinstance(val1, Decimal) and isinstance(val2, Decimal):
            return val1 == val2
        if isinstance(val1, Decimal) or isinstance(val2, Decimal):
            try:
                d1 = Decimal(str(val1)) if not isinstance(val1, Decimal) else val1
                d2 = Decimal(str(val2)) if not isinstance(val2, Decimal) else val2
                return d1 == d2
            except (ValueError, TypeError, ArithmeticError):
                pass
        
        # UTC-normalized datetime comparison (Oracle TIMESTAMP WITH TIME ZONE, etc.)
        n1, n2 = _utc_normalize(val1), _utc_normalize(val2)
        if n1 is not None and n2 is not None:
            return n1 == n2
        
        # Float/int with tolerance for non-Decimal numerics
        try:
            val1_num = None
            val2_num = None
            if isinstance(val1, (int, float)) or (isinstance(val1, str) and val1.replace('.', '', 1).replace('-', '', 1).replace('e', '', 1).replace('E', '', 1).isdigit()):
                try:
                    val1_num = float(val1)
                except (ValueError, TypeError):
                    pass
            if isinstance(val2, (int, float)) or (isinstance(val2, str) and val2.replace('.', '', 1).replace('-', '', 1).replace('e', '', 1).replace('E', '', 1).isdigit()):
                try:
                    val2_num = float(val2)
                except (ValueError, TypeError):
                    pass
            if val1_num is not None and val2_num is not None:
                return abs(val1_num - val2_num) < 0.0001
        except (ValueError, TypeError, AttributeError):
            pass
        
        if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            try:
                return abs(float(val1) - float(val2)) < 0.0001
            except Exception:
                return val1 == val2
        
        # Handle string types - normalize whitespace
        if isinstance(val1, str) and isinstance(val2, str):
            # Normalize whitespace for comparison
            val1_clean = val1.strip() if val1 else val1
            val2_clean = val2.strip() if val2 else val2
            if val1_clean == val2_clean:
                return True
            # Also try byte comparison (for binary strings)
            try:
                if val1.encode('utf-8') == val2.encode('utf-8'):
                    return True
            except:
                pass
        
        # Handle bytes types
        if isinstance(val1, bytes) and isinstance(val2, bytes):
            return val1 == val2
        
        # Convert bytes to string for comparison if one is string and other is bytes
        if isinstance(val1, bytes) and isinstance(val2, str):
            try:
                return val1.decode('utf-8') == val2
            except:
                return False
        if isinstance(val1, str) and isinstance(val2, bytes):
            try:
                return val1 == val2.decode('utf-8')
            except:
                return False
        
        # Handle datetime types
        if isinstance(val1, (datetime, date)) and isinstance(val2, (datetime, date)):
            return val1 == val2
        
        # Handle cross-type conversions (e.g., MySQL returns Decimal, PostgreSQL returns float)
        # Try converting both to strings and comparing
        try:
            str1 = str(val1).strip()
            str2 = str(val2).strip()
            if str1 == str2:
                return True
        except:
            pass
        
        # Default comparison
        return val1 == val2
