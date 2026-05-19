"""Day-7 tests: ``ops_metrics_service`` rollup math + tenant scoping.

Covers:
- ``compute_health_rollup`` aggregates ok-rate, dead-letter pct, attempts p95.
- Window filtering excludes executions outside the time window.
- Empty-data sentinel returns OK SLOs and zero counters.
- Tenant scoping filters out other-tenant data.
- ``compute_job_health`` orders by last execution start desc.
- ``_percentile`` degrades to ``max`` for small samples.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_jobs.models import (
    ReconciliationReport,
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
)
from sync_jobs.services import ops_metrics_service


def _make_user(username: str) -> User:
    """Create a user, then promote their profile to ADMIN with self-tenant.

    The post-save signal in ``accounts.signals`` auto-creates a profile;
    we override its role/tenant so ``TenantService`` treats this user as a
    tenant owner (the production case for sync_job creators).
    """
    user = User.objects.create_user(
        username=username, password="pw", email=f"{username}@example.com"
    )
    profile = user.userprofile
    profile.role = Role.ADMIN
    profile.tenant = user
    profile.save(update_fields=["role", "tenant"])
    return user


def _make_job(prefix: str, tenant_user: User) -> SyncJob:
    src = DatabaseConnection.objects.create(
        name=f"{prefix}-src",
        db_type="postgres",
        host="localhost",
        port=5432,
        username="u",
        password="p",
        database_name="db_src",
        created_by=tenant_user,
        tenant=tenant_user,
    )
    tgt = DatabaseConnection.objects.create(
        name=f"{prefix}-tgt",
        db_type="postgres",
        host="localhost",
        port=5432,
        username="u",
        password="p",
        database_name="db_tgt",
        created_by=tenant_user,
        tenant=tenant_user,
    )
    return SyncJob.objects.create(
        name=f"{prefix}-job",
        source_connection_type="database",
        source_connection=src,
        target_connection=tgt,
        sync_type="incremental",
        created_by=tenant_user,
        tenant=tenant_user,
    )


def _make_execution(job: SyncJob, *, status: str = "completed",
                    started_offset: timedelta | None = None) -> SyncExecution:
    """Create an execution and override ``started_at`` (which uses ``auto_now_add``)."""
    execution = SyncExecution.objects.create(
        job=job, status=status, total_tables=1, completed_tables=1,
    )
    if started_offset is not None:
        when = timezone.now() - started_offset
        SyncExecution.objects.filter(id=execution.id).update(
            started_at=when, completed_at=when,
        )
        execution.refresh_from_db()
    return execution


def _seed_table(execution: SyncExecution, *, decision: str = "ok",
                confidence: float = 1.0, attempts: int = 0,
                dead_letter_count: int = 0, rows_fetched: int = 100,
                schema: str = "public", table: str = "orders") -> None:
    SyncExecutionLog.objects.create(
        execution=execution,
        schema_name=schema,
        table_name=table,
        status="completed",
        rows_fetched=rows_fetched,
        rows_inserted=rows_fetched - dead_letter_count,
        attempts=attempts,
        dead_letter_count=dead_letter_count,
    )
    ReconciliationReport.objects.create(
        execution=execution,
        job=execution.job,
        schema_name=schema,
        table_name=table,
        decision=decision,
        confidence=confidence,
        dq_pre_json={},
        dq_post_json={},
    )


class HealthRollupTests(TestCase):
    def setUp(self):
        self.user = _make_user("ops_owner_1")
        self.job = _make_job("ops1", self.user)

    def test_health_rollup_empty_returns_ok_sentinel(self):
        rollup = ops_metrics_service.compute_health_rollup(
            self.user, window_hours=24,
        )
        self.assertEqual(rollup["totals"]["executions"], 0)
        self.assertEqual(rollup["totals"]["ok_rate"], 1.0)
        self.assertTrue(rollup["slo"]["ok_rate"]["ok"])
        self.assertTrue(rollup["slo"]["dead_letter_pct"]["ok"])
        self.assertTrue(rollup["slo"]["attempts_p95"]["ok"])
        self.assertTrue(rollup["slo"]["confidence_floor"]["ok"])

    def test_health_rollup_aggregates_decisions_and_pct(self):
        ok_exec = _make_execution(self.job, started_offset=timedelta(hours=2))
        _seed_table(
            ok_exec, decision="ok", confidence=1.0, attempts=0,
            dead_letter_count=0, rows_fetched=1000,
        )
        warn_exec = _make_execution(self.job, started_offset=timedelta(hours=4))
        _seed_table(
            warn_exec, decision="warning", confidence=0.7, attempts=2,
            dead_letter_count=5, rows_fetched=1000,
            schema="public", table="t2",
        )

        rollup = ops_metrics_service.compute_health_rollup(
            self.user, window_hours=24,
        )
        self.assertEqual(rollup["totals"]["executions"], 2)
        self.assertEqual(rollup["totals"]["ok"], 1)
        self.assertEqual(rollup["totals"]["warning"], 1)
        self.assertEqual(rollup["totals"]["drift_incidents"], 1)
        self.assertAlmostEqual(rollup["totals"]["ok_rate"], 0.5)
        # 5 dead-letter rows over 2000 fetched = 0.0025
        self.assertAlmostEqual(rollup["totals"]["dead_letter_pct"], 0.0025)
        self.assertFalse(rollup["slo"]["dead_letter_pct"]["ok"])
        self.assertFalse(rollup["slo"]["confidence_floor"]["ok"])

    def test_health_rollup_window_filtering_excludes_old_runs(self):
        recent = _make_execution(self.job, started_offset=timedelta(hours=2))
        _seed_table(recent, decision="ok", confidence=1.0)

        old = _make_execution(self.job, started_offset=timedelta(hours=48))
        _seed_table(
            old, decision="warning", confidence=0.5,
            schema="public", table="old_t",
        )

        rollup_24h = ops_metrics_service.compute_health_rollup(
            self.user, window_hours=24,
        )
        self.assertEqual(rollup_24h["totals"]["executions"], 1)
        self.assertEqual(rollup_24h["totals"]["ok"], 1)
        self.assertEqual(rollup_24h["totals"]["warning"], 0)

        rollup_7d = ops_metrics_service.compute_health_rollup(
            self.user, window_hours=168,
        )
        self.assertEqual(rollup_7d["totals"]["executions"], 2)
        self.assertEqual(rollup_7d["totals"]["warning"], 1)

    def test_health_rollup_is_tenant_scoped(self):
        my_exec = _make_execution(self.job, started_offset=timedelta(hours=2))
        _seed_table(my_exec, decision="ok")

        other = _make_user("ops_other_owner")
        other_job = _make_job("ops_other", other)
        other_exec = _make_execution(other_job, started_offset=timedelta(hours=2))
        _seed_table(
            other_exec, decision="warning", confidence=0.4,
            dead_letter_count=10, rows_fetched=10,
        )

        rollup_mine = ops_metrics_service.compute_health_rollup(
            self.user, window_hours=24,
        )
        self.assertEqual(rollup_mine["totals"]["executions"], 1)
        self.assertEqual(rollup_mine["totals"]["warning"], 0)

    def test_compute_job_health_orders_by_last_started_desc(self):
        job_a = _make_job("ord_a", self.user)
        job_b = _make_job("ord_b", self.user)
        exec_a = _make_execution(job_a, started_offset=timedelta(hours=10))
        exec_b = _make_execution(job_b, started_offset=timedelta(hours=2))
        _seed_table(exec_a, decision="ok")
        _seed_table(exec_b, decision="warning", confidence=0.6)

        rows = ops_metrics_service.compute_job_health(
            self.user, window_hours=24,
        )
        # All three jobs should appear (self.job has no executions)
        names = [r["job_name"] for r in rows]
        self.assertIn("ord_b-job", names)
        self.assertIn("ord_a-job", names)
        # The most-recent run (ord_b, 2h ago) should be first.
        self.assertEqual(rows[0]["job_name"], "ord_b-job")

    def test_attempts_p95_handles_small_samples(self):
        # Single value -> percentile == max.
        self.assertEqual(ops_metrics_service._percentile([3], 0.95), 3.0)
        # Empty list -> 0.
        self.assertEqual(ops_metrics_service._percentile([], 0.95), 0.0)
        # Two-value sample -> max (degraded).
        self.assertEqual(ops_metrics_service._percentile([1, 2], 0.95), 2.0)
        # Larger sample -> proper percentile.
        large = [1] * 95 + [10] * 5
        result = ops_metrics_service._percentile(large, 0.95)
        self.assertGreaterEqual(result, 1.0)


class ExecutionSloStatusTests(TestCase):
    def setUp(self):
        self.user = _make_user("ops_slo_owner")
        self.job = _make_job("ops_slo", self.user)

    def test_execution_slo_status_clean_run(self):
        execution = _make_execution(self.job, started_offset=timedelta(hours=1))
        _seed_table(execution, decision="ok", confidence=1.0)
        status = ops_metrics_service.execution_slo_status(execution)
        self.assertTrue(status["slo"]["ok_rate"]["ok"])
        self.assertTrue(status["slo"]["dead_letter_pct"]["ok"])
        self.assertTrue(status["slo"]["attempts_p95"]["ok"])
        self.assertTrue(status["slo"]["confidence_floor"]["ok"])

    def test_execution_slo_status_marks_breaches(self):
        execution = _make_execution(self.job, started_offset=timedelta(hours=1))
        _seed_table(
            execution, decision="warning", confidence=0.5,
            attempts=4, dead_letter_count=20, rows_fetched=100,
        )
        status = ops_metrics_service.execution_slo_status(execution)
        self.assertFalse(status["slo"]["ok_rate"]["ok"])
        self.assertFalse(status["slo"]["dead_letter_pct"]["ok"])
        self.assertFalse(status["slo"]["confidence_floor"]["ok"])

    def test_latest_terminal_executions_for_job_orders_by_recency(self):
        e1 = _make_execution(self.job, started_offset=timedelta(hours=4))
        e2 = _make_execution(self.job, started_offset=timedelta(hours=2))
        e3 = _make_execution(self.job, started_offset=timedelta(hours=1))
        recent = ops_metrics_service.latest_terminal_executions_for_job(
            self.job, limit=10,
        )
        ids = [str(e.id) for e in recent]
        self.assertEqual(ids, [str(e3.id), str(e2.id), str(e1.id)])
