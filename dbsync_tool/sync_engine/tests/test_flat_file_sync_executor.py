from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection, FileSourceConnection
from sync_engine.flat_file_sync import FlatFileSyncExecutor
from sync_jobs.models import SyncExecution, SyncJob, SyncJobTable


class FlatFileSyncExecutorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="flat_exec_user", password="pass123")
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
        self.job = SyncJob.objects.create(
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
            job=self.job,
            schema_name="file",
            table_name="orders_import",
            is_enabled=True,
            column_name_overrides={"order id": "order_id", "customer name": "customer_name"},
        )
        self.execution = SyncExecution.objects.create(job=self.job, status="pending", total_tables=1)

    def test_happy_path_inserts_rows(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "orders.csv").write_text("Order ID,Customer Name\n1,Alice\n2,Bob\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            with override_settings(FILE_SYNC_ROOT=str(root)):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                executor.execute()
            self.assertTrue(mock_target.bulk_insert.called)
            self.execution.refresh_from_db()
            self.assertEqual(self.execution.status, "completed")

    def test_missing_file_raises(self):
        mock_target = Mock()
        mock_target.__class__.__name__ = "PostgresConnector"
        mock_target.database_name = "d"
        with TemporaryDirectory() as tmp:
            with override_settings(FILE_SYNC_ROOT=tmp):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                with self.assertRaises(Exception):
                    executor.execute()

    def test_header_only_file_fails_with_clear_message(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "orders.csv").write_text("Order ID,Customer Name\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            with override_settings(FILE_SYNC_ROOT=str(root)):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                with self.assertRaises(Exception) as exc:
                    executor.execute()
            self.assertIn("no data rows", str(exc.exception).lower())

    def test_unknown_mapping_override_key_fails_fast(self):
        job_table = self.job.tables.first()
        job_table.column_name_overrides = {"does_not_exist": "renamed_col"}
        job_table.save(update_fields=["column_name_overrides"])
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "orders.csv").write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            with override_settings(FILE_SYNC_ROOT=str(root)):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                with self.assertRaises(Exception) as exc:
                    executor.execute()
            self.assertIn("mapping contract mismatch", str(exc.exception).lower())

    def test_excluded_column_not_inserted_but_protected_forced(self):
        job_table = self.job.tables.first()
        job_table.excluded_columns = ["customer name", "order id"]
        job_table.protected_columns = ["order id"]
        job_table.save(update_fields=["excluded_columns", "protected_columns"])
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "orders.csv").write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            with override_settings(FILE_SYNC_ROOT=str(root)):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                executor.execute()
        _, kwargs = mock_target.bulk_insert.call_args
        self.assertEqual(kwargs["columns"], ["order_id"])

