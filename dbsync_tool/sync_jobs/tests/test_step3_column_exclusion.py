from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection


class Step3ColumnExclusionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="step3_excl_user", password="pass123")
        UserProfile.objects.update_or_create(
            user=self.user, defaults={"role": Role.ADMIN, "tenant": self.user}
        )
        self.source = DatabaseConnection.objects.create(
            name="Source DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="u",
            password="p",
            database_name="s",
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )
        self.target = DatabaseConnection.objects.create(
            name="Target DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="u",
            password="p",
            database_name="t",
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session["sync_job_name"] = "Excl Job"
        session["sync_job_source_connection_type"] = "database"
        session["sync_job_source_connection_id"] = str(self.source.id)
        session["sync_job_target_connection_id"] = str(self.target.id)
        session["sync_job_selected_tables"] = [{"schema_name": "public", "table_name": "users"}]
        session.save()
        from sync_jobs.tests.wizard_helpers import seed_transform_plans_in_session

        seed_transform_plans_in_session(self.client, source_db_type="postgres")

    @staticmethod
    def _columns():
        return [
            {"name": "id", "data_type": "int4", "is_nullable": False, "is_primary_key": True},
            {"name": "created_at", "data_type": "timestamp", "is_nullable": True, "is_primary_key": False},
            {"name": "name", "data_type": "varchar", "is_nullable": True, "is_primary_key": False},
            {"name": "email", "data_type": "varchar", "is_nullable": True, "is_primary_key": False},
        ]

    def test_explicit_non_protected_exclude_persists(self):
        table_key = "public.users"
        payload = {
            f"migrate_present_{table_key}.id": "1",
            f"migrate_col_{table_key}.id": "1",
            f"migrate_present_{table_key}.created_at": "1",
            f"migrate_col_{table_key}.created_at": "1",
            f"migrate_present_{table_key}.name": "1",
            f"migrate_present_{table_key}.email": "1",
            f"migrate_col_{table_key}.email": "1",
        }
        with patch("sync_jobs.views.load_table_columns", return_value=self._columns()):
            resp = self.client.post(reverse("sync_jobs:create_step3_submit"), data=payload)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("sync_jobs:create_step4"))
        excluded = self.client.session.get("sync_job_excluded_columns", {})
        self.assertEqual(excluded.get(table_key), ["name"])

    def test_protected_column_cannot_be_excluded(self):
        table_key = "public.users"
        payload = {
            f"migrate_present_{table_key}.id": "1",
            f"migrate_present_{table_key}.created_at": "1",
            f"migrate_col_{table_key}.created_at": "1",
            f"migrate_present_{table_key}.name": "1",
            f"migrate_col_{table_key}.name": "1",
            f"migrate_present_{table_key}.email": "1",
            f"migrate_col_{table_key}.email": "1",
        }
        with patch("sync_jobs.views.load_table_columns", return_value=self._columns()):
            resp = self.client.post(reverse("sync_jobs:create_step3_submit"), data=payload)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("sync_jobs:create_step3"))

