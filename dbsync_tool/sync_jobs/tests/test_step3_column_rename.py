from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection


class Step3ColumnRenameValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.role = Role.ADMIN
        profile.tenant = self.user
        profile.save()

        self.source_connection = DatabaseConnection.objects.create(
            name="Source SQL Server",
            db_type="sqlserver",
            host="localhost",
            port=1433,
            username="u",
            password="p",
            database_name="SourceDB",
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )
        self.target_connection = DatabaseConnection.objects.create(
            name="Target ClickHouse",
            db_type="clickhouse",
            host="localhost",
            port=9000,
            username="u",
            password="p",
            database_name="TargetDB",
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )

        self.client = Client()
        self.client.force_login(self.user)

        session = self.client.session
        session["sync_job_name"] = "Test Job"
        session["sync_job_source_connection_type"] = "database"
        session["sync_job_source_connection_id"] = str(self.source_connection.id)
        session["sync_job_target_connection_id"] = str(self.target_connection.id)
        session["sync_job_selected_tables"] = [{"schema_name": "public", "table_name": "users"}]
        session.save()
        from sync_jobs.tests.wizard_helpers import seed_transform_plans_in_session

        seed_transform_plans_in_session(self.client, source_db_type="sqlserver")

    def _mock_columns(self):
        # updated_at is picked as the predicted incremental column (preferred_datetime_names).
        return [
            {"name": "id", "data_type": "int4", "is_nullable": False, "is_primary_key": True},
            {"name": "updated_at", "data_type": "timestamp", "is_nullable": True, "is_primary_key": False},
            {"name": "name", "data_type": "varchar", "is_nullable": True, "is_primary_key": False},
            {"name": "email", "data_type": "varchar", "is_nullable": True, "is_primary_key": False},
        ]

    def test_rename_non_pk_saved(self):
        table_key = "public.users"
        data = {
            f"override_colname_{table_key}.name": "customer_name",
        }

        with patch("sync_jobs.views.load_table_columns", return_value=self._mock_columns()):
            resp = self.client.post(
                reverse("sync_jobs:create_step3_submit"),
                data=data,
            )

        # Redirect to step 4 on success.
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.client.session.get("sync_job_column_name_overrides"))
        stored = self.client.session["sync_job_column_name_overrides"]
        self.assertEqual(stored[table_key]["name"], "customer_name")

    def test_rename_primary_key_blocked(self):
        table_key = "public.users"
        data = {
            f"override_colname_{table_key}.id": "identifier",
        }

        with patch("sync_jobs.views.load_table_columns", return_value=self._mock_columns()):
            resp = self.client.post(
                reverse("sync_jobs:create_step3_submit"),
                data=data,
            )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("sync_jobs:create_step3"))
        self.assertFalse(self.client.session.get("sync_job_column_name_overrides"))

    def test_rename_predicted_incremental_blocked(self):
        table_key = "public.users"
        data = {
            f"override_colname_{table_key}.updated_at": "upd",
        }

        with patch("sync_jobs.views.load_table_columns", return_value=self._mock_columns()):
            resp = self.client.post(
                reverse("sync_jobs:create_step3_submit"),
                data=data,
            )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("sync_jobs:create_step3"))
        self.assertFalse(self.client.session.get("sync_job_column_name_overrides"))

    def test_duplicate_target_names_blocked(self):
        table_key = "public.users"
        data = {
            f"override_colname_{table_key}.name": "dup",
            f"override_colname_{table_key}.email": "dup",
        }

        with patch("sync_jobs.views.load_table_columns", return_value=self._mock_columns()):
            resp = self.client.post(
                reverse("sync_jobs:create_step3_submit"),
                data=data,
            )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("sync_jobs:create_step3"))
        self.assertFalse(self.client.session.get("sync_job_column_name_overrides"))

    def test_invalid_identifier_blocked(self):
        table_key = "public.users"
        data = {
            f"override_colname_{table_key}.name": "bad-name",
        }

        with patch("sync_jobs.views.load_table_columns", return_value=self._mock_columns()):
            resp = self.client.post(
                reverse("sync_jobs:create_step3_submit"),
                data=data,
            )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("sync_jobs:create_step3"))
        self.assertFalse(self.client.session.get("sync_job_column_name_overrides"))

