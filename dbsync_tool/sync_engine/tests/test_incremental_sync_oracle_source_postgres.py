"""
E2E tests: Incremental sync with Oracle as source and Postgres as target (Day 6).
Asserts checkpoint persistence and that second run only inserts new rows (no duplicates).
"""
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, SyncCheckpoint
from connections.connectors.base import ColumnInfo
from sync_engine.incremental_sync import IncrementalSyncExecutor


class TestIncrementalSyncOracleSourcePostgres(unittest.TestCase):
    """Incremental E2E: Oracle (source) -> Postgres (target)."""

    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job-inc-oracle-pg"
        self.job.sync_type = "incremental"
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))

        self.execution = Mock(spec=SyncExecution)
        self.execution.id = "exec-inc-oracle-pg"
        self.execution.status = "pending"
        self.execution.save = Mock()

        self.source_connector = Mock()
        type(self.source_connector).__name__ = "OracleADWConnector"
        self.target_connector = Mock()
        type(self.target_connector).__name__ = "PostgresConnector"
        self.target_connector.database_name = "public"

        self.executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector,
        )

    @patch("sync_engine.incremental_sync.SyncExecutionLog")
    def test_incremental_oracle_to_postgres_checkpoint_and_no_duplicates(self, mock_log_class):
        """First run: initial batch synced and checkpoint updated. Second run: only new rows inserted."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "MYSCHEMA"
        job_table.table_name = "EVENTS"
        job_table.incremental_column = "updated_at"
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)

        ts1 = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        ts3 = datetime(2024, 6, 2, 8, 0, 0, tzinfo=timezone.utc)

        columns = [
            ColumnInfo("id", "NUMBER", False, True),
            ColumnInfo("name", "VARCHAR2(255)", True, False),
            ColumnInfo("updated_at", "TIMESTAMP WITH TIME ZONE", True, False),
        ]
        self.source_connector.get_columns = Mock(return_value=columns)
        self.source_connector.get_primary_key = Mock(return_value=["id"])
        self.source_connector.get_tables = Mock(return_value=["EVENTS"])

        batch1 = [(1, "a", ts1), (2, "b", ts2)]
        batch2_new_only = [(3, "c", ts3)]

        checkpoint_values = []
        get_checkpoint = Mock(side_effect=[None, ts2])
        create_or_update_checkpoint = Mock(
            side_effect=lambda schema_name, table_name, value: checkpoint_values.append(
                {"schema": schema_name, "table": table_name, "value": value}
            )
        )

        self.target_connector.table_exists = Mock(return_value=True)
        self.target_connector.get_tables = Mock(return_value=["EVENTS"])
        bulk_insert_calls = []
        def capture_bulk(schema, table, columns, rows):
            bulk_insert_calls.append(list(rows))
        self.target_connector.bulk_insert = Mock(side_effect=capture_bulk)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.target_connector.get_row_count = Mock(return_value=2)

        with patch.object(
            self.executor.checkpoint_manager, "get_checkpoint_value", get_checkpoint
        ), patch.object(
            self.executor.checkpoint_manager,
            "create_or_update_checkpoint",
            create_or_update_checkpoint,
        ):
            self.source_connector.fetch_batch = Mock(side_effect=[batch1, []])
            with patch("sync_engine.incremental_sync.SyncExecutionLog.objects.filter") as mock_filter:
                mock_filter.return_value.count = Mock(return_value=1)
                mock_filter.return_value.aggregate = Mock(return_value={"total": 2})
                self.executor.sync_table(job_table)

        self.assertEqual(len(bulk_insert_calls), 1)
        self.assertEqual(len(bulk_insert_calls[0]), 2)
        self.assertEqual(len(checkpoint_values), 1)
        self.assertEqual(checkpoint_values[0]["value"], ts2)

        bulk_insert_calls.clear()
        self.source_connector.fetch_batch = Mock(side_effect=[batch2_new_only, []])

        with patch.object(
            self.executor.checkpoint_manager, "get_checkpoint_value", get_checkpoint
        ), patch.object(
            self.executor.checkpoint_manager,
            "create_or_update_checkpoint",
            create_or_update_checkpoint,
        ):
            with patch("sync_engine.incremental_sync.SyncExecutionLog.objects.filter") as mock_filter:
                mock_filter.return_value.count = Mock(return_value=1)
                mock_filter.return_value.aggregate = Mock(return_value={"total": 1})
                self.executor.sync_table(job_table)

        self.assertEqual(len(bulk_insert_calls), 1)
        self.assertEqual(len(bulk_insert_calls[0]), 1)
        self.assertEqual(bulk_insert_calls[0][0][0], 3)
        self.assertEqual(bulk_insert_calls[0][0][1], "c")
