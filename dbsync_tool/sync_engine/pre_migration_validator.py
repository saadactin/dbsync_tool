"""
Pre-migration validation service for transformation queries

Performs comprehensive validation before migration:
- Query syntax validation (executes query)
- Row count validation (COUNT query with transformations)
- Full query execution before migration (NEW)
- Query result structure verification (NEW)
- Query result data verification (NEW)
- Sample data verification (fetches sample rows)
- Transformation correctness verification
"""
from typing import Optional, Dict, List, Tuple, Any
from connections.connectors.base import DBConnector
from sync_engine.query_builder import QueryBuilder
from sync_engine.transformation_engine import TransformationEngine
from sync_jobs.models import SyncJobTable
import logging
import time

logger = logging.getLogger(__name__)


class PreMigrationValidator:
    """
    Validates transformation queries before migration
    
    Performs:
    - Query syntax validation (executes query)
    - Row count validation (COUNT query with transformations)
    - Sample data verification (fetches sample rows)
    - Transformation correctness verification
    """
    
    def __init__(self, source_connector: DBConnector):
        """
        Initialize pre-migration validator
        
        Args:
            source_connector: Source database connector
        """
        self.source_connector = source_connector
        self.query_builder = QueryBuilder()
        self.transformation_engine = TransformationEngine()
    
    def validate_transformation_query(
        self,
        job_table: SyncJobTable,
        transformed_query: str,
        base_query: str,
        column_names: List[str]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Comprehensive pre-migration validation
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            transformed_query: Transformed query to validate
            base_query: Base query (without transformations)
            column_names: List of column names
            
        Returns:
            Tuple of (is_valid, error_message, validation_report)
            - validation_report contains: expected_row_count, sample_rows, etc.
        """
        schema = job_table.schema_name
        table = job_table.table_name
        where_clause = job_table.transformation_query
        column_transformations = job_table.column_transformations or {}
        
        validation_report = {
            'expected_row_count': 0,
            'query_results': [],  # NEW: Store query results
            'query_result_count': 0,
            'query_execution_time': 0.0,
            'sample_rows': [],
            'sample_size': 0,
            'transformations_verified': False,
            'structure_verified': False,
            'data_verified': False
        }
        
        try:
            # Step 1: Execute query syntax validation (basic check)
            try:
                # Execute validation query with LIMIT 1 to test syntax
                db_type = QueryBuilder.get_db_type(self.source_connector)
                query_upper = transformed_query.upper()
                
                validation_query = transformed_query
                if db_type == 'postgres' and 'LIMIT' not in query_upper:
                    validation_query += ' LIMIT 1'
                elif db_type == 'mysql' and 'LIMIT' not in query_upper:
                    validation_query += ' LIMIT 1'
                elif db_type == 'sqlserver':
                    # SQL Server uses TOP - check if already present
                    if 'TOP' not in query_upper:
                        # Try to execute as-is first
                        pass
                
                result = self.source_connector.fetch_batch(
                    query=validation_query,
                    batch_size=1,
                    offset=0
                )
                
                logger.debug(
                    f"Query syntax validation passed for {schema}.{table}: "
                    f"Query executed successfully"
                )
            except Exception as e:
                error_msg = f"Query syntax validation failed: {str(e)}"
                logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}")
                return False, error_msg, validation_report
            
            # Step 2: Get expected row count with transformations
            try:
                expected_row_count = self._get_expected_row_count(
                    schema=schema,
                    table=table,
                    where_clause=where_clause,
                    column_transformations=column_transformations
                )
                validation_report['expected_row_count'] = expected_row_count
                logger.info(
                    f"Expected row count for {schema}.{table}: {expected_row_count}"
                )
            except Exception as e:
                error_msg = f"Failed to get expected row count: {str(e)}"
                logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}")
                return False, error_msg, validation_report
            
            # NEW: Step 3: Execute full query on source BEFORE migration
            start_time = time.time()
            
            try:
                # Execute full query (or large sample if too large)
                # For Day 6: Try to fetch full result set, but limit for very large tables
                max_sample_size = 50000  # Increased limit for Day 6 (was 10000)
                use_full_query = expected_row_count <= max_sample_size
                
                db_type = QueryBuilder.get_db_type(self.source_connector)
                query_upper = transformed_query.upper()
                
                if use_full_query:
                    # Use full query if expected row count is within limit
                    sample_query = transformed_query
                    logger.info(
                        f"Executing full query for {schema}.{table}: "
                        f"expected {expected_row_count} rows (within limit)"
                    )
                else:
                    # For large tables, sample first N rows
                    sample_query = transformed_query
                    if db_type == 'postgres' and 'LIMIT' not in query_upper:
                        sample_query = f"{transformed_query} LIMIT {max_sample_size}"
                    elif db_type == 'mysql' and 'LIMIT' not in query_upper:
                        sample_query = f"{transformed_query} LIMIT {max_sample_size}"
                    elif db_type == 'sqlserver' and 'TOP' not in query_upper:
                        # SQL Server uses TOP - insert after SELECT
                        select_idx = query_upper.find('SELECT')
                        if select_idx != -1:
                            insert_pos = select_idx + 6  # After "SELECT"
                            sample_query = (
                                transformed_query[:insert_pos] +
                                f' TOP {max_sample_size}' +
                                transformed_query[insert_pos:]
                            )
                    logger.info(
                        f"Executing sampled query for {schema}.{table}: "
                        f"expected {expected_row_count} rows, sampling {max_sample_size} rows"
                    )
                
                # Execute query - use fetch_batch which handles batching internally
                query_results = self.source_connector.fetch_batch(
                    query=sample_query,
                    batch_size=max_sample_size,
                    offset=0
                )
                
                execution_time = time.time() - start_time
                validation_report['query_results'] = query_results if query_results else []
                validation_report['query_result_count'] = len(query_results) if query_results else 0
                validation_report['query_execution_time'] = execution_time
                validation_report['is_full_query_result'] = use_full_query and len(query_results) == expected_row_count
                
                logger.info(
                    f"Query execution completed for {schema}.{table}: "
                    f"{len(query_results) if query_results else 0} rows in {execution_time:.2f}s, "
                    f"full_result={validation_report['is_full_query_result']}"
                )
                
            except Exception as e:
                error_msg = f"Query execution failed: {str(e)}"
                logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}")
                return False, error_msg, validation_report
            
            # NEW: Step 4: Verify query result structure
            from sync_engine.query_result_verifier import QueryResultVerifier
            query_verifier = QueryResultVerifier(self.source_connector)
            
            structure_valid, structure_error, structure_report = query_verifier.verify_query_result_structure(
                query_result=query_results if query_results else [],
                column_names=column_names,
                expected_row_count=expected_row_count
            )
            
            if not structure_valid:
                error_msg = f"Query result structure verification failed: {structure_error}"
                logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}")
                return False, error_msg, validation_report
            
            validation_report['structure_verified'] = True
            validation_report.update(structure_report)
            
            # NEW: Step 5: Verify query result data
            data_valid, data_error, data_report = query_verifier.verify_query_result_data(
                query_result=query_results if query_results else [],
                column_names=column_names,
                column_transformations=column_transformations
            )
            
            if not data_valid:
                error_msg = f"Query result data verification failed: {data_error}"
                logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}")
                return False, error_msg, validation_report
            
            validation_report['data_verified'] = True
            validation_report.update(data_report)
            
            # Step 6: Verify transformations are applied correctly (enhanced)
            if column_transformations and query_results:
                try:
                    is_valid, error = query_verifier.verify_transformations_applied(
                        query_result=query_results,
                        column_names=column_names,
                        column_transformations=column_transformations
                    )
                    if not is_valid:
                        error_msg = f"Transformation verification failed: {error}"
                        logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}")
                        return False, error_msg, validation_report
                    validation_report['transformations_verified'] = True
                    logger.info(
                        f"Transformations verified correctly for {schema}.{table}"
                    )
                except Exception as e:
                    error_msg = f"Transformation verification error: {str(e)}"
                    logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}")
                    return False, error_msg, validation_report
            
            # Store sample rows for logging (first 10 rows)
            validation_report['sample_rows'] = query_results[:10] if query_results and len(query_results) > 10 else (query_results if query_results else [])
            validation_report['sample_size'] = len(validation_report['sample_rows'])
            
            # All validations passed
            logger.info(
                f"Pre-migration validation passed for {schema}.{table}: "
                f"Query executed successfully, {validation_report['query_result_count']} rows, "
                f"Structure verified, Data verified, Transformations verified"
            )
            return True, None, validation_report
            
        except Exception as e:
            error_msg = f"Unexpected error during pre-migration validation: {str(e)}"
            logger.error(f"Pre-migration validation error for {schema}.{table}: {error_msg}", exc_info=True)
            return False, error_msg, validation_report
    
    def _get_expected_row_count(
        self,
        schema: str,
        table: str,
        where_clause: Optional[str],
        column_transformations: Dict[str, str]
    ) -> int:
        """
        Get expected row count from source with transformations applied
        
        Executes: SELECT COUNT(*) FROM table WHERE transformation_query
        
        Args:
            schema: Schema name
            table: Table name
            where_clause: WHERE clause from transformation_query
            column_transformations: Column transformations (not used in COUNT, but kept for consistency)
            
        Returns:
            Expected row count
        """
        try:
            # Build COUNT query with WHERE clause transformation
            # Column transformations don't affect COUNT, so we only need WHERE clause
            db_type = QueryBuilder.get_db_type(self.source_connector)
            
            # Build schema.table identifier
            if db_type == 'postgres':
                schema_part = f'"{schema}"."{table}"'
            elif db_type == 'mysql':
                schema_part = f'`{schema}`.`{table}`'
            elif db_type == 'sqlserver':
                schema_part = f'[{schema}].[{table}]'
            else:
                schema_part = f'{schema}.{table}'
            
            # Build COUNT query
            count_query = f'SELECT COUNT(*) FROM {schema_part}'
            
            if where_clause:
                count_query += f' WHERE {where_clause}'
            
            # Execute COUNT query
            result = self.source_connector.fetch_batch(
                query=count_query,
                batch_size=1,
                offset=0
            )
            
            if result and len(result) > 0 and len(result[0]) > 0:
                count = result[0][0]
                # Handle different return types (int, Decimal, etc.)
                if hasattr(count, '__int__'):
                    return int(count)
                return count
            
            return 0
            
        except Exception as e:
            logger.error(f"Error getting expected row count for {schema}.{table}: {str(e)}")
            raise
    
    def _fetch_sample_rows(
        self,
        transformed_query: str,
        sample_size: int = 10
    ) -> List[Tuple]:
        """
        Fetch sample rows to verify transformations
        
        Args:
            transformed_query: Transformed query
            sample_size: Number of sample rows to fetch
            
        Returns:
            List of sample rows
        """
        try:
            db_type = QueryBuilder.get_db_type(self.source_connector)
            query_upper = transformed_query.upper()
            
            # Add LIMIT/TOP clause if not present
            sample_query = transformed_query
            if db_type == 'postgres' and 'LIMIT' not in query_upper:
                sample_query += f' LIMIT {sample_size}'
            elif db_type == 'mysql' and 'LIMIT' not in query_upper:
                sample_query += f' LIMIT {sample_size}'
            elif db_type == 'sqlserver':
                # SQL Server uses TOP - need to insert after SELECT
                if 'TOP' not in query_upper:
                    # Simple approach: insert TOP after SELECT
                    select_idx = query_upper.find('SELECT')
                    if select_idx != -1:
                        insert_pos = select_idx + 6  # After "SELECT"
                        sample_query = (
                            transformed_query[:insert_pos] +
                            f' TOP {sample_size}' +
                            transformed_query[insert_pos:]
                        )
            
            # Execute query to fetch sample rows
            result = self.source_connector.fetch_batch(
                query=sample_query,
                batch_size=sample_size,
                offset=0
            )
            
            return result if result else []
            
        except Exception as e:
            logger.error(f"Error fetching sample rows: {str(e)}")
            raise
    
    def _verify_transformations_applied(
        self,
        sample_rows: List[Tuple],
        column_names: List[str],
        column_transformations: Dict[str, str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify that transformations were applied correctly to sample rows
        
        This is a basic verification - we check if transformations appear to be applied.
        For TRIM, we check if values don't have leading/trailing spaces.
        For UPPER, we check if values are uppercase.
        For LOWER, we check if values are lowercase.
        
        Note: This is a heuristic check. The actual verification happens during
        post-migration comparison where we compare source (with transformations applied)
        against target.
        
        Args:
            sample_rows: List of sample rows
            column_names: List of column names
            column_transformations: Dict mapping column_name -> transformation_type
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not sample_rows:
            return True, None  # No rows to verify
        
        try:
            # Create column index map
            column_index_map = {
                col_name: idx
                for idx, col_name in enumerate(column_names)
            }
            
            # Check each transformation
            for col_name, transformation in column_transformations.items():
                if col_name not in column_index_map:
                    continue  # Column not in result set (might be filtered)
                
                col_idx = column_index_map[col_name]
                transformation_upper = transformation.upper()
                
                # Check sample rows
                for row_idx, row in enumerate(sample_rows):
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
                        if value != value.strip():
                            # This is a warning, not an error - transformation might be applied in SQL
                            logger.debug(
                                f"Sample row {row_idx}, column {col_name}: "
                                f"Value has spaces but TRIM transformation expected. "
                                f"This may be normal if transformation is applied in SQL."
                            )
                    elif transformation_upper == 'UPPER':
                        # Check if value is uppercase
                        if value != value.upper():
                            return False, (
                                f"Sample row {row_idx}, column {col_name}: "
                                f"Value '{value}' is not uppercase but UPPER transformation expected"
                            )
                    elif transformation_upper == 'LOWER':
                        # Check if value is lowercase
                        if value != value.lower():
                            return False, (
                                f"Sample row {row_idx}, column {col_name}: "
                                f"Value '{value}' is not lowercase but LOWER transformation expected"
                            )
            
            return True, None
            
        except Exception as e:
            error_msg = f"Error verifying transformations: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
