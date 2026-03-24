"""
SAP sync executor for syncing data from SAP B1 Service Layer to database targets.
Supports full and incremental (hash-based change detection) sync.
"""
from typing import List, Optional
from django.utils import timezone
from django.db.models import Sum
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, APISyncState
from connections.connectors.base import DBConnector
from sync_engine.data_transformer import DataTransformer
from sync_engine.exceptions import TableSyncError
from sync_engine import sap_sync_state
from core.constants import SAP_DOCUMENT_TYPES
from connections.connectors.sap_utils import compute_record_hash
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Default batch size for bulk insert/upsert
DEFAULT_BATCH_SIZE = 1000


def _normalize_target_table_name(endpoint_name: str) -> str:
    """SAP tables use SAP_ prefix; endpoint name to snake_case."""
    normalized = endpoint_name.lower().replace(" ", "_").replace("-", "_")
    return f"SAP_{normalized}"


class SAPSyncExecutor:
    """
    Execute sync jobs with SAP B1 API source to database targets.
    Same interface pattern as APISyncExecutor; no inheritance from it.
    """

    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        api_connector,
        target_connector: DBConnector,
    ):
        self.job = job
        self.execution = execution
        self.api_connector = api_connector
        self.target_connector = target_connector
        self.transformer = DataTransformer()
        self.batch_size = DEFAULT_BATCH_SIZE

    def execute(self):
        """Dispatch to optimized async executor."""
        try:
            from sync_engine.sap_optimized import OptimizedSAPSyncExecutor
            import asyncio
            
            logger.info(f"Starting optimized SAP sync for job {self.job.id}")
            optimized_executor = OptimizedSAPSyncExecutor(
                self.job,
                self.execution,
                self.api_connector.api_connection,
                self.target_connector
            )
            
            # Use asyncio.run to execute the async logic from this sync method
            asyncio.run(optimized_executor.execute())
            
        except Exception as e:
            logger.error(
                f"SAP sync execution failed for job {self.job.id}: {str(e)}",
                exc_info=True,
            )
            raise

    def _get_endpoints_from_job(self) -> List[str]:
        """From job.tables (enabled) get unique table_name (endpoint). If SAP and empty, use connection sap_endpoints."""
        job_tables = self.job.tables.filter(is_enabled=True)
        endpoints = []
        for job_table in job_tables:
            name = job_table.table_name
            if name and name not in endpoints:
                endpoints.append(name)
        if not endpoints and self.job.source_api_connection and getattr(self.job.source_api_connection, "sap_endpoints", None):
            endpoints = list(self.job.source_api_connection.sap_endpoints or [])
        return endpoints

    def execute_full_sync(self):
        """Full sync per endpoint; on failure log and create failed SyncExecutionLog, continue others."""
        endpoints = self._get_endpoints_from_job()
        if not endpoints:
            logger.warning(f"No SAP endpoints found for job {self.job.id}")
            return
        logger.info(f"Starting SAP full sync for {len(endpoints)} endpoints in job {self.job.id}")
        for endpoint_name in endpoints:
            try:
                self._sync_endpoint_full(endpoint_name)
            except Exception as e:
                logger.error(
                    f"Failed to sync SAP endpoint {endpoint_name} in job {self.job.id}: {str(e)}",
                    exc_info=True,
                )
                self._create_error_log(endpoint_name, str(e))

    def _sync_endpoint_full(self, endpoint_name: str):
        log = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name="api",
            table_name=endpoint_name,
            status="running",
            started_at=timezone.now(),
        )
        try:
            records = self.api_connector.fetch_records(endpoint_name)
            if not records:
                log.rows_fetched = 0
                log.rows_inserted = 0
                log.status = "completed"
                log.completed_at = timezone.now()
                log.save()
                return

            df = self.transformer.flatten_json(records)
            if df.empty:
                log.rows_fetched = len(records)
                log.rows_inserted = 0
                log.status = "completed"
                log.completed_at = timezone.now()
                log.save()
                return

            df = self.transformer.prepare_for_database(df, self._get_target_db_type())
            target_schema = self.target_connector.database_name
            base_table = _normalize_target_table_name(endpoint_name)
            prefix = getattr(self.job, 'target_table_prefix', None)
            target_table = f"{prefix}_{base_table}" if prefix else base_table
            self._ensure_table_exists(df, target_schema, target_table)
            try:
                self.target_connector.truncate_table(target_schema, target_table)
            except Exception as e:
                logger.warning(f"Could not truncate {target_schema}.{target_table}: {e}")

            column_names = list(df.columns)
            total_rows = len(df)
            total_inserted = 0
            for batch_start in range(0, total_rows, self.batch_size):
                batch_end = min(batch_start + self.batch_size, total_rows)
                batch_df = df.iloc[batch_start:batch_end]
                batch_rows = [tuple(row) for row in batch_df.values]
                self.target_connector.bulk_insert(
                    schema=target_schema,
                    table=target_table,
                    columns=column_names,
                    rows=batch_rows,
                )
                total_inserted += len(batch_rows)
                log.rows_fetched = len(records)
                log.rows_inserted = total_inserted
                log.batch_number = (batch_start // self.batch_size) + 1
                log.save()
                self._update_execution_progress()

            self._update_sync_state(endpoint_name, len(records), total_inserted)
            log.status = "completed"
            log.completed_at = timezone.now()
            log.save()
            logger.info(f"Completed SAP full sync for {endpoint_name}: {total_inserted} rows")
        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save()
            raise

    def execute_incremental_sync(self):
        """Incremental per endpoint; hash-based change detection."""
        endpoints = self._get_endpoints_from_job()
        if not endpoints:
            logger.warning(f"No SAP endpoints found for job {self.job.id}")
            return
        logger.info(f"Starting SAP incremental sync for {len(endpoints)} endpoints in job {self.job.id}")
        for endpoint_name in endpoints:
            try:
                self._sync_endpoint_incremental(endpoint_name)
            except Exception as e:
                logger.error(
                    f"Failed to sync SAP endpoint {endpoint_name} in job {self.job.id}: {str(e)}",
                    exc_info=True,
                )
                self._create_error_log(endpoint_name, str(e))

    def _sync_endpoint_incremental(self, endpoint_name: str):
        log = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name="api",
            table_name=endpoint_name,
            status="running",
            started_at=timezone.now(),
        )
        try:
            state = sap_sync_state.get_or_create_state(self.job, endpoint_name)
            previous_hashes = sap_sync_state.get_hashes(self.job, endpoint_name)
            if state.last_sync_time is None or not previous_hashes:
                logger.info(f"First incremental for {endpoint_name}, running full sync")
                self._sync_endpoint_full(endpoint_name)
                id_field = self._get_id_field_for_endpoint(endpoint_name)
                if id_field:
                    records = self.api_connector.fetch_records(endpoint_name)
                    current_hashes = {}
                    for rec in records:
                        rid = rec.get(id_field)
                        if rid is not None:
                            current_hashes[str(rid)] = compute_record_hash(rec)
                    sap_sync_state.save_hashes(self.job, endpoint_name, current_hashes)
                state.last_sync_time = timezone.now()
                state.save()
                return

            since = state.last_sync_time
            records = self.api_connector.fetch_incremental_records(endpoint_name, since)
            id_field = self._get_id_field_for_endpoint(endpoint_name)
            if not id_field:
                logger.warning(f"No id_field for endpoint {endpoint_name}, running full sync")
                self._sync_endpoint_full(endpoint_name)
                return

            current_hashes = {}
            for rec in records:
                rid = rec.get(id_field)
                if rid is not None:
                    current_hashes[str(rid)] = compute_record_hash(rec)

            deleted_ids = [k for k in previous_hashes if k not in current_hashes]
            new_or_changed_ids = [
                k for k in current_hashes
                if k not in previous_hashes or previous_hashes[k] != current_hashes[k]
            ]
            records_by_id = {str(rec.get(id_field)): rec for rec in records if rec.get(id_field) is not None}
            new_or_changed_records = [records_by_id[k] for k in new_or_changed_ids if k in records_by_id]

            target_schema = self.target_connector.database_name
            base_table = _normalize_target_table_name(endpoint_name)
            prefix = getattr(self.job, 'target_table_prefix', None)
            target_table = f"{prefix}_{base_table}" if prefix else base_table

            if deleted_ids:
                self._delete_records_by_ids(target_schema, target_table, id_field, deleted_ids)

            total_upserted = 0
            if new_or_changed_records:
                df = self.transformer.flatten_json(new_or_changed_records)
                if not df.empty:
                    df = self.transformer.prepare_for_database(df, self._get_target_db_type())
                    if not self.target_connector.table_exists(target_schema, target_table):
                        prefix = getattr(self.job, "target_table_prefix", None)
                        warning_msg = (
                            f"Skipped SAP incremental sync for endpoint {endpoint_name}: "
                            f"target table {target_schema}.{target_table} does not exist. "
                            f"Incremental sync does not create new tables "
                            f"(reason=missing_target_table, prefix={prefix or 'none'}, sync_type=incremental)."
                        )
                        logger.warning(warning_msg)
                        log.rows_fetched = len(records)
                        log.rows_inserted = 0
                        log.status = "completed"
                        log.error_message = warning_msg
                        log.completed_at = timezone.now()
                        log.save()
                        self._update_execution_progress()
                        return
                    self.target_connector.add_missing_columns(target_schema, target_table, df)
                    id_column_df = id_field if id_field in df.columns else next(
                        (c for c in df.columns if c.lower() == id_field.lower()),
                        id_field,
                    )
                    self.target_connector.upsert_dataframe(
                        schema=target_schema,
                        table=target_table,
                        df=df,
                        key_column=id_column_df,
                    )
                    total_upserted = len(df)

            sap_sync_state.save_hashes(self.job, endpoint_name, current_hashes)
            state.last_sync_time = timezone.now()
            state.records_synced = (state.records_synced or 0) + total_upserted
            state.save()

            log.rows_fetched = len(records)
            log.rows_inserted = total_upserted
            log.status = "completed"
            log.completed_at = timezone.now()
            log.save()
            self._update_execution_progress()
            logger.info(f"Completed SAP incremental for {endpoint_name}: {total_upserted} upserted, {len(deleted_ids)} deleted")
        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save()
            raise

    def _delete_records_by_ids(
        self,
        schema: str,
        table: str,
        id_column: str,
        ids: List[str],
    ):
        """Run DELETE for each id (safe across DBs). Identifier quoting per DB type."""
        db_type = self._get_target_db_type()
        if db_type == "sqlserver":
            placeholder = "?"
        else:
            placeholder = "%s"
        for id_val in ids:
            if db_type == "postgres":
                q = f'DELETE FROM "{schema}"."{table}" WHERE "{id_column}" = {placeholder}'
            elif db_type == "mysql":
                q = f"DELETE FROM `{schema}`.`{table}` WHERE `{id_column}` = {placeholder}"
            elif db_type == "sqlserver":
                q = f"DELETE FROM [{schema}].[{table}] WHERE [{id_column}] = {placeholder}"
            elif db_type == "clickhouse":
                q = f"DELETE FROM `{schema}`.`{table}` WHERE `{id_column}` = {placeholder}"
            else:
                q = f'DELETE FROM "{schema}"."{table}" WHERE "{id_column}" = {placeholder}'
            self.target_connector.execute_query(q, [id_val])

    def _get_target_db_type(self) -> str:
        class_name = self.target_connector.__class__.__name__
        if "Postgres" in class_name:
            return "postgres"
        if "MySQL" in class_name:
            return "mysql"
        if "SQLServer" in class_name:
            return "sqlserver"
        if "ClickHouse" in class_name:
            return "clickhouse"
        return "postgres"

    def _ensure_table_exists(self, df: pd.DataFrame, schema: str, table: str):
        if self.target_connector.table_exists(schema, table):
            self.target_connector.add_missing_columns(schema, table, df)
            return
        self.target_connector.create_table_from_dataframe(schema, table, df)

    def _update_execution_progress(self):
        try:
            self.execution.completed_tables = SyncExecutionLog.objects.filter(
                execution=self.execution,
                status="completed",
            ).count()
            self.execution.total_rows_synced = (
                SyncExecutionLog.objects.filter(execution=self.execution).aggregate(
                    total=Sum("rows_inserted")
                )["total"]
                or 0
            )
            self.execution.save()
        except Exception as e:
            logger.warning(f"Error updating execution progress: {str(e)}")

    def _update_sync_state(self, endpoint_name: str, records_fetched: int, records_inserted: int):
        try:
            sync_state, created = APISyncState.objects.get_or_create(
                job=self.job,
                module_name=endpoint_name,
                defaults={
                    "last_sync_time": timezone.now(),
                    "records_synced": records_inserted,
                },
            )
            if not created:
                sync_state.last_sync_time = timezone.now()
                sync_state.records_synced = (sync_state.records_synced or 0) + records_inserted
                sync_state.save()
        except Exception as e:
            logger.warning(f"Error updating sync state for {endpoint_name}: {str(e)}")

    def _get_id_field_for_endpoint(self, endpoint_name: str) -> Optional[str]:
        for entry in SAP_DOCUMENT_TYPES:
            if entry.get("endpoint") == endpoint_name:
                return entry.get("id_field")
        return None

    def _create_error_log(self, endpoint_name: str, error_message: str):
        try:
            SyncExecutionLog.objects.create(
                execution=self.execution,
                schema_name="api",
                table_name=endpoint_name,
                status="failed",
                error_message=error_message,
                started_at=timezone.now(),
                completed_at=timezone.now(),
            )
        except Exception as e:
            logger.warning(f"Error creating error log for {endpoint_name}: {str(e)}")
