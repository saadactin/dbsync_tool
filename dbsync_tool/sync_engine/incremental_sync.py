"""
Incremental sync implementation
"""
from typing import List, Optional, Any
from datetime import datetime
from django.utils import timezone
from django.db.models import Sum
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import DBConnector
from sync_engine.table_handler import TableHandler
from sync_engine.validators import DataValidator
from sync_engine.query_builder import QueryBuilder
from sync_engine.checkpoint_manager import CheckpointManager
from sync_engine.timezone_utils import TimezoneHandler
from sync_engine.exceptions import TableSyncError, CheckpointError
from sync_engine.retry import retry_on_error
from core.constants import DEFAULT_BATCH_SIZE
import logging

logger = logging.getLogger(__name__)

class IncrementalSyncExecutor:
    """Executes incremental sync for a job"""
    
    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        source_connector: DBConnector,
        target_connector: DBConnector
    ):
        """
        Initialize incremental sync executor
        
        Args:
            job: SyncJob instance
            execution: SyncExecution instance
            source_connector: Source database connector
            target_connector: Target database connector
        """
        if not job:
            raise ValueError("Job cannot be None")
        if not execution:
            raise ValueError("Execution cannot be None")
        if not source_connector:
            raise ValueError("Source connector cannot be None")
        if not target_connector:
            raise ValueError("Target connector cannot be None")
        
        if job.sync_type != 'incremental':
            raise ValueError(f"Job sync_type must be 'incremental', got '{job.sync_type}'")
        
        self.job = job
        self.execution = execution
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.table_handler = TableHandler(source_connector, target_connector)
        self.validator = DataValidator()
        self.checkpoint_manager = CheckpointManager(job)
        self.query_builder = QueryBuilder()
        self.timezone_handler = TimezoneHandler()
        self.batch_size = DEFAULT_BATCH_SIZE
        
        logger.info(
            f"Initialized IncrementalSyncExecutor for job {job.id}, "
            f"execution {execution.id}"
        )
    
    def execute(self):
        """
        Execute incremental sync for all enabled tables
        
        Steps:
        1. Update execution status to 'running'
        2. Validate all tables have incremental columns
        3. Connect to source and target databases
        4. Sync each table (continue on individual failures)
        5. Update final execution status
        6. Handle errors gracefully
        
        Raises:
            TableSyncError: If sync fails
        """
        try:
            # Update execution status
            self.execution.status = 'running'
            self.execution.started_at = timezone.now()
            self.execution.save()
            
            # Get enabled tables with incremental columns
            tables = self.job.tables.filter(is_enabled=True)
            
            if not tables.exists():
                logger.warning(f"No enabled tables found for job {self.job.id}")
                self.execution.status = 'completed'
                self.execution.completed_at = timezone.now()
                self.execution.save()
                return
            
            # Validate all tables have incremental columns
            tables_without_column = tables.filter(incremental_column__isnull=True)
            if tables_without_column.exists():
                error_msg = (
                    f"Tables without incremental column: "
                    f"{', '.join(f'{t.schema_name}.{t.table_name}' for t in tables_without_column)}"
                )
                logger.error(error_msg)
                raise TableSyncError(error_msg)
            
            # Connect to databases
            try:
                if not hasattr(self.source_connector, '_connected') or not self.source_connector._connected:
                    self.source_connector.connect()
                    self.source_connector._connected = True
            except Exception as e:
                error_msg = f"Failed to connect to source database: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            try:
                if not hasattr(self.target_connector, '_connected') or not self.target_connector._connected:
                    self.target_connector.connect()
                    self.target_connector._connected = True
            except Exception as e:
                error_msg = f"Failed to connect to target database: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Sync each table
            for job_table in tables:
                try:
                    self.sync_table(job_table)
                except TableSyncError as e:
                    logger.error(f"Table sync failed for {job_table.schema_name}.{job_table.table_name}: {str(e)}")
                    # Continue with other tables
                    continue
                except Exception as e:
                    logger.error(
                        f"Unexpected error syncing table {job_table.schema_name}.{job_table.table_name}: {str(e)}",
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
            total_tables = tables.count()
            completed_count = completed_logs.count()
            failed_count = failed_logs.count()
            
            # Determine execution status
            if failed_count == total_tables and total_tables > 0:
                # ALL tables failed
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"All {failed_count} table(s) failed to sync"
                )
            elif failed_logs.exists():
                # SOME tables failed (partial failure)
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"{failed_count} of {total_tables} table(s) failed to sync"
                )
            elif completed_count == total_tables and total_tables > 0:
                # ALL tables succeeded
                self.execution.status = 'completed'
            else:
                # No logs created (shouldn't happen, but handle gracefully)
                self.execution.status = 'failed'
                self.execution.error_message = "No tables were processed"
            
            self.execution.completed_at = timezone.now()
            self.execution.save()
            
            logger.info(
                f"Incremental sync execution {self.execution.id} completed: "
                f"{completed_count}/{total_tables} tables synced"
            )
            
        except Exception as e:
            logger.error(
                f"Incremental sync execution failed: {str(e)}",
                exc_info=True
            )
            self.execution.status = 'failed'
            self.execution.error_message = str(e)
            self.execution.completed_at = timezone.now()
            self.execution.save()
            raise
    
    def sync_table(self, job_table: SyncJobTable):
        """
        Sync a single table using incremental sync
        
        Steps:
        1. Validate incremental column
        2. Get checkpoint value (None for first sync)
        3. Ensure target table exists (create if not, no truncate)
        4. Build incremental query (WHERE incremental_column > checkpoint_value)
        5. Fetch batches from source
        6. Insert batches into target (no truncate)
        7. Track max incremental value
        8. Update checkpoint after successful sync
        
        Args:
            job_table: SyncJobTable instance
            
        Raises:
            TableSyncError: If table sync fails
        """
        schema = job_table.schema_name
        table = job_table.table_name
        incremental_column = job_table.incremental_column
        
        # Validate incremental column
        if not incremental_column:
            raise TableSyncError(
                f"Incremental column not specified for {schema}.{table}"
            )
        
        # Validate column exists and is appropriate type
        self._validate_incremental_column(schema, table, incremental_column)
        
        # Determine target schema
        # For MySQL targets with PostgreSQL/SQL Server sources: use target database name
        # For PostgreSQL targets with SQL Server sources: map dbo to public
        target_schema = schema
        if self.table_handler.target_db_type == 'mysql' and \
           self.table_handler.source_db_type in ['postgres', 'sqlserver']:
            target_schema = self.target_connector.database_name
        elif self.table_handler.target_db_type == 'postgres' and \
             self.table_handler.source_db_type == 'sqlserver':
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
            
            # Ensure target table exists (create if not, but don't truncate)
            try:
                table_created = self.table_handler.create_table_if_not_exists(schema, table)
                if table_created:
                    logger.info(f"Created target table {schema}.{table} for incremental sync")
            except Exception as e:
                error_msg = f"Failed to create/verify target table: {str(e)}"
                logger.error(f"Table creation error for {schema}.{table}: {error_msg}", exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Get checkpoint value
            checkpoint_value = self.checkpoint_manager.get_checkpoint_value(schema, table)
            
            # Parse checkpoint value if it's a string
            if checkpoint_value:
                # Get column type to parse correctly
                columns = self.source_connector.get_columns(schema, table)
                inc_col_info = next((col for col in columns if col.name == incremental_column), None)
                col_type = inc_col_info.data_type.lower() if inc_col_info else 'timestamp'
                checkpoint_value = self.timezone_handler.parse_checkpoint_value(
                    checkpoint_value, col_type
                )
                logger.info(
                    f"Using checkpoint value for {schema}.{table}: {checkpoint_value}"
                )
            else:
                logger.info(f"No checkpoint found for {schema}.{table} - performing first sync")
            
            # Get column information
            try:
                columns = self.source_connector.get_columns(schema, table)
                if not columns:
                    raise TableSyncError(f"No columns found for source table {schema}.{table}")
                column_names = [col.name for col in columns]
                
                # Get incremental column index for tracking max value
                try:
                    incremental_col_index = column_names.index(incremental_column)
                except ValueError:
                    raise TableSyncError(
                        f"Incremental column '{incremental_column}' not found in column list"
                    )
            except Exception as e:
                error_msg = f"Failed to get columns from source table {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Get primary key for ordering
            try:
                pk_columns = self.source_connector.get_primary_key(schema, table)
                if pk_columns:
                    order_by = f"{incremental_column}, {', '.join(pk_columns)}"
                else:
                    order_by = incremental_column
            except Exception as e:
                logger.warning(f"Could not determine primary key for {schema}.{table}: {str(e)}")
                order_by = incremental_column
            
            # Build incremental query
            try:
                query = self.query_builder.build_incremental_query(
                    connector=self.source_connector,
                    schema=schema,
                    table=table,
                    incremental_column=incremental_column,
                    checkpoint_value=checkpoint_value,
                    columns=column_names,
                    order_by=order_by
                )
                logger.debug(f"Incremental query for {schema}.{table}: {query}")
            except Exception as e:
                error_msg = f"Failed to build incremental query for {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Fetch and insert in batches
            offset = 0
            batch_number = 0
            total_rows_fetched = 0
            total_rows_inserted = 0
            max_incremental_value = checkpoint_value  # Start with checkpoint value
            
            while True:
                # Fetch batch with retry
                try:
                    batch = self._fetch_batch_with_retry(
                        query=query,
                        batch_size=self.batch_size,
                        offset=offset
                    )
                except Exception as e:
                    error_msg = f"Failed to fetch batch {batch_number + 1} for {schema}.{table}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    self._handle_partial_batch_failure(schema, table, batch_number + 1, [])
                    raise TableSyncError(error_msg) from e
                
                if not batch:
                    break  # No more rows
                
                batch_number += 1
                total_rows_fetched += len(batch)
                
                # Validate batch
                self.validator.validate_batch_not_empty(batch, f"{schema}.{table}")
                
                # Find max incremental value in batch
                max_incremental_value = self._get_max_incremental_value(
                    batch, incremental_col_index, max_incremental_value
                )
                
                # Insert batch with retry (use target_schema for MySQL)
                try:
                    self._insert_batch_with_retry(
                        schema=target_schema,
                        table=table,
                        columns=column_names,
                        rows=batch
                    )
                    total_rows_inserted += len(batch)
                except Exception as e:
                    error_msg = f"Failed to insert batch {batch_number} for {schema}.{table}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    self._handle_partial_batch_failure(schema, table, batch_number, batch)
                    raise TableSyncError(error_msg) from e
                
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
            
            # Update checkpoint only after successful sync
            if max_incremental_value is not None and max_incremental_value != checkpoint_value:
                try:
                    self.checkpoint_manager.create_or_update_checkpoint(
                        schema_name=schema,
                        table_name=table,
                        value=max_incremental_value
                    )
                    logger.info(
                        f"Updated checkpoint for {schema}.{table}: {max_incremental_value}"
                    )
                except Exception as e:
                    # Log error but don't fail the sync
                    logger.error(
                        f"Failed to update checkpoint for {schema}.{table}: {str(e)}",
                        exc_info=True
                    )
            elif max_incremental_value == checkpoint_value:
                logger.info(
                    f"No new data for {schema}.{table} - checkpoint unchanged"
                )
            
            # Mark log as completed
            log.status = 'completed'
            log.completed_at = timezone.now()
            log.save()
            
            logger.info(
                f"Successfully synced table {schema}.{table} incrementally: "
                f"{total_rows_inserted} rows in {batch_number} batches"
            )
            
        except Exception as e:
            log.status = 'failed'
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save()
            
            logger.error(
                f"Failed to sync table {schema}.{table} incrementally: {str(e)}",
                exc_info=True
            )
            raise TableSyncError(f"Incremental sync failed for {schema}.{table}: {str(e)}") from e
    
    def _compare_incremental_values(self, value1: Any, value2: Any) -> bool:
        """
        Compare two incremental values to determine which is greater
        
        Args:
            value1: First value
            value2: Second value
            
        Returns:
            True if value1 > value2, False otherwise
        """
        if value1 is None:
            return False
        if value2 is None:
            return True
        
        # Handle datetime comparisons
        if isinstance(value1, datetime) and isinstance(value2, datetime):
            return value1 > value2
        
        # Handle numeric comparisons
        if isinstance(value1, (int, float)) and isinstance(value2, (int, float)):
            return value1 > value2
        
        # String comparison
        return str(value1) > str(value2)

    def _get_max_incremental_value(self, batch: List[tuple], col_index: int, current_max: Any) -> Any:
        """
        Get maximum incremental value from batch
        
        Args:
            batch: Batch of rows
            col_index: Index of incremental column
            current_max: Current maximum value
            
        Returns:
            Maximum value from batch
        """
        max_value = current_max
        for row in batch:
            row_value = row[col_index]
            if row_value is not None:
                if max_value is None or self._compare_incremental_values(row_value, max_value):
                    max_value = row_value
        return max_value

    def _validate_incremental_column(
        self,
        schema: str,
        table: str,
        incremental_column: str
    ) -> bool:
        """
        Validate that incremental column exists and is appropriate for incremental sync
        
        Args:
            schema: Schema name
            table: Table name
            incremental_column: Column name to validate
            
        Returns:
            True if column is valid
            
        Raises:
            TableSyncError: If column is invalid
        """
        try:
            columns = self.source_connector.get_columns(schema, table)
            column_names = [col.name for col in columns]
            
            if incremental_column not in column_names:
                raise TableSyncError(
                    f"Incremental column '{incremental_column}' not found "
                    f"in table {schema}.{table}"
                )
            
            # Check if column type is suitable for incremental sync
            column_info = next(
                (col for col in columns if col.name == incremental_column),
                None
            )
            if column_info:
                col_type = column_info.data_type.lower()
                valid_types = [
                    'timestamp', 'datetime', 'date', 'timestamptz',
                    'int', 'integer', 'bigint', 'serial', 'int4', 'int8',
                    'float', 'double', 'numeric', 'decimal'
                ]
                if not any(vt in col_type for vt in valid_types):
                    logger.warning(
                        f"Incremental column '{incremental_column}' has type "
                        f"'{col_type}' which may not be ideal for incremental sync. "
                        f"Consider using timestamp or integer types."
                    )
                
                # Check if column is nullable (warning)
                if column_info.is_nullable:
                    logger.warning(
                        f"Incremental column '{incremental_column}' allows NULL values. "
                        f"Rows with NULL values will be skipped in checkpoint updates."
                    )
            
            return True
        except TableSyncError:
            raise
        except Exception as e:
            logger.error(
                f"Error validating incremental column: {str(e)}",
                exc_info=True
            )
            raise TableSyncError(
                f"Failed to validate incremental column: {str(e)}"
            ) from e

    def _handle_failed_sync(
        self,
        schema: str,
        table: str,
        error: Exception,
        checkpoint_value: Any
    ):
        """
        Handle failed sync - don't update checkpoint
        
        Args:
            schema: Schema name
            table: Table name
            error: Exception that occurred
            checkpoint_value: Checkpoint value before sync attempt
        """
        logger.error(
            f"Sync failed for {schema}.{table}. Checkpoint NOT updated. "
            f"Previous checkpoint value: {checkpoint_value}"
        )
        # Checkpoint remains unchanged - next sync will retry from same point

    def _handle_partial_batch_failure(
        self,
        schema: str,
        table: str,
        batch_number: int,
        batch: List[tuple]
    ):
        """
        Handle partial batch failure - rollback transaction if possible
        
        Args:
            schema: Schema name
            table: Table name
            batch_number: Batch number that failed
            batch: Batch data
        """
        logger.error(
            f"Batch {batch_number} failed for {schema}.{table}. "
            f"Attempting to rollback transaction."
        )
        # Most databases handle this automatically, but log for debugging
        # For databases that support transactions, the connector should handle rollback

    def _recover_from_checkpoint_corruption(
        self,
        schema: str,
        table: str
    ):
        """
        Recover from checkpoint corruption by resetting checkpoint
        
        Args:
            schema: Schema name
            table: Table name
        """
        logger.warning(
            f"Checkpoint corruption detected for {schema}.{table}. "
            f"Resetting checkpoint - next sync will be a full sync."
        )
        self.checkpoint_manager.delete_checkpoint(schema, table)

    def _prevent_concurrent_sync(self, schema: str, table: str) -> bool:
        """
        Check if another sync is already running for this table
        
        Args:
            schema: Schema name
            table: Table name
            
        Returns:
            True if sync can proceed, False if another sync is running
        """
        # Check for running executions for this job and table
        running_logs = SyncExecutionLog.objects.filter(
            execution__job=self.job,
            schema_name=schema,
            table_name=table,
            status='running'
        ).exclude(execution=self.execution)
        
        if running_logs.exists():
            logger.warning(
                f"Another sync is already running for {schema}.{table}. "
                f"Skipping this sync."
            )
            return False
        return True

    @retry_on_error(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def _fetch_batch_with_retry(self, query: str, batch_size: int, offset: int):
        """Fetch batch with retry logic"""
        return self.source_connector.fetch_batch(
            query=query,
            batch_size=batch_size,
            offset=offset,
            order_by=None
        )

    @retry_on_error(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def _insert_batch_with_retry(
        self,
        schema: str,
        table: str,
        columns: List[str],
        rows: List[tuple]
    ):
        """Insert batch with retry logic"""
        return self.target_connector.bulk_insert(
            schema=schema,
            table=table,
            columns=columns,
            rows=rows
        )

