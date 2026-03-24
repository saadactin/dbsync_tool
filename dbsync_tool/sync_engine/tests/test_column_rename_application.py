import unittest
from unittest.mock import Mock, patch, MagicMock

from connections.connectors.base import ColumnInfo
from sync_engine.table_handler import TableHandler
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.incremental_sync import IncrementalSyncExecutor


class TestColumnRenameApplication(unittest.TestCase):
    def test_table_handler_applies_column_name_overrides_to_target_ddl(self):
        source = Mock()
        target = Mock()
        source.__class__.__name__ = "PostgresConnector"
        target.__class__.__name__ = "PostgresConnector"

        # Ensure target table does not exist -> create_table path.
        target.table_exists = Mock(return_value=False)
        target.ensure_schema_exists = Mock()
        target.create_table = Mock()

        source.get_columns = Mock(
            return_value=[
                ColumnInfo(name="id", data_type="int4", is_nullable=False, is_primary_key=True, max_length=None),
                ColumnInfo(name="name", data_type="text", is_nullable=True, is_primary_key=False, max_length=None),
            ]
        )

        handler = TableHandler(source, target)
        created = handler.create_table_if_not_exists(
            schema="public",
            table="users",
            column_name_overrides={"name": "customer_name"},
        )
        self.assertTrue(created)

        target.create_table.assert_called_once()
        created_columns = target.create_table.call_args[0][2]
        created_col_names = [c.name for c in created_columns]
        self.assertIn("customer_name", created_col_names)
        self.assertNotIn("name", created_col_names)

    def test_full_sync_bulk_insert_uses_target_column_names(self):
        source = Mock()
        target = Mock()
        source.__class__.__name__ = "PostgresConnector"
        target.__class__.__name__ = "PostgresConnector"

        # FullSyncExecutor checks PKs for keyset pagination; return none to use OFFSET/FETCH.
        source.get_primary_key = Mock(return_value=[])

        source_columns = [
            ColumnInfo(name="id", data_type="int4", is_nullable=False, is_primary_key=True, max_length=None),
            ColumnInfo(name="name", data_type="text", is_nullable=True, is_primary_key=False, max_length=None),
            ColumnInfo(name="updated_at", data_type="timestamp", is_nullable=True, is_primary_key=False, max_length=None),
        ]
        source.get_columns = Mock(return_value=source_columns)

        batch = [(1, "Alice", "2026-01-01 00:00:00")]
        source.fetch_batch = Mock(side_effect=[batch, []])

        target.get_tables = Mock(return_value=[])  # avoid truncate_table
        target.bulk_insert = Mock()

        job = Mock()
        job.target_table_prefix = None

        execution = Mock()
        execution.save = Mock()

        executor = FullSyncExecutor(job=job, execution=execution, source_connector=source, target_connector=target)
        executor.table_handler.create_table_if_not_exists = Mock(return_value=True)

        # Keep sync lightweight: bypass transformations + pre-migration validation.
        executor._validate_and_apply_transformations = Mock(side_effect=lambda **kwargs: (kwargs["base_query"], None))
        executor._execute_pre_migration_validation = Mock(return_value=(True, None, None))
        executor.query_builder.build_select_query = Mock(return_value="SELECT_QUERY")

        log_mock = Mock()
        log_mock.save = Mock()

        with patch("sync_engine.full_sync.SyncExecutionLog") as sync_execution_log_cls:
            sync_execution_log_cls.objects.create.return_value = log_mock
            sync_execution_log_cls.objects.filter.return_value.count.return_value = 0
            sync_execution_log_cls.objects.filter.return_value.aggregate.return_value = {"total": 0}

            job_table = Mock()
            job_table.schema_name = "public"
            job_table.table_name = "users"
            job_table.transformation_query = None
            job_table.column_transformations = {}
            job_table.column_type_overrides = {}
            job_table.column_name_overrides = {"name": "customer_name"}

            executor.sync_table(job_table=job_table)

        # bulk_insert called with TARGET columns, not SOURCE columns
        _, kwargs = target.bulk_insert.call_args
        self.assertEqual(kwargs["columns"], ["id", "customer_name", "updated_at"])

    def test_incremental_upsert_batch_uses_target_column_names(self):
        target = Mock()
        target.upsert_dataframe = Mock()

        executor = IncrementalSyncExecutor.__new__(IncrementalSyncExecutor)
        executor.target_connector = target

        rows = [(1, "customer_A")]
        executor._upsert_batch_with_retry(
            schema="public",
            table="users",
            columns=["id", "customer_name"],  # TARGET columns
            rows=rows,
            key_columns=["id"],
        )

        _, kwargs = target.upsert_dataframe.call_args
        df = kwargs["df"]
        self.assertEqual(list(df.columns), ["id", "customer_name"])
        self.assertEqual(kwargs["key_column"], "id")


if __name__ == "__main__":
    unittest.main()

