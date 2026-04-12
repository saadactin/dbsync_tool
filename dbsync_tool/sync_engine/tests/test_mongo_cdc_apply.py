import json
from unittest.mock import Mock

from django.test import TestCase
from django.contrib.auth.models import User

from accounts.models import UserProfile, Role
from connections.models import DatabaseConnection
from sync_engine.mongo_cdc_applier import apply_mongo_cdc_event_to_sql
from sync_engine.mongo_cdc_runner import MongoCdcEvent
from sync_jobs.models import MongoCdcCheckpoint, SyncJob, SyncJobTable
from connections.connectors.base import ColumnInfo


class MongoCdcApplyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mongo_apply_user", "a@example.com", "pass")
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": self.user},
        )
        self.src = DatabaseConnection.objects.create(
            name="Mongo",
            db_type="mongodb",
            host="localhost",
            port=27017,
            username="u",
            password="p",
            database_name="admin",
            created_by=self.user,
            tenant=self.user,
        )
        self.tgt = DatabaseConnection.objects.create(
            name="PG",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="u",
            password="p",
            database_name="db",
            created_by=self.user,
            tenant=self.user,
        )
        self.job = SyncJob.objects.create(
            name="Job",
            source_connection_type="database",
            source_connection=self.src,
            target_connection=self.tgt,
            sync_type="incremental",
            created_by=self.user,
            tenant=self.user,
        )

    def test_checkpoint_updates_only_after_success(self):
        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        source.flatten_document_for_sql = Mock(return_value={"_id": "1", "name": "Alice"})
        source.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "string", False, True),
                ColumnInfo("name", "string", True, False),
            ]
        )

        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.database_name = "db"
        target.table_exists = Mock(return_value=False)
        target.ensure_schema_exists = Mock()
        target.create_table = Mock()
        target.upsert_dataframe = Mock()

        evt = MongoCdcEvent(
            op="insert",
            db="appdb",
            coll="users",
            document_id="1",
            full_document={"_id": "1", "name": "Alice"},
            cluster_time=None,
            resume_token={"token": 1},
        )

        apply_mongo_cdc_event_to_sql(
            job=self.job, event=evt, source_connector=source, target_connector=target
        )
        ckpt = MongoCdcCheckpoint.objects.get(job=self.job, schema_name="appdb", table_name="users")
        self.assertEqual(json.loads(ckpt.resume_token)["token"], 1)

        # Fail apply; checkpoint must not advance.
        evt2 = MongoCdcEvent(
            op="insert",
            db="appdb",
            coll="users",
            document_id="2",
            full_document={"_id": "2", "name": "Bob"},
            cluster_time=None,
            resume_token={"token": 2},
        )
        target.upsert_dataframe.side_effect = Exception("boom")
        try:
            apply_mongo_cdc_event_to_sql(
                job=self.job, event=evt2, source_connector=source, target_connector=target
            )
        except Exception:
            pass
        ckpt.refresh_from_db()
        self.assertEqual(json.loads(ckpt.resume_token)["token"], 1)

    def test_delete_respects_no_delete_propagation(self):
        self.job.no_delete_propagation = True
        self.job.save()

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.execute_query = Mock()

        evt = MongoCdcEvent(
            op="delete",
            db="appdb",
            coll="users",
            document_id="deadbeef",
            full_document=None,
            cluster_time=None,
            resume_token={"token": 3},
        )
        apply_mongo_cdc_event_to_sql(
            job=self.job, event=evt, source_connector=source, target_connector=target
        )
        target.execute_query.assert_not_called()

    def test_cdc_schema_drift_adds_missing_columns_before_upsert(self):
        SyncJobTable.objects.create(
            job=self.job,
            schema_name="appdb",
            table_name="users",
            is_enabled=True,
            column_name_overrides={},
            excluded_columns=[],
            protected_columns=["_id"],
        )

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        source.flatten_document_for_sql = Mock(
            return_value={"_id": "1", "name": "Alice", "age": 30}
        )
        source.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "string", False, True),
                ColumnInfo("name", "string", True, False),
                ColumnInfo("age", "int", True, False),
            ]
        )

        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.database_name = "db"
        target.table_exists = Mock(return_value=True)
        target.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "TEXT", False, True),
                ColumnInfo("name", "TEXT", True, False),
            ]
        )
        target.add_missing_columns = Mock()
        target.upsert_dataframe = Mock()

        evt = MongoCdcEvent(
            op="update",
            db="appdb",
            coll="users",
            document_id="1",
            full_document={"_id": "1", "name": "Alice", "age": 30},
            cluster_time=None,
            resume_token={"token": 10},
        )

        apply_mongo_cdc_event_to_sql(
            job=self.job, event=evt, source_connector=source, target_connector=target
        )

        target.add_missing_columns.assert_called_once()
        _, _, df_missing = target.add_missing_columns.call_args[0]
        self.assertIn("age", list(df_missing.columns))
        target.upsert_dataframe.assert_called_once()

    def test_mapping_excluded_field_is_not_upserted(self):
        SyncJobTable.objects.create(
            job=self.job,
            schema_name="appdb",
            table_name="users",
            is_enabled=True,
            column_name_overrides={},
            excluded_columns=["age"],
            protected_columns=["_id"],
        )

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        source.flatten_document_for_sql = Mock(
            return_value={"_id": "1", "name": "Alice", "age": 30}
        )
        source.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "string", False, True),
                ColumnInfo("name", "string", True, False),
                ColumnInfo("age", "int", True, False),
            ]
        )

        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.database_name = "db"
        target.get_columns = Mock(
            return_value=[
                ColumnInfo("_id", "TEXT", False, True),
                ColumnInfo("name", "TEXT", True, False),
                ColumnInfo("age", "INTEGER", True, False),
            ]
        )
        target.add_missing_columns = Mock()
        target.upsert_dataframe = Mock()

        evt = MongoCdcEvent(
            op="insert",
            db="appdb",
            coll="users",
            document_id="1",
            full_document={"_id": "1", "name": "Alice", "age": 30},
            cluster_time=None,
            resume_token={"token": 11},
        )

        apply_mongo_cdc_event_to_sql(
            job=self.job, event=evt, source_connector=source, target_connector=target
        )

        df = target.upsert_dataframe.call_args[0][2]
        self.assertIn("_id", list(df.columns))
        self.assertIn("name", list(df.columns))
        self.assertNotIn("age", list(df.columns))

    def test_dedupe_skips_when_resume_token_matches_checkpoint(self):
        SyncJobTable.objects.create(
            job=self.job,
            schema_name="appdb",
            table_name="users",
            is_enabled=True,
            column_name_overrides={},
            excluded_columns=[],
            protected_columns=["_id"],
        )

        MongoCdcCheckpoint.objects.create(
            job=self.job,
            schema_name="appdb",
            table_name="users",
            resume_token=json.dumps({"token": 99}),
        )

        source = Mock()
        type(source).__name__ = "MongoDBConnector"
        source.flatten_document_for_sql = Mock(return_value={"_id": "1", "name": "Alice"})

        target = Mock()
        type(target).__name__ = "PostgresConnector"
        target.upsert_dataframe = Mock()
        target.get_columns = Mock(return_value=[ColumnInfo("_id", "TEXT", False, True)])

        evt = MongoCdcEvent(
            op="insert",
            db="appdb",
            coll="users",
            document_id="1",
            full_document={"_id": "1", "name": "Alice"},
            cluster_time=None,
            resume_token={"token": 99},
        )

        apply_mongo_cdc_event_to_sql(
            job=self.job, event=evt, source_connector=source, target_connector=target
        )

        target.upsert_dataframe.assert_not_called()
        ckpt = MongoCdcCheckpoint.objects.get(job=self.job, schema_name="appdb", table_name="users")
        self.assertEqual(json.loads(ckpt.resume_token)["token"], 99)

