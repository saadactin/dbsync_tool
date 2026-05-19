"""
PostgreSQL → ClickHouse Executor
Integrates the production engine with the sync job workflow
"""

import logging
from typing import Optional
from django.utils import timezone
from django.db import transaction

from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import DBConnector
from sync_engine.postgres_clickhouse_production import PostgresClickHouseSync
from sync_engine.exceptions import TableSyncError

logger = logging.getLogger(__name__)


class PostgresClickHouseExecutor:
    """
    Executor for PostgreSQL → ClickHouse migrations using production engine
    """

    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        source_connector: DBConnector,
        target_connector: DBConnector
    ):
        self.job = job
        self.execution = execution
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.sync_engine = PostgresClickHouseSync(job, source_connector, target_connector)

    def execute(self):
        """
        Execute PostgreSQL → ClickHouse sync
        """
        logger.info(f"Starting PostgreSQL → ClickHouse sync for job {self.job.id}")

        # Update execution status
        self.execution.status = 'running'
        self.execution.save()

        # Get enabled tables
        enabled_tables = self.job.tables.filter(is_enabled=True)

        if not enabled_tables.exists():
            logger.warning(f"No enabled tables for job {self.job.id}")
            self.execution.status = 'completed'
            self.execution.completed_at = timezone.now()
            self.execution.save()
            return

        # Process each table
        total_rows_synced = 0
        completed_tables = 0
        failed_tables = 0

        for job_table in enabled_tables:
            schema = job_table.schema_name
            table = job_table.table_name

            # Create execution log for this table
            log = SyncExecutionLog.objects.create(
                execution=self.execution,
                schema_name=schema,
                table_name=table,
                status='pending'
            )

            try:
                logger.info(f"Processing table: {schema}.{table}")

                # Update log status
                log.status = 'running'
                log.started_at = timezone.now()
                log.save()

                # Execute sync based on sync type
                if self.job.sync_type == 'full':
                    rows_synced = self._execute_full_sync(schema, table, job_table, log)
                elif self.job.sync_type == 'incremental':
                    rows_synced = self._execute_incremental_sync(schema, table, job_table, log)
                else:
                    raise TableSyncError(f"Unknown sync type: {self.job.sync_type}")

                # Update log as completed
                log.status = 'completed'
                log.completed_at = timezone.now()
                log.rows_fetched = rows_synced
                log.rows_inserted = rows_synced
                log.verification_summary = f"Rows synced: {rows_synced}, Status: SUCCESS ✓"
                log.save()

                total_rows_synced += rows_synced
                completed_tables += 1

                logger.info(f"✓ Table {schema}.{table} synced: {rows_synced} rows")

            except Exception as e:
                logger.error(f"Failed to sync table {schema}.{table}: {str(e)}", exc_info=True)

                # Update log as failed
                log.status = 'failed'
                log.completed_at = timezone.now()
                log.error_message = str(e)
                log.save()

                failed_tables += 1

        # Update execution summary
        self.execution.completed_tables = completed_tables
        self.execution.total_rows_synced = total_rows_synced

        if failed_tables > 0:
            self.execution.status = 'failed'
            self.execution.error_message = f"{failed_tables} table(s) failed to sync"
        else:
            self.execution.status = 'completed'

        self.execution.completed_at = timezone.now()
        self.execution.save()

        logger.info(
            f"✓ PostgreSQL → ClickHouse sync complete: "
            f"{completed_tables} tables, {total_rows_synced} rows, {failed_tables} failed"
        )

    def _execute_full_sync(
        self,
        schema: str,
        table: str,
        job_table: SyncJobTable,
        log: SyncExecutionLog
    ) -> int:
        """
        Execute full load for a table
        """
        logger.info(f"Full sync: {schema}.{table}")

        try:
            rows_synced = self.sync_engine.full_load(schema, table, job_table)
            return rows_synced
        except Exception as e:
            logger.error(f"Full sync failed for {schema}.{table}: {str(e)}")
            raise TableSyncError(f"Full sync failed: {str(e)}") from e

    def _execute_incremental_sync(
        self,
        schema: str,
        table: str,
        job_table: SyncJobTable,
        log: SyncExecutionLog
    ) -> int:
        """
        Execute incremental sync for a table
        """
        logger.info(f"Incremental sync: {schema}.{table}")

        try:
            rows_synced = self.sync_engine.incremental_sync(schema, table, job_table)

            # Optionally sync deletes (soft delete)
            if not self.job.no_delete_propagation:
                deleted_rows = self.sync_engine.sync_deletes(schema, table, job_table)
                logger.info(f"Soft deleted {deleted_rows} rows in {schema}.{table}")

            return rows_synced
        except Exception as e:
            logger.error(f"Incremental sync failed for {schema}.{table}: {str(e)}")
            raise TableSyncError(f"Incremental sync failed: {str(e)}") from e
