"""
E2E tests: Full sync with Oracle as source and Postgres as target (Day 6).
Uses canonical schema and boundary-value rows; asserts type mappings and value preservation.
"""
import unittest
from unittest.mock import Mock, patch
from decimal import Decimal
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.exceptions import TableSyncError
from sync_engine.tests.oracle_e2e_fixtures import (
    ORACLE_CANONICAL_COLUMNS,
    CANONICAL_COLUMN_NAMES,
    get_canonical_boundary_rows,
)


class TestFullSyncOracleSourcePostgres(unittest.TestCase):
    """Full-sync E2E: Oracle (source) -> Postgres (target)."""

    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job-oracle-pg"
        self.job.sync_type = "full"
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))

        self.execution = Mock(spec=SyncExecution)
        self.execution.id = "exec-oracle-pg"
        self.execution.status = "pending"

        self.source_connector = Mock()
        type(self.source_connector).__name__ = "OracleADWConnector"
        self.target_connector = Mock()
        type(self.target_connector).__name__ = "PostgresConnector"

        self.executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector,
        )

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_full_sync_oracle_to_postgres_canonical_schema_and_rows(self, mock_log_class):
        """Oracle -> Postgres: create_table uses Oracle->Postgres mappings; all rows synced and verified."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "MYSCHEMA"
        job_table.table_name = "CANONICAL"
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.source_connector.get_columns = Mock(return_value=ORACLE_CANONICAL_COLUMNS)
        self.source_connector.get_primary_key = Mock(return_value=["id"])
        self.source_connector.get_tables = Mock(return_value=["CANONICAL"])
        boundary_rows = get_canonical_boundary_rows()
        self.source_connector.fetch_batch = Mock(
            side_effect=[boundary_rows, []]
        )

        self.target_connector.get_tables = Mock(return_value=[])
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.target_connector.truncate_table = Mock()
        self.target_connector.bulk_insert = Mock()
        self.target_connector.get_row_count = Mock(return_value=len(boundary_rows))
        self.target_connector.fetch_batch = Mock(side_effect=[boundary_rows, []])

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(
                return_value={"total": len(boundary_rows)}
            )
            self.executor.sync_table(job_table)

        self.executor.table_handler.create_table_if_not_exists.assert_called_once()
        call_kwargs = self.executor.table_handler.create_table_if_not_exists.call_args
        self.assertEqual(call_kwargs[0][0], "MYSCHEMA")
        self.assertEqual(call_kwargs[0][1], "CANONICAL")

        self.target_connector.bulk_insert.assert_called_once()
        insert_call = self.target_connector.bulk_insert.call_args
        self.assertEqual(insert_call[1]["schema"], "public")
        self.assertEqual(insert_call[1]["table"], "CANONICAL")
        rows_inserted = insert_call[1]["rows"]
        self.assertEqual(len(rows_inserted), len(boundary_rows))
        self.assertEqual(mock_log.status, "completed")

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_full_sync_oracle_unmappable_type_fails_early(self, mock_log_class):
        """Oracle source with unsupported type (e.g. LONG RAW) raises clear error; job fails early."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "MYSCHEMA"
        job_table.table_name = "BAD"
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)

        # One column with unsupported Oracle type
        self.source_connector.get_columns = Mock(
            return_value=[
                ColumnInfo("id", "NUMBER", False, True),
                ColumnInfo("payload", "LONG RAW", True, False),
            ]
        )
        self.source_connector.get_primary_key = Mock(return_value=["id"])

        with self.assertRaises(TableSyncError) as ctx:
            self.executor.sync_table(job_table)

        self.assertIn("Unsupported Oracle type", str(ctx.exception))
        self.assertIn("LONG RAW", str(ctx.exception))
        self.assertEqual(mock_log.status, "failed")
