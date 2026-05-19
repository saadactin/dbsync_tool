"""Day-3 tests for the per-table retry policy + error taxonomy.

Covers:
  * ``RetryPolicy.from_job_table`` happy + hostile JSON clamping
  * ``classify_error`` typed exceptions, cause-walk, message-based
  * ``with_policy`` lifecycle: first-attempt success, transient retry
    + success, fatal abort, max-retries cap, IdempotencyViolation
    short-circuit, exponential backoff with jitter, and the
    ``max_total_seconds`` safety cap
  * Two integration tests against ``IncrementalSyncExecutor`` to assert
    ``SyncExecutionLog.attempts`` and ``last_error_code`` are
    populated end-to-end.

All tests use a fake ``sleep`` and a deterministic ``random.Random``
so timings are asserted instead of slept through.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_engine.exceptions import TableSyncError
from sync_engine.reliability import (
    CATEGORY_DEAD_LETTER,
    CATEGORY_FATAL,
    CATEGORY_TRANSIENT,
    DeadLetterRowError,
    FatalSyncError,
    IdempotencyViolation,
    RetryPolicy,
    TransientSyncError,
    classify_error,
    with_policy,
)
from sync_jobs.models import (
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
    SyncJobTable,
    default_retry_policy,
)


# ----------------------------------------------------------------------
# Test helpers
# ----------------------------------------------------------------------


class _FakeSleeper:
    """Captures sleep durations without ever actually sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)

    @property
    def total(self) -> float:
        return sum(self.calls)


class _FakeRandom:
    """Cycles through a fixed sequence of random() values."""

    def __init__(self, sequence) -> None:
        self._values = list(sequence)
        self._idx = 0

    def random(self) -> float:
        if not self._values:
            return 0.0
        v = self._values[self._idx % len(self._values)]
        self._idx += 1
        return v


class _Counter:
    """Closure-friendly attempt counter."""

    def __init__(self) -> None:
        self.value = 0

    def bump(self) -> int:
        self.value += 1
        return self.value


# ----------------------------------------------------------------------
# RetryPolicy.from_job_table
# ----------------------------------------------------------------------


class RetryPolicyParsingTests(SimpleTestCase):
    def test_default_policy_from_empty_jsonfield_uses_factory(self):
        jt = MagicMock(spec=SyncJobTable)
        jt.retry_policy = {}
        policy = RetryPolicy.from_job_table(jt)
        defaults = default_retry_policy()
        self.assertEqual(policy.max_retries, defaults["max_retries"])
        self.assertEqual(policy.initial_delay, defaults["initial_delay"])
        self.assertEqual(policy.backoff, defaults["backoff"])

    def test_policy_clamps_hostile_values(self):
        jt = MagicMock(spec=SyncJobTable)
        jt.retry_policy = {
            "max_retries": 10000,
            "initial_delay": -1,
            "backoff": 1000,
        }
        policy = RetryPolicy.from_job_table(jt)
        self.assertEqual(policy.max_retries, 10)  # clamp upper bound
        self.assertEqual(policy.initial_delay, 0.0)  # clamp lower bound
        self.assertEqual(policy.backoff, 10.0)  # clamp upper bound

    def test_policy_garbage_types_fall_back_to_default(self):
        jt = MagicMock(spec=SyncJobTable)
        jt.retry_policy = {
            "max_retries": "not-a-number",
            "initial_delay": None,
            "backoff": [],
        }
        policy = RetryPolicy.from_job_table(jt)
        defaults = default_retry_policy()
        self.assertEqual(policy.max_retries, defaults["max_retries"])
        self.assertEqual(policy.initial_delay, defaults["initial_delay"])
        self.assertEqual(policy.backoff, defaults["backoff"])

    def test_policy_handles_mock_object_without_dict(self):
        jt = MagicMock()  # no retry_policy attr controlled by spec
        jt.retry_policy = MagicMock()  # a Mock is not a dict
        policy = RetryPolicy.from_job_table(jt)
        defaults = default_retry_policy()
        self.assertEqual(policy.max_retries, defaults["max_retries"])

    def test_disabled_policy_yields_single_attempt(self):
        policy = RetryPolicy.disabled()
        self.assertEqual(policy.max_retries, 0)


# ----------------------------------------------------------------------
# classify_error
# ----------------------------------------------------------------------


class ClassifyTypedErrorsTests(SimpleTestCase):
    def test_transient_sync_error_is_transient(self):
        cat, code = classify_error(TransientSyncError("connection reset by peer"))
        self.assertEqual(cat, CATEGORY_TRANSIENT)
        self.assertEqual(code, "CONN_RESET")

    def test_fatal_sync_error_is_fatal(self):
        cat, code = classify_error(FatalSyncError("permission denied"))
        self.assertEqual(cat, CATEGORY_FATAL)
        self.assertEqual(code, "PERMISSION_DENIED")

    def test_dead_letter_row_error_is_dead_letter(self):
        try:
            raise DeadLetterRowError("bad row", row={"id": 1})
        except DeadLetterRowError as exc:
            cat, code = classify_error(exc)
        self.assertEqual(cat, CATEGORY_DEAD_LETTER)
        self.assertEqual(code, "ROW_ERROR")

    def test_idempotency_violation_is_fatal(self):
        cat, code = classify_error(IdempotencyViolation("dup commit"))
        self.assertEqual(cat, CATEGORY_FATAL)
        self.assertEqual(code, "IDEMPOTENCY_VIOLATION")

    def test_connection_error_is_transient(self):
        cat, code = classify_error(ConnectionError("nope"))
        self.assertEqual(cat, CATEGORY_TRANSIENT)
        self.assertEqual(code, "CONN_RESET")

    def test_timeout_error_is_transient(self):
        cat, code = classify_error(TimeoutError("slow"))
        self.assertEqual(cat, CATEGORY_TRANSIENT)
        self.assertEqual(code, "TIMEOUT")

    def test_unknown_exception_is_fatal_unknown(self):
        cat, code = classify_error(ValueError("???"))
        self.assertEqual(cat, CATEGORY_FATAL)
        self.assertEqual(code, "UNKNOWN")


class ClassifyCauseChainTests(SimpleTestCase):
    def test_cause_walk_picks_inner_specific_match(self):
        try:
            try:
                raise RuntimeError("deadlock detected on relation orders")
            except RuntimeError as inner:
                raise TableSyncError("upsert failed") from inner
        except TableSyncError as exc:
            cat, code = classify_error(exc)
        self.assertEqual(cat, CATEGORY_TRANSIENT)
        self.assertEqual(code, "DEADLOCK")

    def test_cause_walk_falls_through_to_outer_when_inner_unknown(self):
        try:
            try:
                raise ValueError("opaque")
            except ValueError as inner:
                raise TableSyncError("relation orders does not exist") from inner
        except TableSyncError as exc:
            cat, code = classify_error(exc)
        # The outer message indicates a missing table; classify hits
        # the outer because the inner is fatal/UNKNOWN.
        self.assertEqual(cat, CATEGORY_FATAL)
        self.assertEqual(code, "TABLE_NOT_FOUND")


class ClassifyMessageBasedTests(SimpleTestCase):
    def test_table_not_found_message_is_fatal(self):
        cat, code = classify_error(TableSyncError("relation X does not exist"))
        self.assertEqual(cat, CATEGORY_FATAL)
        self.assertEqual(code, "TABLE_NOT_FOUND")

    def test_lock_timeout_message_is_transient(self):
        # TableSyncError -> FatalSyncError; we use a custom transient
        # subclass so the typed branch fires correctly first.
        cat, code = classify_error(TransientSyncError("lock_timeout exceeded"))
        self.assertEqual(cat, CATEGORY_TRANSIENT)
        self.assertEqual(code, "LOCK_TIMEOUT")


# ----------------------------------------------------------------------
# with_policy
# ----------------------------------------------------------------------


class WithPolicyLifecycleTests(SimpleTestCase):
    def _policy(self, *, max_retries=3, initial_delay=1.0, backoff=2.0, **kw):
        return RetryPolicy(
            max_retries=max_retries,
            initial_delay=initial_delay,
            backoff=backoff,
            **kw,
        )

    def test_succeeds_on_first_attempt(self):
        sleeper = _FakeSleeper()
        attempts: list[tuple[int, str | None]] = []
        result = with_policy(
            lambda: "ok",
            self._policy(),
            on_attempt=lambda n, c: attempts.append((n, c)),
            sleep=sleeper,
            rng=_FakeRandom([0.0]),
        )
        self.assertEqual(result, "ok")
        self.assertEqual(attempts, [(1, None)])
        self.assertEqual(sleeper.calls, [])

    def test_retries_transient_then_succeeds(self):
        sleeper = _FakeSleeper()
        ctr = _Counter()
        attempts: list[tuple[int, str | None]] = []

        def _flaky():
            n = ctr.bump()
            if n < 3:
                raise TransientSyncError("connection reset")
            return "done"

        result = with_policy(
            _flaky,
            self._policy(initial_delay=1.0, backoff=2.0),
            on_attempt=lambda n, c: attempts.append((n, c)),
            sleep=sleeper,
            rng=_FakeRandom([0.0, 0.0, 0.0]),  # zero jitter
        )
        self.assertEqual(result, "done")
        self.assertEqual(ctr.value, 3)
        self.assertEqual(len(sleeper.calls), 2)
        self.assertEqual(sleeper.calls[0], 1.0)  # initial_delay * 2^0
        self.assertEqual(sleeper.calls[1], 2.0)  # initial_delay * 2^1
        self.assertEqual(attempts, [(1, None), (2, "CONN_RESET"), (3, "CONN_RESET")])

    def test_aborts_on_fatal_immediately(self):
        sleeper = _FakeSleeper()
        ctr = _Counter()

        def _bad():
            ctr.bump()
            raise FatalSyncError("permission denied")

        with self.assertRaises(FatalSyncError):
            with_policy(_bad, self._policy(), sleep=sleeper)
        self.assertEqual(ctr.value, 1)
        self.assertEqual(sleeper.calls, [])

    def test_caps_at_max_retries(self):
        sleeper = _FakeSleeper()
        ctr = _Counter()

        def _bad():
            ctr.bump()
            raise TransientSyncError("connection reset")

        with self.assertRaises(TransientSyncError):
            with_policy(
                _bad,
                self._policy(max_retries=3, initial_delay=0.1, backoff=2.0),
                sleep=sleeper,
                rng=_FakeRandom([0.0]),
            )
        # 1 initial + 3 retries = 4 attempts, 3 sleeps in between.
        self.assertEqual(ctr.value, 4)
        self.assertEqual(len(sleeper.calls), 3)

    def test_idempotency_violation_is_fatal_even_with_retries(self):
        sleeper = _FakeSleeper()
        ctr = _Counter()

        def _bad():
            ctr.bump()
            raise IdempotencyViolation("dup commit")

        with self.assertRaises(IdempotencyViolation):
            with_policy(
                _bad,
                self._policy(max_retries=5),
                sleep=sleeper,
            )
        self.assertEqual(ctr.value, 1)
        self.assertEqual(sleeper.calls, [])

    def test_exponential_backoff_with_jitter_timing(self):
        sleeper = _FakeSleeper()
        ctr = _Counter()

        # rng.random() returns 0.0, 1.0, 0.5 in turn; jitter = 1 + r*0.25
        rng = _FakeRandom([0.0, 1.0, 0.5])

        def _bad():
            ctr.bump()
            raise TransientSyncError("connection reset")

        with self.assertRaises(TransientSyncError):
            with_policy(
                _bad,
                self._policy(max_retries=3, initial_delay=2.0, backoff=2.0),
                sleep=sleeper,
                rng=rng,
            )

        # Expected base delays: 2.0, 4.0, 8.0
        # Jitter multipliers from rng: 1.00, 1.25, 1.125
        self.assertAlmostEqual(sleeper.calls[0], 2.0 * 1.00, places=6)
        self.assertAlmostEqual(sleeper.calls[1], 4.0 * 1.25, places=6)
        self.assertAlmostEqual(sleeper.calls[2], 8.0 * 1.125, places=6)

    def test_max_total_seconds_safety_cap(self):
        sleeper = _FakeSleeper()
        ctr = _Counter()

        def _bad():
            ctr.bump()
            raise TransientSyncError("connection reset")

        # Cap the cumulative sleep at 1.5s. With initial_delay=1.0,
        # backoff=2.0, the first sleep is 1.0; the second would be
        # 2.0 but only 0.5 of budget remains, so it is clipped. Then
        # the third retry has no budget left and we abort.
        with self.assertRaises(TransientSyncError):
            with_policy(
                _bad,
                RetryPolicy(
                    max_retries=5,
                    initial_delay=1.0,
                    backoff=2.0,
                    max_total_seconds=1.5,
                ),
                sleep=sleeper,
                rng=_FakeRandom([0.0]),
            )
        self.assertLessEqual(sleeper.total, 1.5 + 1e-6)


# ----------------------------------------------------------------------
# Executor wire-in integration
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


def _make_job_execution_table(prefix: str):
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
    )
    return user, job, execution, job_table


class _StubExecutor:
    """Mimics the slice of IncrementalSyncExecutor needed by the wrappers.

    We exercise ``_sync_table_with_policy`` and
    ``_record_terminal_table_error`` by binding the real methods to a
    minimal stand-in. This keeps the integration test focused on the
    Day-3 behaviour without requiring real source/target connectors.
    """

    def __init__(self, execution, sync_table_callable):
        self.execution = execution
        self._sync_table = sync_table_callable

    def sync_table(self, job_table):
        return self._sync_table(job_table)


class ExecutorWireInTests(TestCase):
    def test_executor_wire_in_increments_attempts_then_succeeds(self):
        from sync_engine.incremental_sync import IncrementalSyncExecutor

        _, _job, execution, job_table = _make_job_execution_table("ewi_ok")
        # Pre-create the log row so on_attempt's UPDATE actually finds
        # something to bump (real sync_table would create it, but we
        # stub sync_table here).
        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name=job_table.schema_name,
            table_name=job_table.table_name,
            status="pending",
        )

        ctr = _Counter()

        def _flaky_sync_table(jt):
            n = ctr.bump()
            if n < 3:
                raise TransientSyncError("connection reset")
            return None

        stub = _StubExecutor(execution, _flaky_sync_table)
        # Bind the real wrapper method to our stub so we exercise the
        # production code path verbatim.
        bound = IncrementalSyncExecutor._sync_table_with_policy.__get__(stub)
        # The on_attempt callback inside the wrapper sleeps via
        # time.sleep(); patch RetryPolicy.from_job_table to return a
        # zero-delay policy so the test does not actually sleep.
        from sync_engine.reliability import retry_policy as _rp

        original_from = _rp.RetryPolicy.from_job_table
        try:
            _rp.RetryPolicy.from_job_table = staticmethod(
                lambda _jt: RetryPolicy(
                    max_retries=5, initial_delay=0.0, backoff=1.0,
                )
            )
            bound(job_table)
        finally:
            _rp.RetryPolicy.from_job_table = original_from

        log = SyncExecutionLog.objects.get(
            execution=execution,
            schema_name=job_table.schema_name,
            table_name=job_table.table_name,
        )
        # 3 total attempts means 2 retries; on_attempt fires for n>=2,
        # writing attempts=n-1: so at n=2 -> attempts=1, n=3 -> attempts=2.
        self.assertEqual(log.attempts, 2)
        # Last code persisted on the n=3 callback (the prior failure
        # was CONN_RESET); on success the wrapper does not clear it.
        self.assertEqual(log.last_error_code, "CONN_RESET")

    def test_executor_records_last_error_code_on_terminal_failure(self):
        from sync_engine.incremental_sync import IncrementalSyncExecutor

        _, _job, execution, job_table = _make_job_execution_table("ewi_fail")
        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name=job_table.schema_name,
            table_name=job_table.table_name,
            status="pending",
        )

        def _always_fatal(_jt):
            raise FatalSyncError("relation X does not exist")

        stub = _StubExecutor(execution, _always_fatal)
        bound_table = IncrementalSyncExecutor._sync_table_with_policy.__get__(stub)
        bound_record = IncrementalSyncExecutor._record_terminal_table_error.__get__(stub)

        from sync_engine.reliability import retry_policy as _rp

        original_from = _rp.RetryPolicy.from_job_table
        try:
            _rp.RetryPolicy.from_job_table = staticmethod(
                lambda _jt: RetryPolicy(
                    max_retries=3, initial_delay=0.0, backoff=1.0,
                )
            )
            try:
                bound_table(job_table)
            except FatalSyncError as exc:
                bound_record(job_table, exc)
        finally:
            _rp.RetryPolicy.from_job_table = original_from

        log = SyncExecutionLog.objects.get(
            execution=execution,
            schema_name=job_table.schema_name,
            table_name=job_table.table_name,
        )
        self.assertEqual(log.last_error_code, "TABLE_NOT_FOUND")
