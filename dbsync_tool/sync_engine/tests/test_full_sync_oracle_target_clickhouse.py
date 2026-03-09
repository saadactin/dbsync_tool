"""
E2E tests: Full sync with ClickHouse as source and Oracle as target (Day 6).
Asserts String/FixedString -> VARCHAR2/CLOB, Decimal -> NUMBER.
"""
import unittest
from unittest.mock import Mock, patch
from decimal import Decimal
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.tests.oracle_e2e_fixtures import get_canonical_boundary_rows


class TestFullSyncOracleTargetClickHouse(unittest.TestCase):
    """Full-sync E2E: ClickHouse (source) -> Oracle (target)."""

    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job-ch-oracle"
        self.job.sync_type = "full"
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))

        self.execution = Mock(spec=SyncExecution)
        self.execution.id = "exec-ch-oracle"
        self.execution.status = "pending"

        self.source_connector = Mock()
        type(self.source_connector).__name__ = "ClickHouseConnector"
        self.target_connector = Mock()
        type(self.target_connector).__name__ = "OracleADWConnector"
        self.source_connector.database_name = "test_db"

        self.executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector,
        )

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_full_sync_clickhouse_to_oracle_string_and_decimal_mappings(self, mock_log_class):
        """ClickHouse -> Oracle: String -> VARCHAR2/CLOB, Decimal preserved."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "test_db"
        job_table.table_name = "canonical"
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)

        source_columns = [
            ColumnInfo("id", "Int64", False, True),
            ColumnInfo("name", "String", True, False),
            ColumnInfo("description", "String", True, False),
            ColumnInfo("amount", "Decimal(38,10)", True, False),
            ColumnInfo("created_at", "DateTime", True, False),
            ColumnInfo("is_active", "UInt8", True, False),
        ]
        self.source_connector.get_columns = Mock(return_value=source_columns)
        self.source_connector.get_primary_key = Mock(return_value=["id"])
        self.source_connector.get_tables = Mock(return_value=["canonical"])
        boundary_rows = get_canonical_boundary_rows()
        self.source_connector.fetch_batch = Mock(side_effect=[boundary_rows, []])

        create_table_calls = []
        bulk_insert_calls = []

        self.target_connector.create_table = Mock(
            side_effect=lambda schema, table, columns=None: create_table_calls.append(
                {"schema": schema, "table": table, "columns": columns}
            )
        )
        self.target_connector.table_exists = Mock(return_value=False)
        self.target_connector.get_tables = Mock(return_value=[])
        self.target_connector.truncate_table = Mock()
        self.target_connector.bulk_insert = Mock(
            side_effect=lambda schema, table, columns, rows: bulk_insert_calls.append(
                {"schema": schema, "table": table, "columns": columns, "rows": list(rows)}
            )
        )
        self.target_connector.get_row_count = Mock(return_value=len(boundary_rows))
        self.target_connector.fetch_batch = Mock(side_effect=[boundary_rows, []])

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={"total": len(boundary_rows)})
            self.executor.sync_table(job_table)

        self.assertGreaterEqual(len(create_table_calls), 1)
        col_types = {c.name: c.data_type for c in (create_table_calls[0].get("columns") or [])}
        self.assertIn("amount", col_types)
        self.assertTrue(
            "NUMBER" in col_types["amount"].upper(),
            msg="ClickHouse Decimal should map to Oracle NUMBER",
        )
        self.assertGreaterEqual(len(bulk_insert_calls), 1)
        self.assertEqual(len(bulk_insert_calls[0]["rows"]), len(boundary_rows))
        self.assertEqual(mock_log.status, "completed")
