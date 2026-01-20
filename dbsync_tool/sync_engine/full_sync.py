"""
Full sync implementation
"""
from typing import List, Optional, Tuple, Dict, Any
from django.utils import timezone
from django.db.models import Sum
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import DBConnector
from sync_engine.table_handler import TableHandler
from sync_engine.validators import DataValidator
from sync_engine.query_builder import QueryBuilder
from sync_engine.transformation_engine import TransformationEngine
from sync_engine.transformation_validator import TransformationValidator
from sync_engine.exceptions import TableSyncError
from core.constants import DEFAULT_BATCH_SIZE, MAX_BATCH_SIZE, MIN_BATCH_SIZE
import logging

logger = logging.getLogger(__name__)

class FullSyncExecutor:
    """Executes full sync for a job"""
    
    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        source_connector: DBConnector,
        target_connector: DBConnector
    ):
        """
        Initialize full sync executor
        
        Args:
            job: SyncJob instance
            execution: SyncExecution instance
            source_connector: Source database connector
            target_connector: Target database connector
        """
        self.job = job
        self.execution = execution
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.table_handler = TableHandler(source_connector, target_connector)
        self.validator = DataValidator()
        # Optimize batch size based on database types
        self.batch_size = self._optimize_batch_size()
        self.query_builder = QueryBuilder()
        # Initialize transformation engine and validator
        self.transformation_engine = TransformationEngine()
        self.transformation_validator = TransformationValidator()
        # NEW: Initialize pre-migration validator and data integrity verifier
        from sync_engine.pre_migration_validator import PreMigrationValidator
        from sync_engine.data_integrity_verifier import DataIntegrityVerifier
        
        self.pre_migration_validator = PreMigrationValidator(source_connector)
        self.data_integrity_verifier = DataIntegrityVerifier(
            source_connector,
            target_connector
        )
    
    def _optimize_batch_size(self):
        """
        Optimize batch size based on source and target database types
        
        Returns:
            int: Optimized batch size
        """
        source_type = self._get_db_type(self.source_connector)
        target_type = self._get_db_type(self.target_connector)
        
        # Different databases have different optimal batch sizes
        # PostgreSQL can handle larger batches
        # MySQL and SQL Server may need smaller batches
        if source_type == 'postgres' and target_type == 'postgres':
            return min(MAX_BATCH_SIZE, DEFAULT_BATCH_SIZE * 2)  # 10000
        elif source_type == 'mysql' or target_type == 'mysql':
            return min(DEFAULT_BATCH_SIZE, 3000)  # Smaller for MySQL
        elif source_type == 'sqlserver' or target_type == 'sqlserver':
            return min(DEFAULT_BATCH_SIZE, 2000)  # Smaller for SQL Server
        else:
            return DEFAULT_BATCH_SIZE
    
    def _get_db_type(self, connector):
        """Extract database type from connector"""
        class_name = connector.__class__.__name__
        if 'Postgres' in class_name:
            return 'postgres'
        elif 'MySQL' in class_name:
            return 'mysql'
        elif 'SQLServer' in class_name:
            return 'sqlserver'
        else:
            return 'unknown'
    
    def _validate_and_apply_transformations(
        self,
        job_table: SyncJobTable,
        base_query: str,
        column_names: List[str]
    ) -> Tuple[str, Optional[str]]:
        """
        Validate and apply transformations to query
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            base_query: Base SELECT query (without transformations)
            column_names: List of column names
            
        Returns:
            Tuple of (transformed_query, error_message)
            - If error_message is not None, validation failed
            - If error_message is None, transformed_query is ready to use
        """
        # Read transformation fields
        where_clause = job_table.transformation_query
        column_transformations = job_table.column_transformations or {}
        
        # If no transformations, return base query
        if not where_clause and not column_transformations:
            return base_query, None
        
        # Validate transformations
        schema = job_table.schema_name
        table = job_table.table_name
        
        # Validate WHERE clause
        if where_clause:
            is_valid, error = self.transformation_validator.validate_where_clause(
                where_clause=where_clause,
                schema=schema,
                table=table,
                connector=self.source_connector
            )
            if not is_valid:
                return None, f"WHERE clause validation failed: {error}"
        
        # Validate column transformations
        if column_transformations:
            is_valid, error = self.transformation_validator.validate_column_transformations(
                transformations=column_transformations,
                schema=schema,
                table=table,
                connector=self.source_connector
            )
            if not is_valid:
                return None, f"Column transformation validation failed: {error}"
        
        # Apply transformations to query
        try:
            transformed_query = self.transformation_engine.apply_query_transformations(
                query=base_query,
                where_clause=where_clause,
                column_transformations=column_transformations,
                connector=self.source_connector
            )
            return transformed_query, None
        except Exception as e:
            return None, f"Failed to apply transformations: {str(e)}"
    
    def _execute_pre_migration_validation(
        self,
        job_table: SyncJobTable,
        transformed_query: str,
        base_query: str,
        column_names: List[str]
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Enhanced pre-migration validation with comprehensive checks
        
        Args:
            job_table: SyncJobTable instance
            transformed_query: Transformed query to validate
            base_query: Base query (without transformations)
            column_names: List of column names
            
        Returns:
            Tuple of (is_valid, error_message, validation_report)
        """
        # Only run enhanced validation if transformations are present
        if not job_table.transformation_query and not job_table.column_transformations:
            # No transformations, skip enhanced validation
            return True, None, None
        
        # Use PreMigrationValidator for comprehensive validation
        is_valid, error_msg, validation_report = self.pre_migration_validator.validate_transformation_query(
            job_table=job_table,
            transformed_query=transformed_query,
            base_query=base_query,
            column_names=column_names
        )
        
        if not is_valid:
            logger.error(
                f"Pre-migration validation failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
            )
            return False, error_msg, None
        
        logger.info(
            f"Pre-migration validation passed for {job_table.schema_name}.{job_table.table_name}: "
            f"Expected {validation_report.get('expected_row_count', 0)} rows, "
            f"Query executed: {validation_report.get('query_result_count', 0)} rows in "
            f"{validation_report.get('query_execution_time', 0.0):.2f}s, "
            f"Structure verified: {validation_report.get('structure_verified', False)}, "
            f"Data verified: {validation_report.get('data_verified', False)}"
        )
        
        return True, None, validation_report
    
    def execute(self):
        """Execute full sync for all enabled tables"""
        try:
            # Update execution status
            self.execution.status = 'running'
            self.execution.started_at = timezone.now()
            self.execution.save()
            
            # Get enabled tables
            tables = self.job.tables.filter(is_enabled=True)
            
            if not tables.exists():
                logger.warning(f"No enabled tables found for job {self.job.id}")
                self.execution.status = 'completed'
                self.execution.completed_at = timezone.now()
                self.execution.save()
                return
            
            # Connect to databases (connections are managed efficiently)
            # Connections are opened once and reused for all tables
            if not hasattr(self.source_connector, '_connected') or not self.source_connector._connected:
                self.source_connector.connect()
                self.source_connector._connected = True
            
            if not hasattr(self.target_connector, '_connected') or not self.target_connector._connected:
                self.target_connector.connect()
                self.target_connector._connected = True
            
            # Sync each table
            for job_table in tables:
                try:
                    self.sync_table(job_table)
                except TableSyncError as e:
                    logger.error(f"Table sync failed: {str(e)}")
                    # Continue with other tables
                    continue
                except Exception as e:
                    logger.error(
                        f"Unexpected error syncing table: {str(e)}",
                        exc_info=True
                    )
                    # Continue with other tables
                    continue
            
            # Final status update
            completed_logs = SyncExecutionLog.objects.filter(
                execution=self.execution,
                status='completed'
            )
            failed_logs = SyncExecutionLog.objects.filter(
                execution=self.execution,
                status='failed'
            )
            total_logs = completed_logs.count() + failed_logs.count()
            
            # Determine execution status
            if failed_logs.count() == total_logs and total_logs > 0:
                # ALL tables failed
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"All {failed_logs.count()} table(s) failed to sync"
                )
            elif failed_logs.exists():
                # SOME tables failed (partial failure)
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"{failed_logs.count()} of {total_logs} table(s) failed to sync"
                )
            elif completed_logs.count() == total_logs and total_logs > 0:
                # ALL tables succeeded
                self.execution.status = 'completed'
            else:
                # No logs created (shouldn't happen, but handle gracefully)
                self.execution.status = 'failed'
                self.execution.error_message = "No tables were processed"
            
            self.execution.completed_at = timezone.now()
            self.execution.save()
            
            logger.info(
                f"Full sync execution {self.execution.id} completed: "
                f"{completed_logs.count()}/{tables.count()} tables synced"
            )
            
        except Exception as e:
            logger.error(
                f"Full sync execution failed: {str(e)}",
                exc_info=True
            )
            self.execution.status = 'failed'
            self.execution.error_message = str(e)
            self.execution.completed_at = timezone.now()
            self.execution.save()
            raise
    
    def sync_table(self, job_table: SyncJobTable):
        """
        Sync a single table using full sync
        
        Steps:
        1. Create execution log entry
        2. Ensure target table exists (create if not)
        3. Truncate target table
        4. Get primary key for ordering
        5. Build source query
        6. Fetch batches from source
        7. Insert batches into target
        8. Update execution log
        """
        schema = job_table.schema_name
        table = job_table.table_name
        
        # Determine target schema
        # For MySQL targets with PostgreSQL/SQL Server sources: use target database name
        # For PostgreSQL targets with SQL Server sources: map dbo to public
        target_schema = schema
        if self.table_handler.target_db_type == 'mysql' and self.table_handler.source_db_type in ['postgres', 'sqlserver']:
            # Use the target database name instead of PostgreSQL schema
            target_schema = self.target_connector.database_name
            logger.info(f"Using target schema '{target_schema}' for source schema '{schema}'")
        elif self.table_handler.target_db_type == 'postgres' and self.table_handler.source_db_type == 'sqlserver':
            # Map SQL Server 'dbo' schema to PostgreSQL 'public' schema
            if schema.lower() == 'dbo':
                target_schema = 'public'
                logger.info(f"Mapping SQL Server schema 'dbo' to PostgreSQL schema 'public'")
        
        # Create execution log
        log = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name=schema,
            table_name=table,
            status='pending'
        )
        
        try:
            log.status = 'running'
            log.started_at = timezone.now()
            log.save()
            
            # Ensure target table exists (uses correct schema mapping internally)
            try:
                self.table_handler.create_table_if_not_exists(schema, table)
            except Exception as e:
                error_msg = f"Failed to create/verify target table: {str(e)}"
                logger.error(f"Table creation error for {schema}.{table}: {error_msg}", exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Truncate target table (use target_schema for MySQL)
            try:
                self.target_connector.truncate_table(target_schema, table)
            except Exception as e:
                error_msg = f"Failed to truncate target table: {str(e)}"
                logger.error(f"Table truncate error for {schema}.{table}: {error_msg}", exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Get primary key for ordering
            try:
                pk_columns = self.source_connector.get_primary_key(schema, table)
                if pk_columns:
                    order_by = ', '.join(pk_columns)
                else:
                    # Fallback to first column
                    columns = self.source_connector.get_columns(schema, table)
                    if columns:
                        order_by = columns[0].name
                    else:
                        order_by = None
            except Exception as e:
                logger.warning(f"Could not determine primary key for {schema}.{table}: {str(e)}")
                order_by = None
            
            # Get column names
            try:
                columns = self.source_connector.get_columns(schema, table)
                if not columns:
                    raise TableSyncError(f"No columns found for source table {schema}.{table}")
                column_names = [col.name for col in columns]
            except Exception as e:
                error_msg = f"Failed to get columns from source table {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Build source query
            try:
                base_query = self.query_builder.build_select_query(
                    connector=self.source_connector,
                    schema=schema,
                    table=table,
                    columns=column_names,
                    order_by=order_by
                )
            except Exception as e:
                error_msg = f"Failed to build query for {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Validate and apply transformations
            transformed_query, transformation_error = self._validate_and_apply_transformations(
                job_table=job_table,
                base_query=base_query,
                column_names=column_names
            )
            
            if transformation_error:
                error_msg = f"Transformation validation failed for {schema}.{table}: {transformation_error}"
                logger.error(error_msg)
                raise TableSyncError(error_msg)
            
            # NEW: Enhanced pre-migration validation
            validation_passed, validation_error, validation_report = self._execute_pre_migration_validation(
                job_table=job_table,
                transformed_query=transformed_query,
                base_query=base_query,
                column_names=column_names
            )
            
            if not validation_passed:
                error_msg = f"Pre-migration validation failed for {schema}.{table}: {validation_error}"
                logger.error(error_msg)
                raise TableSyncError(error_msg)
            
            # Store expected row count and query results for post-migration verification
            expected_row_count = validation_report.get('expected_row_count', 0) if validation_report else None
            pre_migration_query_results = validation_report.get('query_results', []) if validation_report else None
            
            # Use transformed_query instead of base_query for fetching
            query = transformed_query
            
            # Fetch and insert in batches
            offset = 0
            batch_number = 0
            total_rows_fetched = 0
            total_rows_inserted = 0
            
            while True:
                # Fetch batch
                batch = self.source_connector.fetch_batch(
                    query=query,
                    batch_size=self.batch_size,
                    offset=offset,
                    order_by=order_by
                )
                
                if not batch:
                    break  # No more rows
                
                batch_number += 1
                total_rows_fetched += len(batch)
                
                # Validate batch
                self.validator.validate_batch_not_empty(batch, f"{schema}.{table}")
                
                # Apply row transformations if column transformations were applied
                # (This is a fallback for transformations that couldn't be applied in SQL)
                column_transformations = job_table.column_transformations or {}
                if column_transformations:
                    batch = self.transformation_engine.apply_row_transformations(
                        batch=batch,
                        column_names=column_names,
                        column_transformations=column_transformations
                    )
                
                # Insert batch (use target_schema for MySQL)
                try:
                    self.target_connector.bulk_insert(
                        schema=target_schema,
                        table=table,
                        columns=column_names,
                        rows=batch
                    )
                    total_rows_inserted += len(batch)
                except Exception as e:
                    raise TableSyncError(
                        f"Failed to insert batch {batch_number} for {schema}.{table}: {str(e)}"
                    )
                
                # Update log
                log.batch_number = batch_number
                log.rows_fetched = total_rows_fetched
                log.rows_inserted = total_rows_inserted
                log.save()
                
                # Update execution progress
                self.execution.completed_tables = SyncExecutionLog.objects.filter(
                    execution=self.execution,
                    status='completed'
                ).count()
                self.execution.total_rows_synced = SyncExecutionLog.objects.filter(
                    execution=self.execution
                ).aggregate(total=Sum('rows_inserted'))['total'] or 0
                self.execution.save()
                
                offset += self.batch_size
                
                # Check if we got fewer rows than batch size (last batch)
                if len(batch) < self.batch_size:
                    break
            
            # NEW: Post-migration data accuracy verification
            if job_table.transformation_query or job_table.column_transformations:
                # Only verify if transformations were applied
                if expected_row_count is not None:
                    is_accurate, accuracy_error, accuracy_report = self._verify_post_migration_accuracy(
                        job_table=job_table,
                        source_schema=schema,
                        target_schema=target_schema,
                        expected_row_count=expected_row_count,
                        column_names=column_names,
                        pre_migration_query_results=pre_migration_query_results  # NEW
                    )
                    
                    if not is_accurate:
                        # Rollback: truncate target table
                        try:
                            self.target_connector.truncate_table(target_schema, table)
                            logger.warning(f"Rolled back target table {target_schema}.{table} due to accuracy verification failure")
                        except Exception as rollback_error:
                            logger.error(f"Failed to rollback target table: {str(rollback_error)}")
                        
                        error_msg = f"Post-migration verification failed for {schema}.{table}: {accuracy_error}"
                        logger.error(error_msg)
                        raise TableSyncError(error_msg)
                    
                    # Log perfect accuracy success
                    if accuracy_report.get('perfect_accuracy', False):
                        logger.info(
                            f"Perfect migration completed for {schema}.{table}: "
                            f"Zero data loss, zero inaccuracy, 100% accuracy verified"
                        )
            
            # Mark log as completed
            log.status = 'completed'
            log.completed_at = timezone.now()
            log.save()
            
            logger.info(
                f"Successfully synced table {schema}.{table}: "
                f"{total_rows_inserted} rows in {batch_number} batches"
            )
            
        except Exception as e:
            # Capture full error details including traceback
            import traceback
            error_details = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            
            log.status = 'failed'
            log.error_message = error_details[:5000]  # Limit to 5000 chars for database field
            log.completed_at = timezone.now()
            log.save()
            
            logger.error(
                f"Failed to sync table {schema}.{table}: {str(e)}",
                exc_info=True
            )
            raise TableSyncError(f"Table sync failed for {schema}.{table}: {str(e)}") from e
    
    def _verify_post_migration_accuracy(
        self,
        job_table: SyncJobTable,
        source_schema: str,
        target_schema: str,
        expected_row_count: int,
        column_names: List[str],
        pre_migration_query_results: Optional[List[Tuple]] = None
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Enhanced post-migration data accuracy verification with perfect accuracy checks
        
        NEW: Compares stored pre-migration query results with target data for 100% accuracy
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            source_schema: Source schema name
            target_schema: Target schema name
            expected_row_count: Expected row count (from pre-migration validation)
            column_names: List of column names
            pre_migration_query_results: Query results from pre-migration validation (NEW)
            
        Returns:
            Tuple of (is_accurate, error_message, accuracy_report)
        """
        try:
            # Use DataIntegrityVerifier for comprehensive verification
            is_accurate, error_msg, accuracy_report = self.data_integrity_verifier.verify_data_accuracy(
                job_table=job_table,
                source_schema=source_schema,
                target_schema=target_schema,
                expected_row_count=expected_row_count,
                column_names=column_names
            )
            
            # NEW: Compare pre-migration query results with target data
            if pre_migration_query_results and is_accurate:
                from sync_engine.query_result_verifier import QueryResultVerifier
                query_verifier = QueryResultVerifier(self.source_connector)
                
                # Fetch target data
                table = job_table.table_name
                try:
                    # Get order by column for consistent ordering
                    # Try to use primary key, fallback to first column
                    try:
                        pk_columns = self.source_connector.get_primary_key(source_schema, table)
                        if pk_columns:
                            order_by = ', '.join(pk_columns)
                        else:
                            order_by = column_names[0] if column_names else None
                    except:
                        order_by = column_names[0] if column_names else None
                    
                    # Fetch target rows in batches if needed (for large datasets)
                    target_rows = []
                    batch_size = min(10000, expected_row_count) if expected_row_count else 10000
                    offset = 0
                    
                    while True:
                        batch = self.target_connector.fetch_batch(
                            query=self.query_builder.build_select_query(
                                connector=self.target_connector,
                                schema=target_schema,
                                table=table,
                                columns=column_names,
                                order_by=order_by
                            ),
                            batch_size=batch_size,
                            offset=offset
                        )
                        
                        if not batch:
                            break
                        
                        target_rows.extend(batch)
                        offset += len(batch)
                        
                        # Stop if we've fetched enough rows or got fewer than batch size
                        if len(target_rows) >= len(pre_migration_query_results) or len(batch) < batch_size:
                            break
                    
                    # Limit target rows to match pre-migration query results count
                    # (in case we sampled pre-migration results)
                    if len(pre_migration_query_results) < len(target_rows):
                        target_rows = target_rows[:len(pre_migration_query_results)]
                    
                    # Compare query results with target
                    comparison_valid, comparison_error, comparison_report = query_verifier.compare_query_results_with_target(
                        source_query_result=pre_migration_query_results,
                        target_rows=target_rows if target_rows else [],
                        column_names=column_names,
                        column_transformations=job_table.column_transformations or {}
                    )
                    
                    if not comparison_valid:
                        error_msg = f"Query result comparison failed: {comparison_error}"
                        logger.error(
                            f"Post-migration verification failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
                        )
                        return False, error_msg, accuracy_report
                    
                    # Update accuracy report with comparison results
                    accuracy_report['query_result_comparison'] = comparison_report
                    accuracy_report['perfect_accuracy'] = True
                    accuracy_report['pre_migration_rows_compared'] = len(pre_migration_query_results)
                    accuracy_report['target_rows_compared'] = len(target_rows)
                    
                    logger.info(
                        f"Perfect accuracy verified for {job_table.schema_name}.{job_table.table_name}: "
                        f"Query results ({len(pre_migration_query_results)} rows) match target data ({len(target_rows)} rows) exactly"
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not perform query result comparison for {job_table.schema_name}.{job_table.table_name}: {str(e)}",
                        exc_info=True
                    )
                    # Don't fail if comparison can't be performed, but log warning
                    accuracy_report['perfect_accuracy'] = False
                    accuracy_report['comparison_error'] = str(e)
            else:
                # No query results provided - perfect accuracy cannot be verified
                accuracy_report['perfect_accuracy'] = False
            
            if not is_accurate:
                logger.error(
                    f"Post-migration verification failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
                )
                return False, error_msg, accuracy_report
            
            logger.info(
                f"Post-migration verification passed for {job_table.schema_name}.{job_table.table_name}: "
                f"Row count: {accuracy_report.get('actual_row_count', 0)}, "
                f"All rows match: {accuracy_report.get('all_rows_match', False)}, "
                f"Perfect accuracy: {accuracy_report.get('perfect_accuracy', False)}"
            )
            
            return True, None, accuracy_report
            
        except Exception as e:
            error_msg = f"Post-migration verification error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, {}

