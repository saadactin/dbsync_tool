"""
E2E tests: Incremental sync with Postgres as source and Oracle as target (Day 6).
Asserts checkpoints use Postgres incremental column and Oracle bulk_insert receives correct values.
"""
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.incremental_sync import IncrementalSyncExecutor


class TestIncrementalSyncOracleTargetPostgres(unittest.TestCase):
    """Incremental E2E: Postgres (source) -> Oracle (target)."""

    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job-inc-pg-oracle"
        self.job.sync_type = "incremental"
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))

        self.execution = Mock(spec=SyncExecution)
        self.execution.id = "exec-inc-pg-oracle"
        self.execution.status = "pending"
        self.execution.save = Mock()

        self.source_connector = Mock()
        type(self.source_connector).__name__ = "PostgresConnector"
        self.target_connector = Mock()
        type(self.target_connector).__name__ = "OracleADWConnector"

        self.executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector,
        )

    @patch("sync_engine.incremental_sync.SyncExecutionLog")
    def test_incremental_postgres_to_oracle_checkpoint_and_bulk_insert_values(self, mock_log_class):
        """Postgres -> Oracle: first sync inserts rows; bulk_insert receives incremental column values correctly."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "public"
        job_table.table_name = "events"
        job_table.incremental_column = "updated_at"
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)

        ts1 = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        columns = [
            ColumnInfo("id", "integer", False, True),
            ColumnInfo("name", "character varying(255)", True, False),
            ColumnInfo("updated_at", "timestamp with time zone", True, False),
        ]
        self.source_connector.get_columns = Mock(return_value=columns)
        self.source_connector.get_primary_key = Mock(return_value=["id"])
        self.source_connector.get_tables = Mock(return_value=["events"])

        batch = [(1, "a", ts1), (2, "b", ts2)]
        self.source_connector.fetch_batch = Mock(side_effect=[batch, []])

        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()

        self.target_connector.table_exists = Mock(return_value=True)
        self.target_connector.get_tables = Mock(return_value=["events"])
        bulk_insert_rows = []
        def capture_bulk(schema, table, columns, rows):
            bulk_insert_rows.extend(list(rows))
        self.target_connector.bulk_insert = Mock(side_effect=capture_bulk)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.target_connector.get_row_count = Mock(return_value=2)

        with patch("sync_engine.incremental_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={"total": 2})
            self.executor.sync_table(job_table)

        self.assertEqual(len(bulk_insert_rows), 2)
        self.assertEqual(bulk_insert_rows[0][2], ts1)
        self.assertEqual(bulk_insert_rows[1][2], ts2)
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()
        call_kw = self.executor.checkpoint_manager.create_or_update_checkpoint.call_args[1]
        self.assertEqual(call_kw["value"], ts2)
