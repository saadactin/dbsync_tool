"""Tests for the Day-1 reliability + DQ data layer.

Covers:
- new fields exist with the documented defaults
- ProcessedBatch unique-per-(execution, schema, table, batch_id) constraint
- ReconciliationReport unique-per-(execution, schema, table) constraint
- SyncDeadLetterRow inserts succeed and are retrievable by every indexed lookup
- the data backfill rules baked into the migration: existing checkpoints get
  ``last_seen_value == last_committed_value == last_value`` and
  ``checkpoint_status == 'clean'``; SyncJobTable rows get the canonical
  default retry policy when their ``retry_policy`` was empty.

The reliability exception classes are smoke-tested too so importers in
later days can rely on stable types.
"""

from django.contrib.auth.models import User
from django.db.utils import IntegrityError
from django.test import TestCase

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_engine.reliability import (
    DeadLetterRowError,
    FatalSyncError,
    IdempotencyViolation,
    TransientSyncError,
)
from sync_engine.exceptions import SyncExecutionError
from sync_jobs.models import (
    ProcessedBatch,
    ReconciliationReport,
    SyncCheckpoint,
    SyncDeadLetterRow,
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
    SyncJobTable,
    SyncVerificationReport,
    default_retry_policy,
)


def _make_user_and_conns(prefix):
    user = User.objects.create_user(
        f"{prefix}_user", f"{prefix}@example.com", "pass"
    )
    UserProfile.objects.update_or_create(
        user=user,
        defaults={"role": Role.ADMIN, "tenant": user},
    )
    src = DatabaseConnection.objects.create(
        name=f"{prefix}-src",
        db_type="postgres",
        host="localhost",
        port=5432,
        username="u",
        password="p",
        database_name="db",
        created_by=user,
        tenant=user,
    )
    tgt = DatabaseConnection.objects.create(
        name=f"{prefix}-tgt",
        db_type="postgres",
        host="localhost",
        port=5432,
        username="u",
        password="p",
        database_name="db2",
        created_by=user,
        tenant=user,
    )
    return user, src, tgt


class ReliabilityFieldDefaultsTests(TestCase):
    """Verify Day-1 fields exist with documented defaults."""

    def setUp(self):
        self.user, self.src, self.tgt = _make_user_and_conns("rel_defaults")
        self.job = SyncJob.objects.create(
            name="DefaultsJob",
            source_connection_type="database",
            source_connection=self.src,
            target_connection=self.tgt,
            sync_type="incremental",
            created_by=self.user,
            tenant=self.user,
        )

    def test_syncjobtable_defaults(self):
        tbl = SyncJobTable.objects.create(
            job=self.job, schema_name="public", table_name="orders"
        )
        # JSONField default=dict gives {} on a brand-new row; the data
        # backfill in the migration only fires for existing rows. Operators
        # can either rely on the ``default_retry_policy()`` factory at
        # write-time or have it auto-applied later by Day-3 wiring.
        self.assertEqual(tbl.retry_policy, {})
        self.assertAlmostEqual(tbl.dead_letter_max_pct, 0.001)

    def test_default_retry_policy_factory_shape(self):
        policy = default_retry_policy()
        self.assertEqual(policy["max_retries"], 3)
        self.assertEqual(policy["initial_delay"], 1.0)
        self.assertEqual(policy["backoff"], 2.0)
        self.assertEqual(
            sorted(policy["retryable_errors"]),
            sorted(["timeout", "conn_reset", "deadlock"]),
        )

    def test_synccheckpoint_defaults(self):
        cp = SyncCheckpoint.objects.create(
            job=self.job,
            schema_name="public",
            table_name="orders",
            last_value="42",
        )
        # New rows do not auto-populate dual pointers; only the migration
        # backfill does that for *existing* rows. The status default still
        # has to be 'clean'.
        self.assertIsNone(cp.last_seen_value)
        self.assertIsNone(cp.last_committed_value)
        self.assertEqual(cp.checkpoint_status, "clean")
        self.assertIsNone(cp.last_successful_batch_id)
        self.assertIsNone(cp.last_status_reason)

    def test_syncexecutionlog_defaults(self):
        execution = SyncExecution.objects.create(job=self.job)
        log = SyncExecutionLog.objects.create(
            execution=execution,
            schema_name="public",
            table_name="orders",
        )
        self.assertEqual(log.attempts, 0)
        self.assertIsNone(log.last_error_code)
        self.assertEqual(log.dead_letter_count, 0)

    def test_syncverificationreport_metrics_default(self):
        execution = SyncExecution.objects.create(job=self.job)
        report = SyncVerificationReport.objects.create(
            job=self.job,
            execution=execution,
            schema_name="public",
            table_name="orders",
        )
        self.assertEqual(report.metrics_json, {})


class ProcessedBatchTests(TestCase):
    def setUp(self):
        self.user, self.src, self.tgt = _make_user_and_conns("rel_pb")
        self.job = SyncJob.objects.create(
            name="PBJob",
            source_connection_type="database",
            source_connection=self.src,
            target_connection=self.tgt,
            sync_type="full",
            created_by=self.user,
            tenant=self.user,
        )
        self.execution = SyncExecution.objects.create(job=self.job)

    def test_unique_per_run(self):
        ProcessedBatch.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            batch_id="b1",
        )
        with self.assertRaises(IntegrityError):
            ProcessedBatch.objects.create(
                job=self.job,
                execution=self.execution,
                schema_name="public",
                table_name="orders",
                batch_id="b1",
            )

    def test_same_batch_id_different_execution_allowed(self):
        ProcessedBatch.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            batch_id="b1",
        )
        # A second execution of the same job re-using batch_id "b1" is fine -
        # idempotency is scoped per-execution, not per-job.
        execution2 = SyncExecution.objects.create(job=self.job)
        ProcessedBatch.objects.create(
            job=self.job,
            execution=execution2,
            schema_name="public",
            table_name="orders",
            batch_id="b1",
        )
        self.assertEqual(
            ProcessedBatch.objects.filter(batch_id="b1").count(),
            2,
        )

    def test_default_status_started(self):
        pb = ProcessedBatch.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            batch_id="b9",
        )
        self.assertEqual(pb.status, "started")
        self.assertEqual(pb.row_count, 0)
        self.assertIsNone(pb.committed_at)


class SyncDeadLetterRowTests(TestCase):
    def setUp(self):
        self.user, self.src, self.tgt = _make_user_and_conns("rel_dlr")
        self.job = SyncJob.objects.create(
            name="DLRJob",
            source_connection_type="database",
            source_connection=self.src,
            target_connection=self.tgt,
            sync_type="full",
            created_by=self.user,
            tenant=self.user,
        )
        self.execution = SyncExecution.objects.create(job=self.job)

    def test_insert_and_lookup_paths(self):
        for i in range(3):
            SyncDeadLetterRow.objects.create(
                job=self.job,
                execution=self.execution,
                schema_name="public",
                table_name="orders",
                batch_id=f"b{i}",
                source_pk_text=str(i),
                source_row_hash=f"hash{i}",
                raw_row_json={"id": i, "name": f"row{i}"},
                error_code="ROW_PARSE_ERROR" if i % 2 == 0 else "ROW_TYPE_ERROR",
                error_message=f"failure {i}",
            )
        self.assertEqual(
            SyncDeadLetterRow.objects.filter(execution=self.execution).count(),
            3,
        )
        self.assertEqual(
            SyncDeadLetterRow.objects.filter(error_code="ROW_PARSE_ERROR").count(),
            2,
        )
        self.assertEqual(
            SyncDeadLetterRow.objects.filter(
                execution=self.execution,
                schema_name="public",
                table_name="orders",
            ).count(),
            3,
        )


class ReconciliationReportTests(TestCase):
    def setUp(self):
        self.user, self.src, self.tgt = _make_user_and_conns("rel_recon")
        self.job = SyncJob.objects.create(
            name="ReconJob",
            source_connection_type="database",
            source_connection=self.src,
            target_connection=self.tgt,
            sync_type="full",
            created_by=self.user,
            tenant=self.user,
        )
        self.execution = SyncExecution.objects.create(job=self.job)

    def test_unique_per_execution_and_table(self):
        ReconciliationReport.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
        )
        with self.assertRaises(IntegrityError):
            ReconciliationReport.objects.create(
                job=self.job,
                execution=self.execution,
                schema_name="public",
                table_name="orders",
            )

    def test_defaults(self):
        report = ReconciliationReport.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
        )
        self.assertEqual(report.decision, "ok")
        self.assertEqual(report.confidence, 1.0)
        for json_field in (
            report.source_metrics_json,
            report.target_metrics_json,
            report.drift_json,
            report.dq_pre_json,
            report.dq_post_json,
            report.snapshots_json,
        ):
            self.assertEqual(json_field, {})


class CheckpointBackfillTests(TestCase):
    """Replay the data migration to confirm the dual-pointer backfill rule.

    The migration runs against pre-existing rows. In tests the schema is
    already at HEAD, so we manually invoke the same backfill function to
    prove it does the right thing for rows that are missing the new
    pointers.
    """

    def setUp(self):
        self.user, self.src, self.tgt = _make_user_and_conns("rel_backfill")
        self.job = SyncJob.objects.create(
            name="BackfillJob",
            source_connection_type="database",
            source_connection=self.src,
            target_connection=self.tgt,
            sync_type="incremental",
            created_by=self.user,
            tenant=self.user,
        )

    def test_checkpoint_pointers_backfill(self):
        # The migration module starts with a digit so it can only be loaded
        # via ``importlib.import_module`` (Python's ``import`` statement
        # rejects identifiers starting with a digit).
        import importlib

        migration_mod = importlib.import_module(
            "sync_jobs.migrations.0031_reliability_dq_foundations"
        )

        # Existing-row simulation: dual pointers are NULL, status looks empty.
        cp = SyncCheckpoint.objects.create(
            job=self.job,
            schema_name="public",
            table_name="orders",
            last_value="2026-01-01T00:00:00Z",
        )
        SyncCheckpoint.objects.filter(pk=cp.pk).update(
            last_seen_value=None,
            last_committed_value=None,
        )

        # Apps shim minimally compatible with what the data migration uses.
        class _AppsShim:
            def get_model(self, app_label, model_name):
                from django.apps import apps as django_apps

                return django_apps.get_model(app_label, model_name)

        class _SchemaEditorShim:
            class _Conn:
                alias = "default"

            connection = _Conn()

        migration_mod.backfill_checkpoint_pointers(_AppsShim(), _SchemaEditorShim())

        cp.refresh_from_db()
        self.assertEqual(cp.last_seen_value, cp.last_value)
        self.assertEqual(cp.last_committed_value, cp.last_value)
        self.assertEqual(cp.checkpoint_status, "clean")

    def test_default_retry_policy_backfill(self):
        import importlib

        migration_mod = importlib.import_module(
            "sync_jobs.migrations.0031_reliability_dq_foundations"
        )

        tbl = SyncJobTable.objects.create(
            job=self.job, schema_name="public", table_name="orders"
        )
        # Row created post-AddField has retry_policy={}; backfill should
        # populate it with the canonical default policy.
        self.assertEqual(tbl.retry_policy, {})

        class _AppsShim:
            def get_model(self, app_label, model_name):
                from django.apps import apps as django_apps

                return django_apps.get_model(app_label, model_name)

        class _SchemaEditorShim:
            class _Conn:
                alias = "default"

            connection = _Conn()

        migration_mod.backfill_default_retry_policy(_AppsShim(), _SchemaEditorShim())

        tbl.refresh_from_db()
        self.assertEqual(tbl.retry_policy, default_retry_policy())

        # Re-running the backfill should be idempotent: rows that already
        # have a non-empty policy are left alone.
        tbl.retry_policy = {"max_retries": 99}
        tbl.save(update_fields=["retry_policy"])
        migration_mod.backfill_default_retry_policy(_AppsShim(), _SchemaEditorShim())
        tbl.refresh_from_db()
        self.assertEqual(tbl.retry_policy, {"max_retries": 99})


class ReliabilityExceptionTests(TestCase):
    """Smoke-test the typed exceptions added in the reliability package."""

    def test_subclass_relationships(self):
        for cls in (
            TransientSyncError,
            FatalSyncError,
            DeadLetterRowError,
            IdempotencyViolation,
        ):
            self.assertTrue(issubclass(cls, SyncExecutionError))

    def test_dead_letter_carries_row_metadata(self):
        err = DeadLetterRowError(
            "bad row",
            row={"id": 1},
            error_code="ROW_TYPE_ERROR",
        )
        self.assertEqual(err.row, {"id": 1})
        self.assertEqual(err.error_code, "ROW_TYPE_ERROR")
        self.assertIn("bad row", str(err))

    def test_dead_letter_default_error_code(self):
        err = DeadLetterRowError("oops")
        self.assertEqual(err.error_code, "ROW_ERROR")
        self.assertIsNone(err.row)
