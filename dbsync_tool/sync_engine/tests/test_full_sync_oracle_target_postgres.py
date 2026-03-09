"""
E2E tests: Full sync with Postgres as source and Oracle as target (Day 6).
Asserts Oracle DDL uses non-lossy type mappings and bulk_insert receives exact values.
"""
import unittest
from unittest.mock import Mock, patch
from decimal import Decimal
from datetime import datetime, timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.exceptions import TableSyncError
from sync_engine.tests.oracle_e2e_fixtures import get_canonical_boundary_rows


class TestFullSyncOracleTargetPostgres(unittest.TestCase):
    """Full-sync E2E: Postgres (source) -> Oracle (target)."""

    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job-pg-oracle"
        self.job.sync_type = "full"
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))

        self.execution = Mock(spec=SyncExecution)
        self.execution.id = "exec-pg-oracle"
        self.execution.status = "pending"

        self.source_connector = Mock()
        type(self.source_connector).__name__ = "PostgresConnector"
        self.target_connector = Mock()
        type(self.target_connector).__name__ = "OracleADWConnector"

        self.executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector,
        )

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_full_sync_postgres_to_oracle_type_mappings_and_values(self, mock_log_class):
        """Postgres -> Oracle: create_table uses safe Oracle types; bulk_insert gets exact values."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "public"
        job_table.table_name = "canonical"
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)

        # Postgres-style source columns (canonical logical schema)
        source_columns = [
            ColumnInfo("id", "integer", False, True),
            ColumnInfo("name", "character varying(255)", True, False),
            ColumnInfo("description", "text", True, False),
            ColumnInfo("amount", "numeric(38,10)", True, False),
            ColumnInfo("created_at", "timestamp with time zone", True, False),
            ColumnInfo("is_active", "boolean", True, False),
        ]
        self.source_connector.get_columns = Mock(return_value=source_columns)
        self.source_connector.get_primary_key = Mock(return_value=["id"])
        self.source_connector.get_tables = Mock(return_value=["canonical"])
        boundary_rows = get_canonical_boundary_rows()
        self.source_connector.fetch_batch = Mock(side_effect=[boundary_rows, []])

        create_table_calls = []
        bulk_insert_calls = []

        def capture_create(schema, table, columns=None):
            create_table_calls.append({"schema": schema, "table": table, "columns": columns})

        def capture_bulk_insert(schema, table, columns, rows):
            bulk_insert_calls.append({"schema": schema, "table": table, "columns": columns, "rows": list(rows)})

        self.target_connector.create_table = Mock(side_effect=capture_create)
        self.target_connector.table_exists = Mock(return_value=False)
        self.target_connector.get_tables = Mock(return_value=[])
        self.target_connector.truncate_table = Mock()
        self.target_connector.bulk_insert = Mock(side_effect=capture_bulk_insert)
        self.target_connector.get_row_count = Mock(return_value=len(boundary_rows))
        self.target_connector.fetch_batch = Mock(side_effect=[boundary_rows, []])

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={"total": len(boundary_rows)})
            self.executor.sync_table(job_table)

        self.assertGreaterEqual(len(create_table_calls), 1)
        call = create_table_calls[0]
        self.assertEqual(call["table"], "canonical")
        col_types = {c.name: c.data_type for c in (call["columns"] or [])}
        self.assertIn("amount", col_types)
        self.assertIn("NUMBER", col_types["amount"].upper(), msg="Oracle amount should be NUMBER(38,10) or similar")
        self.assertIn("description", col_types)
        self.assertTrue(
            "CLOB" in col_types["description"].upper() or "VARCHAR2" in col_types["description"].upper(),
            msg="Long text should map to CLOB or large VARCHAR2",
        )

        self.assertGreaterEqual(len(bulk_insert_calls), 1)
        insert = bulk_insert_calls[0]
        self.assertEqual(len(insert["rows"]), len(boundary_rows))
        mid_row = next((r for r in insert["rows"] if r[0] == 2), None)
        self.assertIsNotNone(mid_row)
        self.assertEqual(mid_row[3], Decimal("1234567890.1234567890"))
        self.assertEqual(mock_log.status, "completed")

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_full_sync_oracle_target_existing_narrow_schema_raises(self, mock_log_class):
        """Postgres -> Oracle: existing Oracle table with NUMBER(10,0) where NUMBER(38,10) needed raises TableCreationError."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "public"
        job_table.table_name = "narrow"
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)

        source_columns = [
            ColumnInfo("id", "integer", False, True),
            ColumnInfo("amount", "numeric(38,10)", True, False),
        ]
        self.source_connector.get_columns = Mock(return_value=source_columns)
        self.source_connector.get_primary_key = Mock(return_value=["id"])
        self.source_connector.get_tables = Mock(return_value=["narrow"])

        # Oracle table already exists with narrower column
        existing_oracle_columns = [
            ColumnInfo("id", "NUMBER", False, True),
            ColumnInfo("amount", "NUMBER(10,0)", True, False),  # too narrow
        ]
        self.target_connector.table_exists = Mock(return_value=True)
        self.target_connector.get_columns = Mock(return_value=existing_oracle_columns)
        self.target_connector.get_tables = Mock(return_value=["narrow"])

        with self.assertRaises(TableSyncError) as ctx:
            self.executor.sync_table(job_table)

        self.assertIn("amount", str(ctx.exception))
        self.assertTrue(
            "precision" in str(ctx.exception) or "smaller than required" in str(ctx.exception),
            msg="Error should mention precision or required",
        )
        self.assertEqual(mock_log.status, "failed")
