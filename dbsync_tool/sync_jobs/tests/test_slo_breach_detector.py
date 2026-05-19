from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role
from connections.models import DatabaseConnection
from sync_jobs.models import ReconciliationReport, SyncExecution, SyncExecutionLog, SyncJob
from sync_jobs.services import ops_metrics_service, sync_email_service


def _make_user(username: str) -> User:
    user = User.objects.create_user(
        username=username, password="pw", email=f"{username}@example.com"
    )
    profile = user.userprofile
    profile.role = Role.ADMIN
    profile.tenant = user
    profile.save(update_fields=["role", "tenant"])
    return user


def _make_job(prefix: str, owner: User) -> SyncJob:
    src = DatabaseConnection.objects.create(
        name=f"{prefix}-src", db_type="postgres", host="localhost", port=5432,
        username="u", password="p", database_name="d", created_by=owner, tenant=owner,
    )
    tgt = DatabaseConnection.objects.create(
        name=f"{prefix}-tgt", db_type="postgres", host="localhost", port=5432,
        username="u", password="p", database_name="d", created_by=owner, tenant=owner,
    )
    return SyncJob.objects.create(
        name=f"{prefix}-job", source_connection_type="database",
        source_connection=src, target_connection=tgt, sync_type="incremental",
        created_by=owner, tenant=owner,
    )


def _make_execution(job: SyncJob, hours_ago: int) -> SyncExecution:
    execution = SyncExecution.objects.create(job=job, status="completed")
    when = timezone.now() - timedelta(hours=hours_ago)
    SyncExecution.objects.filter(id=execution.id).update(started_at=when, completed_at=when)
    execution.refresh_from_db()
    return execution


def _seed(execution: SyncExecution, *, decision: str, confidence: float = 1.0, dead_letter=0, fetched=100):
    SyncExecutionLog.objects.create(
        execution=execution, schema_name="public", table_name="orders",
        status="completed", attempts=0, dead_letter_count=dead_letter,
        rows_fetched=fetched, rows_inserted=max(0, fetched - dead_letter),
    )
    ReconciliationReport.objects.create(
        execution=execution, job=execution.job, schema_name="public",
        table_name="orders", decision=decision, confidence=confidence,
    )


class SloBreachDetectorTests(TestCase):
    @override_settings(SLO_BREACH_STREAK_N=3)
    def test_streak_threshold_and_reset(self):
        user = _make_user("slo_user")
        job = _make_job("slo", user)
        e1 = _make_execution(job, 6); _seed(e1, decision="warning")
        e2 = _make_execution(job, 4); _seed(e2, decision="ok")
        e3 = _make_execution(job, 2); _seed(e3, decision="warning")
        self.assertEqual(ops_metrics_service.detect_slo_breach(e3), [])

        e4 = _make_execution(job, 1); _seed(e4, decision="warning")
        e5 = _make_execution(job, 0); _seed(e5, decision="warning")
        slos = {b["slo"] for b in ops_metrics_service.detect_slo_breach(e5)}
        self.assertIn("ok_rate", slos)

    @override_settings(SLO_BREACH_STREAK_N=2, SLO_DEAD_LETTER_PCT_MAX=0.001)
    def test_dead_letter_pct_breach(self):
        user = _make_user("dl_user")
        job = _make_job("dl", user)
        e1 = _make_execution(job, 2); _seed(e1, decision="ok", dead_letter=10, fetched=100)
        e2 = _make_execution(job, 1); _seed(e2, decision="ok", dead_letter=5, fetched=100)
        slos = {b["slo"] for b in ops_metrics_service.detect_slo_breach(e2)}
        self.assertIn("dead_letter_pct", slos)


class SloBreachEmailAndHookTests(TestCase):
    def setUp(self):
        self.user = _make_user("email_user")
        self.job = _make_job("email", self.user)
        self.execution = _make_execution(self.job, 1)
        _seed(self.execution, decision="warning", confidence=0.4)

    @override_settings(
        DEFAULT_FROM_EMAIL="dbsync@example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ADMIN_EMAILS=["ops@example.com"],
    )
    def test_email_subject_body_and_smtp_swallow(self):
        breaches = [{"slo": "ok_rate", "value": 0.5, "target": 0.99, "streak": 3}]
        self.assertTrue(sync_email_service.send_slo_breach_email(self.execution, breaches))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("SLO breach", mail.outbox[0].subject)
        self.assertIn("ok_rate", mail.outbox[0].body)

        with patch("sync_jobs.services.sync_email_service.send_mail", side_effect=RuntimeError("smtp")):
            self.assertFalse(sync_email_service.send_slo_breach_email(self.execution, breaches))

    def test_executor_hook_ordering(self):
        from sync_engine.executor import SyncExecutor

        class _Stub(SyncExecutor):
            def __init__(self):
                pass

        with patch(
            "sync_jobs.services.sync_email_service.send_execution_summary_email",
            return_value={"sent": True, "error_message": "", "recipients": ["x@y"]},
        ), patch(
            "sync_jobs.services.sync_email_service.send_drift_alert",
            return_value=False,
        ) as drift_mock, patch(
            "sync_jobs.services.ops_metrics_service.detect_slo_breach",
            return_value=[{"slo": "ok_rate", "value": 0.0, "target": 0.99, "streak": 3}],
        ) as detect_mock, patch(
            "sync_jobs.services.sync_email_service.send_slo_breach_email",
            return_value=True,
        ) as send_mock:
            _Stub()._send_summary_email(self.execution)

        drift_mock.assert_called_once_with(self.execution)
        detect_mock.assert_called_once_with(self.execution)
        send_mock.assert_called_once_with(self.execution, [{"slo": "ok_rate", "value": 0.0, "target": 0.99, "streak": 3}])
