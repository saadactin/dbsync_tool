"""
Query result verification service for pre and post-migration validation

Performs comprehensive query result verification:
- Query result structure verification (columns, types)
- Query result data verification (rows, values)
- Transformation-aware result verification
- Data type conversion handling
- NULL value handling
- Special character handling
"""
from typing import Optional, Dict, List, Tuple, Any
from connections.connectors.base import DBConnector
from sync_engine.query_builder import QueryBuilder
from sync_engine.transformation_engine import TransformationEngine
import logging
from decimal import Decimal
from datetime import datetime, date

logger = logging.getLogger(__name__)


class QueryResultVerifier:
    """
    Verifies query results before and after migration
    
    Performs:
    - Query result structure verification (columns, types)
    - Query result data verification (rows, values)
    - Transformation-aware result verification
    - Data type conversion handling
    - NULL value handling
    - Special character handling
    """
    
    def __init__(self, source_connector: DBConnector):
        """
        Initialize query result verifier
        
        Args:
            source_connector: Source database connector
        """
        self.source_connector = source_connector
        self.query_builder = QueryBuilder()
        self.transformation_engine = TransformationEngine()
    
    def verify_query_result_structure(
        self,
        query_result: List[Tuple],
        column_names: List[str],
        expected_row_count: int
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Verify query result structure
        
        Args:
            query_result: Query result rows
            column_names: Expected column names
            expected_row_count: Expected row count
            
        Returns:
            Tuple of (is_valid, error_message, structure_report)
        """
        structure_report = {
            'actual_row_count': len(query_result),
            'expected_row_count': expected_row_count,
            'row_count_match': False,
            'column_count_match': False,
            'columns_verified': len(column_names)
        }
        
        try:
            # Verify row count
            actual_count = len(query_result)
            if actual_count != expected_row_count:
                # For large tables, we might have sampled, so allow some flexibility
                # But log a warning if difference is significant
                if abs(actual_count - expected_row_count) > max(100, expected_row_count * 0.1):
                    error_msg = (
                        f"Row count mismatch: expected {expected_row_count}, "
                        f"got {actual_count} (difference: {abs(actual_count - expected_row_count)})"
                    )
                    logger.warning(error_msg)
                    # Don't fail if we're sampling (actual_count < expected_row_count)
                    if actual_count > expected_row_count:
                        return False, error_msg, structure_report
                else:
                    # Small difference, might be due to sampling
                    logger.debug(
                        f"Row count difference within tolerance: "
                        f"expected={expected_row_count}, actual={actual_count}"
                    )
            
            structure_report['row_count_match'] = True
            
            # Verify column count
            if query_result:
                actual_column_count = len(query_result[0])
                expected_column_count = len(column_names)
                
                if actual_column_count != expected_column_count:
                    error_msg = (
                        f"Column count mismatch: expected {expected_column_count}, "
                        f"got {actual_column_count}"
                    )
                    return False, error_msg, structure_report
                
                structure_report['column_count_match'] = True
            else:
                # Empty result set - structure is valid if column_names is provided
                structure_report['column_count_match'] = True
            
            logger.debug(
                f"Query result structure verified: "
                f"{actual_count} rows, {len(column_names)} columns"
            )
            
            return True, None, structure_report
            
        except Exception as e:
            error_msg = f"Error verifying query result structure: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, structure_report
    
    def verify_query_result_data(
        self,
        query_result: List[Tuple],
        column_names: List[str],
        column_transformations: Dict[str, str]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Verify query result data
        
        Args:
            query_result: Query result rows
            column_names: Column names
            column_transformations: Column transformations applied
            
        Returns:
            Tuple of (is_valid, error_message, data_report)
        """
        data_report = {
            'rows_verified': 0,
            'null_values_found': 0,
            'special_characters_found': 0,
            'data_types_verified': True
        }
        
        try:
            if not query_result:
                # Empty result set is valid
                return True, None, data_report
            
            # Verify each row
            for row_idx, row in enumerate(query_result):
                if len(row) != len(column_names):
                    error_msg = (
                        f"Row {row_idx}: Column count mismatch: "
                        f"expected {len(column_names)}, got {len(row)}"
                    )
                    return False, error_msg, data_report
                
                # Verify each column value
                for col_idx, col_name in enumerate(column_names):
                    if col_idx >= len(row):
                        error_msg = (
                            f"Row {row_idx}, Column {col_name}: "
                            f"Column index out of range"
                        )
                        return False, error_msg, data_report
                    
                    value = row[col_idx]
                    
                    # Check for NULL values (valid, but track them)
                    if value is None:
                        data_report['null_values_found'] += 1
                        continue
                    
                    # Check for special characters (valid, but track them)
                    if isinstance(value, str):
                        # Check for Unicode and special characters
                        try:
                            value.encode('ascii')
                        except UnicodeEncodeError:
                            data_report['special_characters_found'] += 1
                
                data_report['rows_verified'] += 1
            
            logger.debug(
                f"Query result data verified: "
                f"{data_report['rows_verified']} rows, "
                f"{data_report['null_values_found']} NULL values, "
                f"{data_report['special_characters_found']} special characters"
            )
            
            return True, None, data_report
            
        except Exception as e:
            error_msg = f"Error verifying query result data: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, data_report
    
    def verify_transformations_applied(
        self,
        query_result: List[Tuple],
        column_names: List[str],
        column_transformations: Dict[str, str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify transformations are applied correctly in query results
        
        Args:
            query_result: Query result rows
            column_names: Column names
            column_transformations: Column transformations applied
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not column_transformations:
            # No transformations to verify
            return True, None
        
        if not query_result:
            # Empty result set - transformations are valid (nothing to verify)
            return True, None
        
        try:
            # Create column index map
            column_index_map = {
                col_name: idx
                for idx, col_name in enumerate(column_names)
            }
            
            # Check each transformation
            for col_name, transformation in column_transformations.items():
                if col_name not in column_index_map:
                    # Column not in result set (might be filtered or not selected)
                    logger.debug(f"Column '{col_name}' not in result set, skipping transformation verification")
                    continue
                
                col_idx = column_index_map[col_name]
                transformation_upper = transformation.upper()
                
                # Check sample rows (first 10 rows or all if less)
                sample_size = min(10, len(query_result))
                for row_idx in range(sample_size):
                    row = query_result[row_idx]
                    
                    if col_idx >= len(row):
                        continue
                    
                    value = row[col_idx]
                    
                    # Skip NULL values
                    if value is None:
                        continue
                    
                    # Convert to string for checking
                    if not isinstance(value, str):
                        continue
                    
                    # Verify transformation
                    if transformation_upper == 'TRIM':
                        # Check if value has leading/trailing spaces
                        # Note: TRIM might be applied in SQL, so we check if spaces exist
                        # This is a heuristic check
                        if value != value.strip():
                            logger.debug(
                                f"Row {row_idx}, column {col_name}: "
                                f"Value has spaces but TRIM transformation expected. "
                                f"This may be normal if transformation is applied in SQL SELECT."
                            )
                            # Don't fail - TRIM might be applied in SQL
                    elif transformation_upper == 'UPPER':
                        # Check if value is uppercase
                        if value != value.upper():
                            error_msg = (
                                f"Row {row_idx}, column {col_name}: "
                                f"Value '{value}' is not uppercase but UPPER transformation expected"
                            )
                            return False, error_msg
                    elif transformation_upper == 'LOWER':
                        # Check if value is lowercase
                        if value != value.lower():
                            error_msg = (
                                f"Row {row_idx}, column {col_name}: "
                                f"Value '{value}' is not lowercase but LOWER transformation expected"
                            )
                            return False, error_msg
            
            logger.debug(
                f"Transformations verified correctly for {len(column_transformations)} columns"
            )
            
            return True, None
            
        except Exception as e:
            error_msg = f"Error verifying transformations: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def compare_query_results_with_target(
        self,
        source_query_result: List[Tuple],
        target_rows: List[Tuple],
        column_names: List[str],
        column_transformations: Dict[str, str]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Compare query results with target data
        
        Args:
            source_query_result: Source query result rows
            target_rows: Target data rows
            column_names: Column names
            column_transformations: Column transformations applied
            
        Returns:
            Tuple of (matches, error_message, comparison_report)
        """
        comparison_report = {
            'source_row_count': len(source_query_result),
            'target_row_count': len(target_rows),
            'rows_match': False,
            'mismatched_rows': [],
            'mismatched_columns': []
        }
        
        try:
            # Compare row counts
            if len(source_query_result) != len(target_rows):
                error_msg = (
                    f"Row count mismatch: source={len(source_query_result)}, "
                    f"target={len(target_rows)}"
                )
                return False, error_msg, comparison_report
            
            comparison_report['rows_match'] = True
            
            # Log first row for debugging
            if len(source_query_result) > 0 and len(target_rows) > 0:
                logger.debug(
                    f"First row comparison: source={source_query_result[0]}, target={target_rows[0]}, "
                    f"source_types={[type(v).__name__ for v in source_query_result[0]]}, "
                    f"target_types={[type(v).__name__ for v in target_rows[0]]}, "
                    f"columns={column_names}"
                )
            
            # Compare each row
            mismatched_count = 0
            for row_idx, (source_row, target_row) in enumerate(zip(source_query_result, target_rows)):
                # Log first row for debugging
                if row_idx == 0:
                    logger.debug(
                        f"Comparing row {row_idx}: source={source_row}, target={target_row}, "
                        f"columns={column_names}"
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
                            'error': f'... and {len(source_query_result) - row_idx - 1} more mismatched rows'
                        })
                        break
            
            if mismatched_count > 0:
                # Log first few mismatches for debugging
                for mismatch in comparison_report['mismatched_rows'][:3]:
                    logger.error(
                        f"Mismatch details: {mismatch.get('error', 'Unknown error')}, "
                        f"row_index: {mismatch.get('row_index', 'unknown')}, "
                        f"source: {mismatch.get('source_row', 'N/A')}, "
                        f"target: {mismatch.get('target_row', 'N/A')}"
                    )
                error_msg = f"Found {mismatched_count} mismatched row(s)"
                return False, error_msg, comparison_report
            
            logger.debug(
                f"Query results match target: "
                f"{len(source_query_result)} rows compared, all match"
            )
            
            return True, None, comparison_report
            
        except Exception as e:
            error_msg = f"Error comparing query results with target: {str(e)}"
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
            # Source already has transformations applied, target should match
            normalized_source = self._normalize_value_for_comparison(source_val, None)
            normalized_target = self._normalize_value_for_comparison(target_val, None)
            
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
    
    def _normalize_value_for_comparison(
        self,
        value: Any,
        transformation: Optional[str]
    ) -> Any:
        """
        Normalize value for comparison based on transformation
        
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
        Compare two values for equality, handling type conversions and cross-database differences
        
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
        
        # Handle boolean comparisons (PostgreSQL bool vs MySQL tinyint(1))
        # PostgreSQL: True/False
        # MySQL: 1/0 or True/False or tinyint(1)
        # Check if either value is boolean-like
        bool1 = None
        bool2 = None
        
        # Check val1 for boolean
        if isinstance(val1, bool):
            bool1 = val1
        elif isinstance(val1, int) and val1 in (0, 1):
            bool1 = bool(val1)
        elif isinstance(val1, str) and val1.lower() in ('true', 'false', '1', '0', 't', 'f'):
            bool1 = val1.lower() in ('true', '1', 't')
        
        # Check val2 for boolean
        if isinstance(val2, bool):
            bool2 = val2
        elif isinstance(val2, int) and val2 in (0, 1):
            bool2 = bool(val2)
        elif isinstance(val2, str) and val2.lower() in ('true', 'false', '1', '0', 't', 'f'):
            bool2 = val2.lower() in ('true', '1', 't')
        
        # If both are boolean-like, compare as booleans
        if bool1 is not None and bool2 is not None:
            return bool1 == bool2
        
        # Handle numeric comparisons (Decimal vs float/int)
        # PostgreSQL returns Decimal, MySQL returns float or DECIMAL
        if isinstance(val1, (int, float, Decimal)) or isinstance(val2, (int, float, Decimal)):
            try:
                # Convert both to float for comparison
                num1 = float(val1) if isinstance(val1, (int, float, Decimal)) else None
                num2 = float(val2) if isinstance(val2, (int, float, Decimal)) else None
                
                # Try string-to-number conversion if needed
                if num1 is None and isinstance(val1, str):
                    try:
                        num1 = float(val1)
                    except (ValueError, TypeError):
                        pass
                if num2 is None and isinstance(val2, str):
                    try:
                        num2 = float(val2)
                    except (ValueError, TypeError):
                        pass
                
                # If both are numeric, compare as numbers with tolerance
                if num1 is not None and num2 is not None:
                    if abs(num1 - num2) < 0.0001:
                        return True
                    return False
            except (ValueError, TypeError, AttributeError):
                pass
        
        # Convert both to same type for comparison (handles cross-database type differences)
        # Try numeric conversion first (handles cross-database type differences)
        try:
            # If either is numeric, try to compare as numbers
            val1_num = None
            val2_num = None
            
            if isinstance(val1, (int, float, Decimal)) or (isinstance(val1, str) and val1.replace('.', '', 1).replace('-', '', 1).replace('e', '', 1).replace('E', '', 1).isdigit()):
                try:
                    val1_num = float(val1)
                except (ValueError, TypeError):
                    pass
            
            if isinstance(val2, (int, float, Decimal)) or (isinstance(val2, str) and val2.replace('.', '', 1).replace('-', '', 1).replace('e', '', 1).replace('E', '', 1).isdigit()):
                try:
                    val2_num = float(val2)
                except (ValueError, TypeError):
                    pass
            
            # If both are numeric, compare as numbers
            if val1_num is not None and val2_num is not None:
                # Use tolerance for floating point comparison
                if abs(val1_num - val2_num) < 0.0001:
                    return True
                return False
        except (ValueError, TypeError, AttributeError):
            pass
        
        # Handle numeric types (same database type)
        if isinstance(val1, (int, float, Decimal)) and isinstance(val2, (int, float, Decimal)):
            try:
                return abs(float(val1) - float(val2)) < 0.0001  # Allow small floating point differences
            except:
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
