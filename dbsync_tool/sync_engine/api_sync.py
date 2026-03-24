"""
API sync executor for syncing data from API sources (Zoho CRM) to database targets
"""
from typing import List, Optional, Tuple
from django.utils import timezone
from django.db.models import Sum
from django.db import transaction
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, APISyncState
from connections.connectors.zoho import ZohoConnector
from connections.connectors.base import DBConnector
from sync_engine.data_transformer import DataTransformer
from sync_engine.exceptions import TableSyncError
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)


class APISyncExecutor:
    """
    Execute sync jobs with API sources (Zoho CRM) to database targets
    Supports both full and incremental sync
    """
    
    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        api_connector: ZohoConnector,
        target_connector: DBConnector
    ):
        """
        Initialize API sync executor
        
        Args:
            job: SyncJob instance with API source
            execution: SyncExecution instance
            api_connector: ZohoConnector instance
            target_connector: Target database connector
        """
        self.job = job
        self.execution = execution
        self.api_connector = api_connector
        self.target_connector = target_connector
        self.transformer = DataTransformer()
        self.batch_size = 1000  # Process 1000 records per batch
    
    def execute(self):
        """
        Execute sync for all modules in job
        
        Raises:
            Exception: If execution fails
        """
        try:
            if self.job.sync_type == 'full':
                self.execute_full_sync()
            elif self.job.sync_type == 'incremental':
                self.execute_incremental_sync()
            else:
                raise ValueError(f"Unknown sync type: {self.job.sync_type}")
        except Exception as e:
            logger.error(f"API sync execution failed for job {self.job.id}: {str(e)}", exc_info=True)
            raise
    
    def execute_full_sync(self):
        """Execute full sync for all modules"""
        modules = self._get_modules_from_job()
        
        if not modules:
            logger.warning(f"No modules found for job {self.job.id}")
            return
        
        logger.info(f"Starting full sync for {len(modules)} modules in job {self.job.id}")
        
        for module_name in modules:
            try:
                self._sync_module_full(module_name)
            except Exception as e:
                logger.error(f"Failed to sync module {module_name} in job {self.job.id}: {str(e)}", exc_info=True)
                # Continue with other modules even if one fails
                # Log the error in execution log
                self._create_error_log(module_name, str(e))
    
    def execute_incremental_sync(self):
        """Execute incremental sync for all modules"""
        modules = self._get_modules_from_job()
        
        if not modules:
            logger.warning(f"No modules found for job {self.job.id}")
            return
        
        logger.info(f"Starting incremental sync for {len(modules)} modules in job {self.job.id}")
        
        for module_name in modules:
            try:
                self._sync_module_incremental(module_name)
            except Exception as e:
                logger.error(f"Failed to sync module {module_name} in job {self.job.id}: {str(e)}", exc_info=True)
                # Continue with other modules even if one fails
                # Log the error in execution log
                self._create_error_log(module_name, str(e))
    
    def _get_modules_from_job(self) -> List[str]:
        """
        Get list of modules to sync from SyncJobTable entries
        
        Returns:
            List[str]: List of module names
        """
        # For API sources, table_name stores the module name
        # schema_name can be 'api' or the module name
        job_tables = self.job.tables.filter(is_enabled=True)
        modules = []
        
        for job_table in job_tables:
            # Use table_name as module name for API sources
            module_name = job_table.table_name
            if module_name and module_name not in modules:
                modules.append(module_name)
        
        return modules
    
    def _sync_module_full(self, module_name: str):
        """
        Sync a single module (full sync)
        
        Args:
            module_name: Name of the module to sync
        """
        logger.info(f"Starting full sync for module: {module_name}")
        
        # Create execution log
        log = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name='api',
            table_name=module_name,
            status='running',
            started_at=timezone.now()
        )
        
        try:
            # 1. Fetch all records from Zoho
            logger.info(f"Fetching all records from module: {module_name}")
            records = self.api_connector.fetch_records(module_name)
            
            if not records:
                logger.info(f"No records found in module {module_name}")
                log.status = 'completed'
                log.rows_fetched = 0
                log.rows_inserted = 0
                log.completed_at = timezone.now()
                log.save()
                return
            
            logger.info(f"Fetched {len(records)} records from module {module_name}")
            
            # 2. Flatten JSON using DataTransformer
            logger.info(f"Flattening JSON data for module {module_name}")
            df = self.transformer.flatten_json(records)
            
            if df.empty:
                logger.warning(f"Empty DataFrame after flattening for module {module_name}")
                log.status = 'completed'
                log.rows_fetched = len(records)
                log.rows_inserted = 0
                log.completed_at = timezone.now()
                log.save()
                return
            
            # 3. Prepare data for target database
            target_db_type = self._get_target_db_type()
            logger.info(f"Preparing data for {target_db_type} database")
            df = self.transformer.prepare_for_database(df, target_db_type)
            
            # 4. Create/update table in target DB
            # Use ZOHO_ prefix so tables are clearly namespaced (e.g. ZOHO_leads)
            base_table = f"ZOHO_{module_name.lower().replace(' ', '_').replace('-', '_')}"
            prefix = getattr(self.job, 'target_table_prefix', None)
            target_table = f"{prefix}_{base_table}" if prefix else base_table
            target_schema = self.target_connector.database_name
            
            logger.info(f"Creating/updating table {target_schema}.{target_table}")
            self._ensure_table_exists(df, target_schema, target_table)
            
            # 5. Truncate table for full sync (optional - could also do upsert)
            # For now, we'll truncate to ensure clean full sync
            try:
                self.target_connector.truncate_table(target_schema, target_table)
            except Exception as e:
                logger.warning(f"Could not truncate table {target_schema}.{target_table}: {e}")
                # Continue anyway - table might not support truncate or might be empty
            
            # 6. Bulk insert data in batches
            column_names = list(df.columns)
            total_rows = len(df)
            total_inserted = 0
            
            logger.info(f"Inserting {total_rows} rows in batches of {self.batch_size}")
            
            for batch_start in range(0, total_rows, self.batch_size):
                batch_end = min(batch_start + self.batch_size, total_rows)
                batch_df = df.iloc[batch_start:batch_end]
                
                # Convert DataFrame rows to list of tuples
                batch_rows = [tuple(row) for row in batch_df.values]
                
                try:
                    self.target_connector.bulk_insert(
                        schema=target_schema,
                        table=target_table,
                        columns=column_names,
                        rows=batch_rows
                    )
                    total_inserted += len(batch_rows)
                    logger.info(f"Inserted batch: {len(batch_rows)} rows (Total: {total_inserted}/{total_rows})")
                except Exception as e:
                    raise TableSyncError(
                        f"Failed to insert batch for {module_name}: {str(e)}"
                    )
                
                # Update log
                log.rows_fetched = len(records)
                log.rows_inserted = total_inserted
                log.batch_number = (batch_start // self.batch_size) + 1
                log.save()
                
                # Update execution progress
                self._update_execution_progress()
            
            # 7. Update sync state (for tracking)
            self._update_sync_state(module_name, len(records), total_inserted)
            
            # Mark log as completed
            log.status = 'completed'
            log.completed_at = timezone.now()
            log.save()
            
            logger.info(f"Completed full sync for module {module_name}: {total_inserted} rows inserted")
            
        except Exception as e:
            logger.error(f"Error syncing module {module_name}: {str(e)}", exc_info=True)
            log.status = 'failed'
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save()
            raise
    
    def _sync_module_incremental(self, module_name: str):
        """
        Sync a single module (incremental sync)
        
        Args:
            module_name: Name of the module to sync
        """
        logger.info(f"Starting incremental sync for module: {module_name}")
        
        # Create execution log
        log = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name='api',
            table_name=module_name,
            status='running',
            started_at=timezone.now()
        )
        
        try:
            # 1. Get last sync time from APISyncState
            sync_state, created = APISyncState.objects.get_or_create(
                job=self.job,
                module_name=module_name,
                defaults={
                    'last_sync_time': None,
                    'last_modified_time': None,
                    'records_synced': 0
                }
            )
            
            # If this is the first sync, do a full sync
            if sync_state.last_sync_time is None:
                logger.info(f"No previous sync found for module {module_name}, performing full sync")
                self._sync_module_full(module_name)
                return
            
            since = sync_state.last_modified_time or sync_state.last_sync_time
            logger.info(f"Fetching records modified since: {since} for module {module_name}")
            
            # 2. Fetch modified records since last sync
            records = self.api_connector.fetch_incremental_records(module_name, since)
            
            if not records:
                logger.info(f"No modified records found in module {module_name}")
                log.status = 'completed'
                log.rows_fetched = 0
                log.rows_inserted = 0
                log.completed_at = timezone.now()
                log.save()
                return
            
            logger.info(f"Fetched {len(records)} modified records from module {module_name}")
            
            # 3. Flatten JSON using DataTransformer
            logger.info(f"Flattening JSON data for module {module_name}")
            df = self.transformer.flatten_json(records)
            
            if df.empty:
                logger.warning(f"Empty DataFrame after flattening for module {module_name}")
                log.status = 'completed'
                log.rows_fetched = len(records)
                log.rows_inserted = 0
                log.completed_at = timezone.now()
                log.save()
                return
            
            # 4. Prepare data for target database
            target_db_type = self._get_target_db_type()
            logger.info(f"Preparing data for {target_db_type} database")
            df = self.transformer.prepare_for_database(df, target_db_type)
            
            # 5. Ensure table exists
            # Use ZOHO_ prefix so tables are clearly namespaced (e.g. ZOHO_leads)
            base_table = f"ZOHO_{module_name.lower().replace(' ', '_').replace('-', '_')}"
            prefix = getattr(self.job, 'target_table_prefix', None)
            target_table = f"{prefix}_{base_table}" if prefix else base_table
            target_schema = self.target_connector.database_name
            
            if not self.target_connector.table_exists(target_schema, target_table):
                prefix = getattr(self.job, "target_table_prefix", None)
                warning_msg = (
                    f"Skipped incremental sync for module {module_name}: "
                    f"target table {target_schema}.{target_table} does not exist. "
                    f"Incremental sync does not create new tables "
                    f"(reason=missing_target_table, prefix={prefix or 'none'}, sync_type=incremental)."
                )
                logger.warning(warning_msg)
                log.status = "completed"
                log.rows_fetched = len(records)
                log.rows_inserted = 0
                log.error_message = warning_msg
                log.completed_at = timezone.now()
                log.save()
                self._update_execution_progress()
                return

            logger.info(f"Using existing table {target_schema}.{target_table} for incremental sync")
            self.target_connector.add_missing_columns(target_schema, target_table, df)
            
            # 6. Upsert data (for incremental sync, we need to handle updates)
            # For simplicity, we'll do insert with ON DUPLICATE KEY UPDATE or similar
            # This depends on the target database type
            column_names = list(df.columns)
            total_rows = len(df)
            total_inserted = 0
            
            # Find primary key or unique identifier column
            # For Zoho, typically 'id' or 'Id' field
            id_column = None
            for col in column_names:
                if col.lower() in ['id', 'record_id', 'zoho_id']:
                    id_column = col
                    break
            
            logger.info(f"Upserting {total_rows} rows in batches of {self.batch_size}")
            
            for batch_start in range(0, total_rows, self.batch_size):
                batch_end = min(batch_start + self.batch_size, total_rows)
                batch_df = df.iloc[batch_start:batch_end]
                
                # Convert DataFrame rows to list of tuples
                batch_rows = [tuple(row) for row in batch_df.values]
                
                try:
                    # For incremental sync, use upsert if we have a key column
                    if id_column:
                        # Use upsert to handle updates
                        self.target_connector.upsert_dataframe(
                            schema=target_schema,
                            table=target_table,
                            df=batch_df,
                            key_column=id_column
                        )
                        total_inserted += len(batch_rows)
                        logger.info(f"Upserted batch: {len(batch_rows)} rows (Total: {total_inserted}/{total_rows})")
                    else:
                        # No key column, use regular insert
                        logger.warning(f"No key column found for upsert, using regular insert (may cause duplicates)")
                        self.target_connector.bulk_insert(
                            schema=target_schema,
                            table=target_table,
                            columns=column_names,
                            rows=batch_rows
                        )
                        total_inserted += len(batch_rows)
                        logger.info(f"Inserted batch: {len(batch_rows)} rows (Total: {total_inserted}/{total_rows})")
                except Exception as e:
                    raise TableSyncError(
                        f"Failed to upsert batch for {module_name}: {str(e)}"
                    )
                
                # Update log
                log.rows_fetched = len(records)
                log.rows_inserted = total_inserted
                log.batch_number = (batch_start // self.batch_size) + 1
                log.save()
                
                # Update execution progress
                self._update_execution_progress()
            
            # 7. Update sync state with latest modified time
            max_modified_time = self._get_max_modified_time(records)
            with transaction.atomic():
                sync_state.last_sync_time = timezone.now()
                if max_modified_time:
                    sync_state.last_modified_time = max_modified_time
                sync_state.records_synced += total_inserted
                sync_state.save()
            
            # Mark log as completed
            log.status = 'completed'
            log.completed_at = timezone.now()
            log.save()
            
            logger.info(f"Completed incremental sync for module {module_name}: {total_inserted} rows upserted")
            
        except Exception as e:
            logger.error(f"Error syncing module {module_name}: {str(e)}", exc_info=True)
            log.status = 'failed'
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save()
            raise
    
    def _ensure_table_exists(self, df: pd.DataFrame, schema: str, table: str):
        """
        Ensure table exists in target database, create if it doesn't
        
        Args:
            df: DataFrame with data structure
            schema: Schema name
            table: Table name
        """
        try:
            # Check if table exists
            if self.target_connector.table_exists(schema, table):
                # Table exists, check if we need to add columns
                logger.info(f"Table {schema}.{table} exists, checking for missing columns")
                self.target_connector.add_missing_columns(schema, table, df)
                return
            
            # Table doesn't exist, create it
            logger.info(f"Creating table {schema}.{table} from DataFrame")
            self.target_connector.create_table_from_dataframe(schema, table, df)
            logger.info(f"Successfully created table {schema}.{table}")
        except Exception as e:
            logger.error(f"Error ensuring table exists {schema}.{table}: {str(e)}", exc_info=True)
            raise
    
    def _get_target_db_type(self) -> str:
        """
        Get target database type
        
        Returns:
            str: Database type ('clickhouse', 'postgres', 'mysql', 'sqlserver')
        """
        class_name = self.target_connector.__class__.__name__
        if 'Postgres' in class_name:
            return 'postgres'
        elif 'MySQL' in class_name:
            return 'mysql'
        elif 'SQLServer' in class_name:
            return 'sqlserver'
        elif 'ClickHouse' in class_name:
            return 'clickhouse'
        else:
            return 'postgres'  # Default
    
    def _update_execution_progress(self):
        """Update execution progress metrics"""
        try:
            self.execution.completed_tables = SyncExecutionLog.objects.filter(
                execution=self.execution,
                status='completed'
            ).count()
            self.execution.total_rows_synced = SyncExecutionLog.objects.filter(
                execution=self.execution
            ).aggregate(total=Sum('rows_inserted'))['total'] or 0
            self.execution.save()
        except Exception as e:
            logger.warning(f"Error updating execution progress: {str(e)}")
    
    def _update_sync_state(self, module_name: str, records_fetched: int, records_inserted: int):
        """
        Update sync state for a module
        
        Args:
            module_name: Module name
            records_fetched: Number of records fetched
            records_inserted: Number of records inserted
        """
        try:
            sync_state, created = APISyncState.objects.get_or_create(
                job=self.job,
                module_name=module_name,
                defaults={
                    'last_sync_time': timezone.now(),
                    'records_synced': records_inserted
                }
            )
            
            if not created:
                sync_state.last_sync_time = timezone.now()
                sync_state.records_synced += records_inserted
                sync_state.save()
        except Exception as e:
            logger.warning(f"Error updating sync state for {module_name}: {str(e)}")
    
    def _get_max_modified_time(self, records: List[dict]) -> Optional[datetime]:
        """
        Get maximum Modified_Time from records
        
        Args:
            records: List of record dictionaries
            
        Returns:
            Optional[datetime]: Maximum modified time or None
        """
        max_time = None
        for record in records:
            if 'Modified_Time' in record:
                try:
                    record_time = pd.to_datetime(record['Modified_Time'])
                    if pd.notna(record_time):
                        record_time = record_time.to_pydatetime()
                        if max_time is None or record_time > max_time:
                            max_time = record_time
                except Exception:
                    pass
        return max_time
    
    def _create_error_log(self, module_name: str, error_message: str):
        """
        Create error log for a module
        
        Args:
            module_name: Module name
            error_message: Error message
        """
        try:
            SyncExecutionLog.objects.create(
                execution=self.execution,
                schema_name='api',
                table_name=module_name,
                status='failed',
                error_message=error_message,
                started_at=timezone.now(),
                completed_at=timezone.now()
            )
        except Exception as e:
            logger.warning(f"Error creating error log for {module_name}: {str(e)}")
