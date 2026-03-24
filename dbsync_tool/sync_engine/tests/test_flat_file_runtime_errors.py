from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection, FileSourceConnection
from sync_engine.flat_file_sync import FlatFileSyncExecutor
from sync_jobs.models import SyncExecution, SyncJob, SyncJobTable


class FlatFileRuntimeErrorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="flat_runtime_user", password="pass123")
        UserProfile.objects.update_or_create(
            user=self.user, defaults={"role": Role.ADMIN, "tenant": self.user}
        )
        self.target_conn = DatabaseConnection.objects.create(
            name="Target DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="u",
            password="p",
            database_name="d",
            created_by=self.user,
            tenant=self.user,
        )
        self.file_source = FileSourceConnection.objects.create(
            name="CSV Source",
            relative_path="orders.csv",
            delimiter=",",
            encoding="utf-8",
            has_header=True,
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )

    def _build_job(self, overrides):
        job = SyncJob.objects.create(
            name="Flat Runtime Job",
            source_file_connection=self.file_source,
            source_connection_type="flat_file",
            target_connection=self.target_conn,
            sync_type="full",
            status="pending",
            created_by=self.user,
            tenant=self.user,
        )
        SyncJobTable.objects.create(
            job=job,
            schema_name="file",
            table_name="orders_import",
            is_enabled=True,
            column_name_overrides=overrides,
        )
        execution = SyncExecution.objects.create(job=job, status="pending", total_tables=1)
        return job, execution

    def test_inactive_file_source_fails(self):
        self.file_source.is_active = False
        self.file_source.save(update_fields=["is_active"])
        job, execution = self._build_job({"order id": "order_id"})
        target = Mock()
        target.__class__.__name__ = "PostgresConnector"
        with self.assertRaises(Exception) as exc:
            FlatFileSyncExecutor(job, execution, target).execute()
        self.assertIn("inactive", str(exc.exception).lower())

    def test_duplicate_renamed_columns_case_insensitive_fails(self):
        job, execution = self._build_job({"order id": "ID", "customer name": "id"})
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "orders.csv").write_text("Order ID,Customer Name\n1,A\n", encoding="utf-8")
            target = Mock()
            target.__class__.__name__ = "PostgresConnector"
            target.database_name = "d"
            target.table_exists.return_value = False
            with override_settings(FILE_SYNC_ROOT=str(root)):
                with self.assertRaises(Exception) as exc:
                    FlatFileSyncExecutor(job, execution, target).execute()
        self.assertIn("duplicate target column mapping", str(exc.exception).lower())

