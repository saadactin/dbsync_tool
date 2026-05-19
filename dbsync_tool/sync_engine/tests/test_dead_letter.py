"""Day-4 tests for dead-letter capture + tolerance budget.

Covers:

  * ``DeadLetterCollector`` core unit behaviour:
      - records into ``SyncDeadLetterRow`` with sanitization
      - sensitive keys are redacted
      - threshold strictly-exceeded fails, exact threshold is allowed
      - ``flush()`` is idempotent on empty buffers
      - unserializable rows fall back without crashing
      - source_pk extraction picks up incremental_key_columns
  * Day-3 ``classify_error`` + ``to_dead_letter`` interplay:
      - ``DeadLetterRowError`` keeps dead_letter category
      - ``dead_letter=True`` tagged exception routes to dead_letter
      - infrastructure errors (OperationalError-like) stay non-dead-letter
  * Executor wire-in for incremental + full + flat-file:
      - row-scope error below budget continues + records
      - row-scope error above budget raises a ``DeadLetterRowError`` with
        a budget-breach message
      - non-row exceptions fall through to legacy fatal handling
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_engine.reliability import (
    CATEGORY_DEAD_LETTER,
    CATEGORY_FATAL,
    DEFAULT_DEAD_LETTER_MAX_PCT,
    DeadLetterCollector,
    DeadLetterRowError,
    DeadLetterStats,
    classify_error,
    is_dead_letter,
    to_dead_letter,
)
from sync_jobs.models import (
    SyncDeadLetterRow,
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
    SyncJobTable,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _make_user_and_conns(prefix: str):
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


def _make_job_execution_table(prefix: str, *, dead_letter_max_pct: float = 0.001):
    user, src, tgt = _make_user_and_conns(prefix)
    job = SyncJob.objects.create(
        name=f"{prefix}-job",
        source_connection_type="database",
        source_connection=src,
        target_connection=tgt,
        sync_type="incremental",
        created_by=user,
        tenant=user,
    )
    execution = SyncExecution.objects.create(job=job)
    job_table = SyncJobTable.objects.create(
        job=job,
        schema_name="public",
        table_name="orders",
        is_enabled=True,
        dead_letter_max_pct=dead_letter_max_pct,
        incremental_key_columns=["order_id"],
    )
    log = SyncExecutionLog.objects.create(
        execution=execution,
        schema_name=job_table.schema_name,
        table_name=job_table.table_name,
        status="pending",
    )
    return user, job, execution, job_table, log


def _make_collector(prefix: str, **kwargs):
    user, job, execution, job_table, log = _make_job_execution_table(
        prefix, **kwargs
    )
    collector = DeadLetterCollector(
        execution=execution,
        job=job,
        job_table=job_table,
    )
    return collector, execution, job, job_table, log


# ----------------------------------------------------------------------
# Stats
# ----------------------------------------------------------------------


class DeadLetterStatsTests(SimpleTestCase):
    def test_dead_letter_pct_zero_when_no_rows_seen(self):
        s = DeadLetterStats()
        self.assertEqual(s.dead_letter_pct, 0.0)

    def test_dead_letter_pct_calculation(self):
        s = DeadLetterStats(rows_seen=1000, dead_letter_count=2)
        self.assertAlmostEqual(s.dead_letter_pct, 0.002)


# ----------------------------------------------------------------------
# Classifier interplay (no DB)
# ----------------------------------------------------------------------


class ClassifyDeadLetterTests(SimpleTestCase):
    def test_typed_dead_letter_row_error_routes_to_dead_letter(self):
        cat, code = classify_error(
            DeadLetterRowError("bad row", row={"id": 1}, error_code="ROW_ERROR")
        )
        self.assertEqual((cat, code), (CATEGORY_DEAD_LETTER, "ROW_ERROR"))

    def test_tagged_exception_routes_to_dead_letter(self):
        exc = ValueError("constraint failure")
        exc.dead_letter = True
        exc.error_code = "CONSTRAINT_VIOLATION"
        cat, code = classify_error(exc)
        self.assertEqual((cat, code), (CATEGORY_DEAD_LETTER, "CONSTRAINT_VIOLATION"))

    def test_untagged_value_error_stays_fatal(self):
        cat, _code = classify_error(ValueError("bad value"))
        self.assertEqual(cat, CATEGORY_FATAL)

    def test_to_dead_letter_wraps_arbitrary_exception(self):
        original = ValueError("syntax error in row")
        wrapped = to_dead_letter(original, row={"id": 7}, error_code="PARSE_ERROR")
        self.assertIsInstance(wrapped, DeadLetterRowError)
        self.assertEqual(wrapped.error_code, "PARSE_ERROR")
        self.assertIs(wrapped.__cause__, original)
        self.assertEqual(wrapped.row, {"id": 7})

    def test_to_dead_letter_idempotent_for_existing(self):
        existing = DeadLetterRowError("already dead", row={"id": 9})
        same = to_dead_letter(existing, row={"id": 9}, error_code="ROW_ERROR")
        self.assertIs(same, existing)

    def test_is_dead_letter_helper(self):
        self.assertTrue(is_dead_letter(DeadLetterRowError("x")))
        tagged = ValueError("x")
        tagged.dead_letter = True
        self.assertTrue(is_dead_letter(tagged))
        self.assertFalse(is_dead_letter(ValueError("untagged")))


# ----------------------------------------------------------------------
# Collector core (DB-backed)
# ----------------------------------------------------------------------


class DeadLetterCollectorPersistenceTests(TestCase):
    def test_record_persists_sanitized_dead_letter_row(self):
        collector, execution, _job, _job_table, _log = _make_collector("ddl_record")
        collector.mark_seen(10)
        collector.record(
            row={"order_id": 42, "customer": "alice"},
            error=DeadLetterRowError("constraint x", error_code="CONSTRAINT_VIOLATION"),
            batch_id="batch-1",
        )
        collector.flush()

        rows = SyncDeadLetterRow.objects.filter(execution=execution)
        self.assertEqual(rows.count(), 1)
        row = rows.first()
        self.assertEqual(row.error_code, "CONSTRAINT_VIOLATION")
        self.assertEqual(row.batch_id, "batch-1")
        self.assertEqual(row.source_pk_text, "42")
        self.assertEqual(row.raw_row_json["customer"], "alice")
        self.assertIsNotNone(row.source_row_hash)

    def test_sensitive_keys_are_redacted(self):
        collector, execution, *_ = _make_collector("ddl_redact")
        collector.mark_seen(1)
        collector.record(
            row={
                "id": 1,
                "user_password": "hunter2",
                "Authorization": "Bearer xyz",
                "api_key": "sk-AAA",
                "name": "ok",
            },
            error=DeadLetterRowError("bad row"),
        )
        collector.flush()
        row = SyncDeadLetterRow.objects.filter(execution=execution).first()
        payload = row.raw_row_json
        self.assertEqual(payload["user_password"], "***REDACTED***")
        self.assertEqual(payload["Authorization"], "***REDACTED***")
        self.assertEqual(payload["api_key"], "***REDACTED***")
        self.assertEqual(payload["name"], "ok")

    def test_record_handles_none_row_without_crash(self):
        collector, execution, *_ = _make_collector("ddl_none")
        collector.mark_seen(1)
        collector.record(row=None, error=DeadLetterRowError("no context"))
        collector.flush()
        row = SyncDeadLetterRow.objects.filter(execution=execution).first()
        self.assertIsNone(row.raw_row_json)
        self.assertIsNone(row.source_pk_text)

    def test_unserializable_row_falls_back_without_crash(self):
        class _Weird:
            def __repr__(self):
                return "<weird>"

        collector, execution, *_ = _make_collector("ddl_weird")
        collector.mark_seen(1)
        collector.record(
            row={"id": 1, "blob": _Weird()},
            error=DeadLetterRowError("weird row"),
        )
        collector.flush()
        row = SyncDeadLetterRow.objects.filter(execution=execution).first()
        self.assertIsNotNone(row)
        self.assertIn("blob", row.raw_row_json)

    def test_flush_is_idempotent_when_no_rows(self):
        collector, _execution, *_ = _make_collector("ddl_idem_flush")
        collector.flush()
        collector.flush()
        self.assertEqual(SyncDeadLetterRow.objects.count(), 0)


class DeadLetterCollectorBudgetTests(TestCase):
    def test_zero_dead_letters_does_not_fail(self):
        collector, *_ = _make_collector("ddl_zero", dead_letter_max_pct=0.0)
        collector.mark_seen(100)
        self.assertFalse(collector.should_fail())

    def test_threshold_strictly_exceeded_fails(self):
        collector, *_ = _make_collector("ddl_breach", dead_letter_max_pct=0.001)
        # 2 / 1000 = 0.002 > 0.001
        collector.mark_seen(1000)
        for i in range(2):
            collector.record(
                row={"order_id": i},
                error=DeadLetterRowError("bad"),
            )
        self.assertTrue(collector.should_fail())
        with self.assertRaises(DeadLetterRowError):
            collector.raise_if_budget_exceeded()

    def test_exact_threshold_is_allowed(self):
        collector, *_ = _make_collector("ddl_exact", dead_letter_max_pct=0.001)
        # 1 / 1000 = 0.001 == max_pct -> allowed (strict inequality).
        collector.mark_seen(1000)
        collector.record(
            row={"order_id": 1},
            error=DeadLetterRowError("bad"),
        )
        self.assertFalse(collector.should_fail())

    def test_zero_budget_fails_fast_on_first_bad_row(self):
        collector, *_ = _make_collector("ddl_zero_budget", dead_letter_max_pct=0.0)
        collector.mark_seen(100)
        collector.record(row={"order_id": 1}, error=DeadLetterRowError("bad"))
        self.assertTrue(collector.should_fail())

    def test_update_log_counters_writes_dead_letter_count(self):
        collector, _execution, _job, _job_table, log = _make_collector("ddl_log_counter")
        collector.mark_seen(50)
        collector.record(row={"order_id": 1}, error=DeadLetterRowError("bad"))
        collector.flush()
        collector.update_log_counters()
        log.refresh_from_db()
        self.assertEqual(log.dead_letter_count, 1)


class DeadLetterCollectorMockSafetyTests(SimpleTestCase):
    """Collector must not blow up when the executor-fixture is a Mock."""

    def test_mock_execution_disables_db_writes_but_keeps_budget(self):
        execution = MagicMock(spec=SyncExecution)
        execution.pk = None
        job = MagicMock(spec=SyncJob)
        job.pk = None
        job_table = MagicMock(spec=SyncJobTable)
        job_table.schema_name = "public"
        job_table.table_name = "orders"
        job_table.dead_letter_max_pct = 0.001
        job_table.incremental_key_columns = ["order_id"]
        job_table.incremental_column = None
        job_table.protected_columns = []

        collector = DeadLetterCollector(
            execution=execution,
            job=job,
            job_table=job_table,
        )
        # No DB writes should happen; counters still advance.
        collector.mark_seen(1000)
        for _ in range(5):
            collector.record(row={"order_id": 7}, error=DeadLetterRowError("nope"))
        self.assertEqual(collector.stats.dead_letter_count, 5)
        self.assertTrue(collector.should_fail())
        # flush + update_log_counters are no-ops, must not raise.
        collector.flush()
        collector.update_log_counters()


# ----------------------------------------------------------------------
# Executor wire-in (incremental, full, flat-file)
# ----------------------------------------------------------------------


class _StubIncrementalExecutor:
    """Minimal stand-in for ``IncrementalSyncExecutor`` to exercise the
    Day-4 helper methods without touching connectors."""

    def __init__(self, execution, job):
        self.execution = execution
        self.job = job

    # The helper methods we want to test call into _make_dead_letter_collector
    # directly; the rest of IncrementalSyncExecutor is irrelevant here.


class IncrementalExecutorWireInTests(TestCase):
    def test_under_budget_dead_letter_continues(self):
        from sync_engine.incremental_sync import IncrementalSyncExecutor

        _, job, execution, job_table, log = _make_job_execution_table(
            "exe_under", dead_letter_max_pct=0.5  # generous
        )
        stub = _StubIncrementalExecutor(execution, job)

        # Bind the real wrapper methods to our stub.
        make = IncrementalSyncExecutor._make_dead_letter_collector.__get__(stub)
        handle = IncrementalSyncExecutor._handle_batch_exception_with_dead_letter.__get__(stub)

        collector = make(job_table)
        collector.mark_seen(10)
        bad_row = {"order_id": 99, "customer": "x"}
        wrapped = DeadLetterRowError("constraint x", row=bad_row)

        handled = handle(
            wrapped,
            dl_collector=collector,
            sample_row=bad_row,
            batch_id="b-1",
        )
        self.assertTrue(handled)
        self.assertEqual(collector.stats.dead_letter_count, 1)
        self.assertEqual(SyncDeadLetterRow.objects.filter(execution=execution).count(), 1)

    def test_over_budget_dead_letter_raises_dead_letter_error(self):
        from sync_engine.incremental_sync import IncrementalSyncExecutor

        _, job, execution, job_table, log = _make_job_execution_table(
            "exe_over", dead_letter_max_pct=0.001  # 0.1%
        )
        stub = _StubIncrementalExecutor(execution, job)
        make = IncrementalSyncExecutor._make_dead_letter_collector.__get__(stub)
        handle = IncrementalSyncExecutor._handle_batch_exception_with_dead_letter.__get__(stub)

        collector = make(job_table)
        collector.mark_seen(10)  # 1/10 = 10% >> 0.1%

        with self.assertRaises(DeadLetterRowError) as cm:
            handle(
                DeadLetterRowError("bad row"),
                dl_collector=collector,
                sample_row={"order_id": 1},
                batch_id="b-1",
            )
        self.assertIn("budget", str(cm.exception).lower())

    def test_non_row_exception_is_not_handled(self):
        from sync_engine.incremental_sync import IncrementalSyncExecutor

        _, job, execution, job_table, _log = _make_job_execution_table("exe_other")
        stub = _StubIncrementalExecutor(execution, job)
        make = IncrementalSyncExecutor._make_dead_letter_collector.__get__(stub)
        handle = IncrementalSyncExecutor._handle_batch_exception_with_dead_letter.__get__(stub)

        collector = make(job_table)
        collector.mark_seen(100)

        # Plain RuntimeError (no dead_letter tag) -> caller falls back
        # to the legacy fatal handling.
        handled = handle(
            RuntimeError("connector blew up"),
            dl_collector=collector,
            sample_row={"order_id": 1},
            batch_id="b-1",
        )
        self.assertFalse(handled)
        self.assertEqual(collector.stats.dead_letter_count, 0)


class FullSyncExecutorWireInTests(TestCase):
    def test_under_budget_dead_letter_continues(self):
        from sync_engine.full_sync import FullSyncExecutor

        _, job, execution, job_table, _log = _make_job_execution_table(
            "fse_under", dead_letter_max_pct=0.5
        )
        stub = _StubIncrementalExecutor(execution, job)
        make = FullSyncExecutor._make_dead_letter_collector.__get__(stub)
        handle = FullSyncExecutor._handle_batch_exception_with_dead_letter.__get__(stub)

        collector = make(job_table)
        collector.mark_seen(10)
        handled = handle(
            DeadLetterRowError("bad row", row={"order_id": 1}),
            dl_collector=collector,
            sample_row={"order_id": 1},
            batch_id="fs-b-1",
        )
        self.assertTrue(handled)
        self.assertEqual(SyncDeadLetterRow.objects.filter(execution=execution).count(), 1)

    def test_over_budget_dead_letter_raises_for_full_sync(self):
        from sync_engine.full_sync import FullSyncExecutor

        _, job, execution, job_table, _log = _make_job_execution_table(
            "fse_over", dead_letter_max_pct=0.0
        )
        stub = _StubIncrementalExecutor(execution, job)
        make = FullSyncExecutor._make_dead_letter_collector.__get__(stub)
        handle = FullSyncExecutor._handle_batch_exception_with_dead_letter.__get__(stub)

        collector = make(job_table)
        collector.mark_seen(100)
        with self.assertRaises(DeadLetterRowError):
            handle(
                DeadLetterRowError("bad row"),
                dl_collector=collector,
                sample_row={"order_id": 1},
                batch_id="fs-b-1",
            )


class TaxonomyRegressionTests(SimpleTestCase):
    """Regressions guarding Day-3 contract while extending Day-4."""

    def test_idempotency_violation_still_fatal(self):
        from sync_engine.reliability import IdempotencyViolation

        cat, code = classify_error(IdempotencyViolation("dup"))
        self.assertEqual((cat, code), (CATEGORY_FATAL, "IDEMPOTENCY_VIOLATION"))

    def test_default_dead_letter_max_pct_constant(self):
        self.assertAlmostEqual(DEFAULT_DEAD_LETTER_MAX_PCT, 0.001)
