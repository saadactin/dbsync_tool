from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection, FileSourceConnection
from sync_engine.flat_file_hashing import compute_row_hash
from sync_engine.flat_file_sync import FlatFileSyncExecutor
from sync_jobs.models import (
    FlatFileIngestionControl,
    SyncCheckpoint,
    SyncExecution,
    SyncJob,
    SyncJobTable,
)


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

    def test_incremental_does_not_truncate_and_uses_upsert_dataframe(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 120
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])

        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.save(update_fields=["incremental_key_columns"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n2,Bob\n", encoding="utf-8")

            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()

            with override_settings(FILE_SYNC_ROOT=str(root)):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                executor.execute()

        mock_target.truncate_table.assert_not_called()
        self.assertTrue(mock_target.upsert_dataframe.called)
        self.assertTrue(
            SyncCheckpoint.objects.filter(
                job=self.job, schema_name="file", table_name="orders_import"
            ).exists()
        )

    def test_incremental_skips_when_file_mtime_before_checkpoint_lower_bound(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 120
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])

        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.save(update_fields=["incremental_key_columns"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")
            file_mtime = p.stat().st_mtime

            # If checkpoint is newer than file mtime + overlap, incremental run should skip.
            checkpoint_dt = datetime.fromtimestamp(file_mtime + 600, tz=timezone.utc)
            SyncCheckpoint.objects.update_or_create(
                job=self.job,
                schema_name="file",
                table_name="orders_import",
                defaults={"last_value": checkpoint_dt.isoformat()},
            )

            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()

            with override_settings(FILE_SYNC_ROOT=str(root)):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                executor.execute()

        mock_target.truncate_table.assert_not_called()
        mock_target.upsert_dataframe.assert_not_called()

    def test_incremental_none_string_checkpoint_treated_as_missing(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 120
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])

        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.save(update_fields=["incremental_key_columns"])

        SyncCheckpoint.objects.update_or_create(
            job=self.job,
            schema_name="file",
            table_name="orders_import",
            defaults={"last_value": "none"},
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")

            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()

            with override_settings(FILE_SYNC_ROOT=str(root)):
                executor = FlatFileSyncExecutor(self.job, self.execution, mock_target)
                executor.execute()

        mock_target.truncate_table.assert_not_called()
        mock_target.upsert_dataframe.assert_called()

    def test_incremental_duplicate_keys_across_runs_uses_upsert(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])
        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.save(update_fields=["incremental_key_columns"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n2,Bob\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()

            with override_settings(FILE_SYNC_ROOT=str(root)):
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()
                p.write_text("Order ID,Customer Name\n1,Alice Updated\n2,Bob\n", encoding="utf-8")
                self.execution = SyncExecution.objects.create(job=self.job, status="pending", total_tables=1)
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()

        self.assertGreaterEqual(mock_target.upsert_dataframe.call_count, 2)
        mock_target.truncate_table.assert_not_called()

    def test_incremental_missing_rows_in_new_file_do_not_propagate_delete(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])
        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.save(update_fields=["incremental_key_columns"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n2,Bob\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()
            mock_target.execute_query = Mock()

            with override_settings(FILE_SYNC_ROOT=str(root)):
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()
                p.write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")
                self.execution = SyncExecution.objects.create(job=self.job, status="pending", total_tables=1)
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()

        mock_target.truncate_table.assert_not_called()
        mock_target.execute_query.assert_not_called()

    def test_incremental_soak_three_runs_checkpoint_monotonic(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])
        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.save(update_fields=["incremental_key_columns"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()

            with override_settings(FILE_SYNC_ROOT=str(root)):
                p.write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()
                cp1 = SyncCheckpoint.objects.get(job=self.job, schema_name="file", table_name="orders_import").last_value

                p.write_text("Order ID,Customer Name\n1,Alice v2\n", encoding="utf-8")
                self.execution = SyncExecution.objects.create(job=self.job, status="pending", total_tables=1)
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()
                cp2 = SyncCheckpoint.objects.get(job=self.job, schema_name="file", table_name="orders_import").last_value

                p.write_text("Order ID,Customer Name\n1,Alice v3\n", encoding="utf-8")
                self.execution = SyncExecution.objects.create(job=self.job, status="pending", total_tables=1)
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()
                cp3 = SyncCheckpoint.objects.get(job=self.job, schema_name="file", table_name="orders_import").last_value

        self.assertTrue(cp1 <= cp2 <= cp3)

    def test_hybrid_same_file_hash_is_skipped_by_control_table(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])
        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.flat_file_incremental_mode = "hybrid_hash_control"
        job_table.save(update_fields=["incremental_key_columns", "flat_file_incremental_mode"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n2,Bob\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()
            mock_target.fetch_batch.return_value = []

            with override_settings(FILE_SYNC_ROOT=str(root)):
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()
                self.execution = SyncExecution.objects.create(job=self.job, status="pending", total_tables=1)
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()

        self.assertEqual(
            FlatFileIngestionControl.objects.filter(
                job=self.job,
                schema_name="file",
                table_name="orders_import",
                status="success",
            ).count(),
            1,
        )
        self.assertEqual(mock_target.upsert_dataframe.call_count, 1)

    def test_hybrid_changed_file_upserts_only_changed_rows(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])
        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.flat_file_incremental_mode = "hybrid_hash_control"
        job_table.save(update_fields=["incremental_key_columns", "flat_file_incremental_mode"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice v2\n2,Bob\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()
            existing_bob_hash = compute_row_hash(
                {"Order ID": "2", "Customer Name": "Bob"},
                columns=["Order ID", "Customer Name"],
                algorithm="sha256",
            )
            # Existing target has key=2 with same hash as incoming row for Bob.
            mock_target.fetch_batch.side_effect = [
                [("1", "oldhash"), ("2", existing_bob_hash)],
                [],
            ]

            with override_settings(FILE_SYNC_ROOT=str(root)):
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()

        _, kwargs = mock_target.upsert_dataframe.call_args
        self.assertEqual(len(kwargs["df"]), 1)
        self.assertEqual(
            FlatFileIngestionControl.objects.filter(
                job=self.job,
                schema_name="file",
                table_name="orders_import",
                status="success",
            ).count(),
            1,
        )

    def test_hybrid_without_key_fails_when_hash_only_not_allowed(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])
        job_table = self.job.tables.first()
        job_table.incremental_key_columns = []
        job_table.protected_columns = []
        job_table.flat_file_incremental_mode = "hybrid_hash_control"
        job_table.flat_file_allow_hash_only_without_key = False
        job_table.save(
            update_fields=[
                "incremental_key_columns",
                "protected_columns",
                "flat_file_incremental_mode",
                "flat_file_allow_hash_only_without_key",
            ]
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "PostgresConnector"
            mock_target.database_name = "d"
            mock_target.table_exists.return_value = False
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()
            mock_target.fetch_batch.return_value = []

            with override_settings(FILE_SYNC_ROOT=str(root)):
                with self.assertRaises(Exception) as exc:
                    FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()

        self.assertIn("stable upsert key", str(exc.exception).lower())

    def test_hybrid_sqlserver_target_uses_sqlserver_identifier_style(self):
        self.job.sync_type = "incremental"
        self.job.no_delete_propagation = True
        self.job.incremental_overlap_seconds = 0
        self.job.save(update_fields=["sync_type", "no_delete_propagation", "incremental_overlap_seconds"])
        job_table = self.job.tables.first()
        job_table.incremental_key_columns = ["Order ID"]
        job_table.flat_file_incremental_mode = "hybrid_hash_control"
        job_table.save(update_fields=["incremental_key_columns", "flat_file_incremental_mode"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "orders.csv"
            p.write_text("Order ID,Customer Name\n1,Alice\n", encoding="utf-8")
            mock_target = Mock()
            mock_target.__class__.__name__ = "SQLServerConnector"
            mock_target.database_name = "SmartphoneDB"
            mock_target.table_exists.return_value = True
            mock_target.upsert_dataframe = Mock()
            mock_target.truncate_table = Mock()
            # query probe for existing key hashes (returns empty set)
            mock_target.fetch_batch.side_effect = [[], []]

            with override_settings(FILE_SYNC_ROOT=str(root)):
                FlatFileSyncExecutor(self.job, self.execution, mock_target).execute()

        self.assertTrue(mock_target.fetch_batch.called)
        first_query = mock_target.fetch_batch.call_args_list[0].kwargs.get("query", "")
        self.assertIn("[dbo].[orders_import]", first_query)
        self.assertIn("[order_id]", first_query)
        self.assertIn("[row_hash]", first_query)

