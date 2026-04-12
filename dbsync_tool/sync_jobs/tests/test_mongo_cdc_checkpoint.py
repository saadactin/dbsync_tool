from django.test import TestCase
from django.contrib.auth.models import User
from django.db.utils import IntegrityError

from accounts.models import UserProfile, Role
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, MongoCdcCheckpoint


class MongoCdcCheckpointModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mongo_ckpt_user", "m@example.com", "pass")
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

    def test_unique_constraint(self):
        MongoCdcCheckpoint.objects.create(
            job=self.job, schema_name="appdb", table_name="users", resume_token="{}"
        )
        with self.assertRaises(IntegrityError):
            MongoCdcCheckpoint.objects.create(
                job=self.job, schema_name="appdb", table_name="users", resume_token="{}"
            )

