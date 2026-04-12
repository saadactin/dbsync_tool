"""
MongoDB-specific unit tests for FullSyncExecutor.
"""

import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor


class TestFullSyncMongoDB(unittest.TestCase):
    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_sync_table_mongo_source_uses_document_batch_and_bulk_insert(self, mock_log_class):
        job = Mock()
        job.id = "job"
        job.sync_type = "full"

        execution = Mock()
        execution.id = "exec"

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.database_name = "db"

        executor = FullSyncExecutor(job=job, execution=execution, source_connector=source, target_connector=target)
        executor.table_handler.source_db_type = "mongodb"
        executor.table_handler.target_db_type = "postgres"

        job_table = Mock()
        job_table.schema_name = "appdb"
        job_table.table_name = "users"
        job_table.column_type_overrides = {}
        job_table.column_name_overrides = {}
        job_table.excluded_columns = []
        job_table.protected_columns = []

        mock_log = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        target.get_tables = Mock(return_value=["users"])
        target.truncate_table = Mock()
        target.bulk_insert = Mock()

        source.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "string", False, True),
                ColumnInfo("name", "string", True, False),
            ]
        )
        target.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "TEXT", False, True),
                ColumnInfo("name", "TEXT", True, False),
            ]
        )
        target.add_missing_columns = Mock()
        source.fetch_documents_batch = Mock(
            side_effect=[
                ([{"_id": "1", "name": "Alice"}, {"_id": "2", "name": "Bob"}], "2"),
                ([], "2"),
            ]
        )
        source.flatten_document_for_sql = Mock(
            side_effect=[
                {"_id": "1", "name": "Alice"},
                {"_id": "2", "name": "Bob"},
            ]
        )

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={"total": 2})
            executor.sync_table(job_table)

        target.bulk_insert.assert_called_once()

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_sync_table_mongo_source_adds_missing_columns_when_schema_drifts(self, mock_log_class):
        job = Mock()
        job.id = "job"
        job.sync_type = "full"

        execution = Mock()
        execution.id = "exec"

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.database_name = "db"

        executor = FullSyncExecutor(job=job, execution=execution, source_connector=source, target_connector=target)
        executor.table_handler.source_db_type = "mongodb"
        executor.table_handler.target_db_type = "postgres"

        job_table = Mock()
        job_table.schema_name = "appdb"
        job_table.table_name = "users"
        job_table.column_type_overrides = {}
        job_table.column_name_overrides = {}
        job_table.excluded_columns = []
        job_table.protected_columns = []

        mock_log = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        target.get_tables = Mock(return_value=["users"])
        target.truncate_table = Mock()
        target.bulk_insert = Mock()
        target.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "TEXT", False, True),
                ColumnInfo("name", "TEXT", True, False),
            ]
        )
        target.add_missing_columns = Mock()

        source.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "string", False, True),
                ColumnInfo("name", "string", True, False),
                ColumnInfo("age", "int", True, False),
            ]
        )
        source.fetch_documents_batch = Mock(side_effect=[([], None)])
        source.flatten_document_for_sql = Mock(return_value={"_id": "1", "name": "Alice", "age": 30})

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={"total": 0})
            executor.sync_table(job_table)

        target.add_missing_columns.assert_called_once()
        _, _, df_missing = target.add_missing_columns.call_args[0]
        self.assertIn("age", list(df_missing.columns))

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_sync_table_mongo_source_honors_excluded_and_rename_mapping(self, mock_log_class):
        job = Mock()
        job.id = "job"
        job.sync_type = "full"
        job.target_table_prefix = None

        execution = Mock()
        execution.id = "exec"

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.database_name = "db"

        executor = FullSyncExecutor(job=job, execution=execution, source_connector=source, target_connector=target)
        executor.table_handler.source_db_type = "mongodb"
        executor.table_handler.target_db_type = "postgres"

        job_table = Mock()
        job_table.schema_name = "appdb"
        job_table.table_name = "users"
        job_table.column_type_overrides = {}
        job_table.column_name_overrides = {"name": "customer_name"}
        job_table.excluded_columns = ["age"]
        job_table.protected_columns = ["_id"]

        mock_log = Mock()
        mock_log.save = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        target.get_tables = Mock(return_value=["users"])
        target.truncate_table = Mock()
        target.bulk_insert = Mock()
        target.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "TEXT", False, True),
                ColumnInfo("customer_name", "TEXT", True, False),
            ]
        )
        target.add_missing_columns = Mock()

        source.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "string", False, True),
                ColumnInfo("name", "string", True, False),
                ColumnInfo("age", "int", True, False),
            ]
        )
        source.fetch_documents_batch = Mock(
            side_effect=[
                ([{"_id": "1", "name": "Alice", "age": 30}], "1"),
                ([], "1"),
            ]
        )
        source.flatten_document_for_sql = Mock(return_value={"_id": "1", "name": "Alice", "age": 30})

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={"total": 1})
            executor.sync_table(job_table)

        # Ensure excluded field not included and rename applied.
        _, kwargs = target.bulk_insert.call_args
        self.assertEqual(kwargs["columns"], ["_id", "customer_name"])
        self.assertEqual(kwargs["rows"], [("1", "Alice")])

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_sync_table_mongo_source_normalizes_decimal128_and_nul_strings(self, mock_log_class):
        class FakeDecimal128:
            def __init__(self, value: str):
                self._v = Decimal(value)

            def to_decimal(self):
                return self._v

        job = Mock()
        job.id = "job"
        job.sync_type = "full"
        job.target_table_prefix = None

        execution = Mock()
        execution.id = "exec"

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.database_name = "db"

        executor = FullSyncExecutor(job=job, execution=execution, source_connector=source, target_connector=target)
        executor.table_handler.source_db_type = "mongodb"
        executor.table_handler.target_db_type = "postgres"

        job_table = Mock()
        job_table.schema_name = "appdb"
        job_table.table_name = "products"
        job_table.column_type_overrides = {}
        job_table.column_name_overrides = {}
        job_table.excluded_columns = []
        job_table.protected_columns = []

        mock_log = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        target.get_tables = Mock(return_value=["products"])
        target.truncate_table = Mock()
        target.bulk_insert = Mock()
        target.get_columns = Mock(return_value=[])
        target.add_missing_columns = Mock()

        source.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "string", False, True),
                ColumnInfo("price", "decimal", True, False),
                ColumnInfo("note", "string", True, False),
            ]
        )
        source.fetch_documents_batch = Mock(
            side_effect=[
                ([{"_id": "1", "price": FakeDecimal128("12.34"), "note": "abc\x00def"}], "1"),
                ([], "1"),
            ]
        )
        source.flatten_document_for_sql = Mock(
            return_value={"_id": "1", "price": FakeDecimal128("12.34"), "note": "abc\x00def"}
        )

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={"total": 1})
            executor.sync_table(job_table)

        _, kwargs = target.bulk_insert.call_args
        self.assertEqual(kwargs["rows"], [("1", Decimal("12.34"), "abcdef")])

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_sync_table_mongo_target_truncates_and_upserts(self, mock_log_class):
        job = Mock()
        job.id = "job"
        job.sync_type = "full"

        execution = Mock()
        execution.id = "exec"

        source = Mock()
        type(source).__name__ = "PostgresConnector"
        target = Mock()
        type(target).__name__ = "MongoDBConnector"
        target.database_name = "mongo_db"
        target.truncate_table = Mock()
        target.bulk_upsert_documents = Mock()

        executor = FullSyncExecutor(job=job, execution=execution, source_connector=source, target_connector=target)
        executor.table_handler.source_db_type = "postgres"
        executor.table_handler.target_db_type = "mongodb"

        job_table = Mock()
        job_table.schema_name = "public"
        job_table.table_name = "users"
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.transform_plan = None
        job_table.excluded_columns = []
        job_table.protected_columns = []
        job_table.column_name_overrides = {}

        mock_log = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        source.get_primary_key = Mock(return_value=["id"])
        source.get_columns = Mock(
            return_value=[
                ColumnInfo("id", "int", False, True),
                ColumnInfo("name", "varchar", True, False),
            ]
        )
        executor.query_builder.build_select_query = Mock(return_value='SELECT id,name FROM "public"."users"')
        source.fetch_batch = Mock(side_effect=[[(1, "Alice"), (2, "Bob")], []])

        with patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.aggregate = Mock(return_value={"total": 2})
            executor.sync_table(job_table)

        target.truncate_table.assert_called_once()
        target.bulk_upsert_documents.assert_called_once()

    @patch("sync_engine.full_sync.SyncExecutionLog")
    def test_sync_table_mongo_target_supports_model_transform_plan(self, mock_log_class):
        job = Mock()
        job.id = "job"
        job.sync_type = "full"

        execution = Mock()
        execution.id = "exec"

        source = Mock()
        type(source).__name__ = "PostgresConnector"
        target = Mock()
        type(target).__name__ = "MongoDBConnector"
        target.database_name = "mongo_db"
        target.truncate_table = Mock()
        target.bulk_upsert_documents = Mock()

        executor = FullSyncExecutor(job=job, execution=execution, source_connector=source, target_connector=target)
        executor.table_handler.source_db_type = "postgres"
        executor.table_handler.target_db_type = "mongodb"

        job_table = Mock()
        job_table.schema_name = "public"
        job_table.table_name = "users"
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.transform_plan = {"mode": "join"}
        job_table.excluded_columns = []
        job_table.protected_columns = []
        job_table.column_name_overrides = {}

        mock_log = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        source.fetch_batch = Mock(side_effect=[[(1, "Alice"), (2, "Bob")], []])

        with (
            patch("sync_engine.full_sync.prepare_runtime_transform_plan", return_value={"mode": "join"}),
            patch("sync_engine.full_sync.compile_select_from_plan", return_value=('SELECT id, name FROM "public"."users"', [])),
            patch("sync_engine.full_sync.runtime_output_aliases", return_value=["id", "name"]),
            patch("sync_engine.full_sync.validate_transform_plan_column_references"),
            patch("sync_engine.full_sync.SyncExecutionLog.objects.filter") as mock_filter,
        ):
            mock_filter.return_value.aggregate = Mock(return_value={"total": 2})
            executor.sync_table(job_table)

        target.truncate_table.assert_called_once()
        target.bulk_upsert_documents.assert_called_once()


if __name__ == "__main__":
    unittest.main()

