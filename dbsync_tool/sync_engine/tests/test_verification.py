"""Unit tests for sync_engine.verification (parity verifier)."""
from django.test import TestCase
from django.contrib.auth.models import User

from connections.models import DatabaseConnection
from sync_engine.verification import verify_table_parity
from sync_jobs.models import SyncJob, SyncVerificationReport


class _FakeConnector:
    def __init__(self, count=0, hash_value="abc123"):
        self._count = count
        self._hash = hash_value

    def count_rows(self, schema, table, where=None):
        return self._count

    def aggregate_hash(self, schema, table, columns, where=None):
        return self._hash

    def aggregate_checksum_agg(self, schema, table, columns, where=None):
        return 12345


class _MissingHelpersConnector:
    """Simulates a connector without count_rows/aggregate_* helpers."""

    def __init__(self):
        pass


class VerifyTableParityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ver_user", password="x")
        self.conn = DatabaseConnection.objects.create(
            name="ver-source",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="x",
            password="x",
            database_name="db",
            created_by=self.user,
        )
        self.target = DatabaseConnection.objects.create(
            name="ver-target",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="x",
            password="x",
            database_name="db",
            created_by=self.user,
        )
        self.job = SyncJob.objects.create(
            name="vj",
            source_connection=self.conn,
            target_connection=self.target,
            sync_type="incremental",
            created_by=self.user,
            tenant=self.user,
            no_delete_propagation=True,
        )

    def test_full_sync_ok_when_counts_match(self):
        result = verify_table_parity(
            job=self.job,
            execution=None,
            source_connector=_FakeConnector(count=100),
            target_connector=_FakeConnector(count=100),
            source_schema="dbo",
            source_table="t1",
            target_schema="public",
            target_table="t1",
            sync_mode="full",
        )
        self.assertEqual(result.decision, "ok")
        self.assertEqual(result.source_count, 100)
        self.assertEqual(result.target_count, 100)
        self.assertEqual(SyncVerificationReport.objects.count(), 1)

    def test_full_sync_repair_full_on_count_mismatch(self):
        result = verify_table_parity(
            job=self.job,
            execution=None,
            source_connector=_FakeConnector(count=100),
            target_connector=_FakeConnector(count=99),
            source_schema="dbo",
            source_table="t1",
            target_schema="public",
            target_table="t1",
            sync_mode="full",
        )
        self.assertEqual(result.decision, "repair_full")

    def test_incremental_no_deletes_target_can_be_greater(self):
        result = verify_table_parity(
            job=self.job,
            execution=None,
            source_connector=_FakeConnector(count=50),
            target_connector=_FakeConnector(count=70),
            source_schema="dbo",
            source_table="t1",
            target_schema="public",
            target_table="t1",
            sync_mode="incremental",
            no_delete_propagation=True,
        )
        self.assertEqual(result.decision, "ok")

    def test_incremental_drift_when_target_lower(self):
        result = verify_table_parity(
            job=self.job,
            execution=None,
            source_connector=_FakeConnector(count=100),
            target_connector=_FakeConnector(count=80),
            source_schema="dbo",
            source_table="t1",
            target_schema="public",
            target_table="t1",
            sync_mode="incremental",
            no_delete_propagation=True,
        )
        self.assertEqual(result.decision, "repair_full")

    def test_warning_when_helpers_missing(self):
        result = verify_table_parity(
            job=self.job,
            execution=None,
            source_connector=_MissingHelpersConnector(),
            target_connector=_MissingHelpersConnector(),
            source_schema="dbo",
            source_table="t1",
            target_schema="public",
            target_table="t1",
            sync_mode="full",
        )
        self.assertEqual(result.decision, "warning")
