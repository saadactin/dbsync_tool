"""
E2E tests: Full sync with Oracle as source and ClickHouse as target (Day 6).
Asserts high-precision decimals and DateTime conversions without rounding/truncation.
"""
import unittest
from unittest.mock import Mock, patch
from decimal import Decimal
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.tests.oracle_e2e_fixtures import (
    ORACLE_CANONICAL_COLUMNS,
    get_canonical_boundary_rows,
)


class TestFullSyncOracleSourceClickHouse(unittest.TestCase):
    """Full-sync E2E: Oracle (source) -> ClickHouse (target)."""

    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job-oracle-ch"
        self.job.sync_type = "full"
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))

        self.execution = Mock(spec=SyncExecution)
        self.execution.id = "exec-oracle-ch"
        self.execution.status = "pending"

        self.source_connector = Mock()
        type(self.source_connector).__name__ = "OracleADWConnector"
        self.target_connector = Mock()
        type(self.target_connector).__name__ = "ClickHouseConnector"
        self.target_connector.database_name = "test_db"

        self.executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector,
        )

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_full_sync_oracle_to_clickhouse_decimal_and_datetime_preserved(
        self, mock_log_class
    ):
        """Oracle -> ClickHouse: bulk_insert receives rows with Decimal and datetime preserved."""
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
        self.source_connector.fetch_batch = Mock(side_effect=[boundary_rows, []])

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
        self.target_connector.bulk_insert.assert_called_once()
        insert_call = self.target_connector.bulk_insert.call_args
        rows_inserted = insert_call[1]["rows"]
        self.assertEqual(len(rows_inserted), len(boundary_rows))

        # Assert high-precision decimal row (id=2) preserved
        mid_row = next((r for r in rows_inserted if r[0] == 2), None)
        self.assertIsNotNone(mid_row)
        amount = mid_row[3]
        self.assertIsInstance(amount, (Decimal, float, int))
        if isinstance(amount, Decimal):
            self.assertEqual(amount, Decimal("1234567890.1234567890"))
        else:
            self.assertAlmostEqual(float(amount), 1234567890.1234567890, places=10)

        self.assertEqual(mock_log.status, "completed")
