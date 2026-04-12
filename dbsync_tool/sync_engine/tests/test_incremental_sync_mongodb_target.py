import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytz

from connections.connectors.base import ColumnInfo
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_engine.exceptions import TableSyncError
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog


class TestIncrementalMongoTarget(unittest.TestCase):
    def setUp(self):
        self.job = Mock(spec=SyncJob)
        self.job.id = "job"
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.target_table_prefix = None

        self.execution = Mock(spec=SyncExecution)
        self.execution.id = "exec"
        self.execution.status = "pending"

        self.source = Mock()
        type(self.source).__name__ = "PostgresConnector"

        self.target = Mock()
        type(self.target).__name__ = "MongoDBConnector"
        self.target.database_name = "mongo_db"
        self.target.table_exists = Mock(return_value=False)  # should not skip for mongo
        self.target.get_columns = Mock(return_value=[])
        self.target.add_missing_columns = Mock()
        self.target.upsert_dataframe = Mock()

        self.executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source,
            target_connector=self.target,
        )
        self.executor._prevent_concurrent_sync = Mock(return_value=True)
        self.executor.table_handler.target_db_type = "mongodb"
        self.executor.table_handler.source_db_type = "postgres"

    @patch("sync_engine.incremental_sync.SyncExecutionLog")
    def test_mongo_target_does_not_skip_when_collection_missing(self, mock_log_class):
        jt = Mock(spec=SyncJobTable)
        jt.schema_name = "public"
        jt.table_name = "users"
        jt.incremental_column = "updated_at"
        jt.transformation_query = None
        jt.column_transformations = None
        jt.transform_plan = None
        jt.excluded_columns = []
        jt.protected_columns = ["id"]  # stable key fallback
        jt.incremental_key_columns = ["id"]
        jt.column_name_overrides = {}

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = "pending"
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.source.get_primary_key = Mock(return_value=["id"])
        self.source.get_columns = Mock(
            return_value=[
                ColumnInfo("id", "int", False, True),
                ColumnInfo("updated_at", "timestamp", False, False),
            ]
        )
        self.executor.query_builder.build_incremental_query = Mock(return_value="Q")
        t0 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
        self.source.fetch_batch = Mock(side_effect=[[(1, t0), (2, t0 + timedelta(hours=1))], []])
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()

        with patch("sync_engine.incremental_sync.SyncExecutionLog.objects.filter") as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={"total": 2})
            self.executor.sync_table(jt)

        self.target.upsert_dataframe.assert_called()
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()

    @patch("sync_engine.incremental_sync.SyncExecutionLog")
    def test_mongo_target_rejects_composite_keys(self, mock_log_class):
        jt = Mock(spec=SyncJobTable)
        jt.schema_name = "public"
        jt.table_name = "users"
        jt.incremental_column = "updated_at"
        jt.transformation_query = None
        jt.column_transformations = None
        jt.transform_plan = None
        jt.excluded_columns = []
        jt.protected_columns = []
        jt.incremental_key_columns = ["id1", "id2"]
        jt.column_name_overrides = {}

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = "pending"
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.source.get_primary_key = Mock(return_value=["id1", "id2"])
        self.source.get_columns = Mock(
            return_value=[
                ColumnInfo("id1", "int", False, True),
                ColumnInfo("id2", "int", False, True),
                ColumnInfo("updated_at", "timestamp", False, False),
            ]
        )

        with self.assertRaises(TableSyncError):
            self.executor.sync_table(jt)


if __name__ == "__main__":
    unittest.main()

