import unittest
from unittest.mock import Mock, patch

from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor
from sync_jobs.models import SyncExecution, SyncJob, SyncJobTable


class FullSyncColumnExclusionTests(unittest.TestCase):
    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job-id"
        self.job.sync_type = "full"
        self.execution = Mock(spec=SyncExecution)
        self.source = Mock()
        type(self.source).__name__ = "PostgresConnector"
        self.target = Mock()
        type(self.target).__name__ = "PostgresConnector"
        self.executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source,
            target_connector=self.target,
        )

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_excluded_columns_removed_from_select_and_insert(self, mock_log_class):
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = "public"
        job_table.table_name = "users"
        job_table.transformation_query = None
        job_table.column_transformations = {}
        job_table.column_type_overrides = {}
        job_table.column_name_overrides = {}
        job_table.transform_plan = None
        job_table.excluded_columns = ["email"]
        job_table.protected_columns = []

        mock_log = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.source.get_tables = Mock(return_value=["users"])
        self.source.get_primary_key = Mock(return_value=["id"])
        self.source.get_columns = Mock(
            return_value=[
                ColumnInfo("id", "int", False, True),
                ColumnInfo("name", "varchar", True, False),
                ColumnInfo("email", "varchar", True, False),
            ]
        )
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.target.truncate_table = Mock()
        self.executor.query_builder.build_select_query = Mock(return_value="SELECT x")
        self.source.execute_query_fetchall = Mock(return_value=[(1, "A")])
        self.target.bulk_insert = Mock()
        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={"total": 1})
            self.executor.sync_table(job_table)

        _, kwargs = self.executor.query_builder.build_select_query.call_args
        self.assertEqual(kwargs["columns"], ["id", "name"])
        _, bulk_kwargs = self.target.bulk_insert.call_args
        self.assertEqual(bulk_kwargs["columns"], ["id", "name"])

    def test_recreates_existing_table_when_exclusion_changes_schema(self):
        self.executor.table_handler.target_db_type = "clickhouse"
        self.executor.table_handler.target_connector = Mock()
        self.executor.table_handler.target_connector.table_exists.return_value = True
        self.executor.table_handler.target_connector.get_columns.return_value = [
            ColumnInfo("id", "Int32", False, True),
            ColumnInfo("name", "String", True, False),
            ColumnInfo("email", "String", True, False),
        ]
        self.executor.table_handler.target_connector.execute_query = Mock()
        self.executor.table_handler.target_connector.create_table = Mock()
        self.executor.table_handler.ensure_schema_exists = Mock()
        self.executor.table_handler.source_connector.get_columns = Mock(
            return_value=[
                ColumnInfo("id", "int", False, True),
                ColumnInfo("name", "varchar", True, False),
                ColumnInfo("email", "varchar", True, False),
            ]
        )
        created = self.executor.table_handler.create_table_if_not_exists(
            schema="test_db",
            table="users",
            excluded_columns=["email"],
            protected_columns=[],
        )
        self.assertTrue(created)
        self.assertTrue(self.executor.table_handler.target_connector.execute_query.called)

