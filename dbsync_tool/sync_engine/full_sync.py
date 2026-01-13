"""
Full sync implementation
"""
from typing import List, Optional
from django.utils import timezone
from django.db.models import Sum
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import DBConnector
from sync_engine.table_handler import TableHandler
from sync_engine.validators import DataValidator
from sync_engine.query_builder import QueryBuilder
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
                query = self.query_builder.build_select_query(
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

