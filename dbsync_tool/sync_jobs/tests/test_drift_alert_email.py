"""Day-6 tests: drift alert email + structured DRIFT_LOG.

Covers:
- ``send_drift_alert`` with no drift logs INFO and does not call ``send_mail``.
- A ``warning`` decision triggers a single batched email.
- A ``repair_full`` decision triggers an alert.
- SMTP failures are swallowed and logged via DRIFT_LOG.exception.
- Recipients match ``resolve_summary_recipients`` exactly.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_jobs.models import (
    ReconciliationReport,
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
)
from sync_jobs.services.sync_email_service import (
    DRIFT_LOG,
    resolve_summary_recipients,
    send_drift_alert,
)


def _make_user(username: str, email: str | None = None) -> User:
    user = User.objects.create_user(
        username=username,
        password="pw",
        email=email or f"{username}@example.com",
    )
    UserProfile.objects.update_or_create(
        user=user,
        defaults={"role": Role.ADMIN, "tenant": user},
    )
    return user


def _make_execution(prefix: str, user: User, decision: str = "ok",
                    confidence: float = 1.0) -> SyncExecution:
    src = DatabaseConnection.objects.create(
        name=f"{prefix}-src",
        db_type="postgres",
        host="localhost",
        port=5432,
        username="u",
        password="p",
        database_name="db_src",
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
        database_name="db_tgt",
        created_by=user,
        tenant=user,
    )
    job = SyncJob.objects.create(
        name=f"{prefix}-job",
        source_connection_type="database",
        source_connection=src,
        target_connection=tgt,
        sync_type="incremental",
        created_by=user,
        tenant=user,
    )
    execution = SyncExecution.objects.create(
        job=job, status="completed", total_tables=1, completed_tables=1,
    )
    ReconciliationReport.objects.create(
        execution=execution,
        job=job,
        schema_name="public",
        table_name="orders",
        decision=decision,
        confidence=confidence,
        dq_pre_json={},
        dq_post_json={},
    )
    SyncExecutionLog.objects.create(
        execution=execution,
        schema_name="public",
        table_name="orders",
        status="completed",
        rows_fetched=10,
        rows_inserted=10,
    )
    return execution


class DriftAlertTests(TestCase):
    @override_settings(ADMIN_EMAILS=["ops@example.com"])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_no_drift_no_email_only_log(self, mock_send_mail):
        execution = _make_execution("d_no_drift", _make_user("d_owner_1"), decision="ok")
        with self.assertLogs(DRIFT_LOG, level=logging.INFO) as captured:
            sent = send_drift_alert(execution)
        self.assertFalse(sent)
        mock_send_mail.assert_not_called()
        joined = "\n".join(captured.output)
        self.assertIn("no drift", joined)

    @override_settings(ADMIN_EMAILS=["ops@example.com"])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_drift_email_sent_for_warning_decision(self, mock_send_mail):
        execution = _make_execution(
            "d_warn", _make_user("d_owner_2"), decision="warning", confidence=0.7,
        )
        with self.assertLogs(DRIFT_LOG, level=logging.WARNING) as captured:
            sent = send_drift_alert(execution)
        self.assertTrue(sent)
        mock_send_mail.assert_called_once()
        kwargs = mock_send_mail.call_args.kwargs
        self.assertIn("Drift detected", kwargs["subject"])
        self.assertIn("ops@example.com", kwargs["recipient_list"])
        body_text = kwargs["message"]
        self.assertIn("public.orders", body_text)
        self.assertIn("WARNING", body_text)
        joined = "\n".join(captured.output)
        self.assertIn("drift alert sent", joined)

    @override_settings(ADMIN_EMAILS=["ops@example.com"])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_drift_email_sent_for_repair_full_decision(self, mock_send_mail):
        execution = _make_execution(
            "d_repair", _make_user("d_owner_3"), decision="repair_full", confidence=0.4,
        )
        sent = send_drift_alert(execution)
        self.assertTrue(sent)
        mock_send_mail.assert_called_once()
        body_text = mock_send_mail.call_args.kwargs["message"]
        self.assertIn("REPAIR_FULL", body_text)

    @override_settings(ADMIN_EMAILS=["ops@example.com"])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_drift_email_swallowed_on_smtp_failure_and_logged(self, mock_send_mail):
        mock_send_mail.side_effect = RuntimeError("smtp boom")
        execution = _make_execution(
            "d_smtp", _make_user("d_owner_4"), decision="warning", confidence=0.7,
        )
        with self.assertLogs(DRIFT_LOG, level=logging.ERROR) as captured:
            sent = send_drift_alert(execution)
        self.assertFalse(sent)
        joined = "\n".join(captured.output)
        self.assertIn("drift alert send failed", joined)

    @override_settings(ADMIN_EMAILS=["ops@example.com", "ops2@example.com"])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_drift_email_recipients_match_summary_recipients(self, mock_send_mail):
        owner = _make_user("d_owner_5", email="creator@example.com")
        execution = _make_execution(
            "d_recip", owner, decision="warning", confidence=0.7,
        )
        sent = send_drift_alert(execution)
        self.assertTrue(sent)
        actual = mock_send_mail.call_args.kwargs["recipient_list"]
        expected = resolve_summary_recipients(execution)
        self.assertEqual(actual, expected)

    @override_settings(ADMIN_EMAILS=[])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_drift_with_no_recipients_logs_warning_and_skips_send(self, mock_send_mail):
        owner = User.objects.create_user(
            username="d_owner_6", password="pw", email="",
        )
        UserProfile.objects.update_or_create(
            user=owner,
            defaults={"role": Role.ADMIN, "tenant": owner},
        )
        execution = _make_execution(
            "d_no_recip", owner, decision="warning", confidence=0.7,
        )
        with self.assertLogs(DRIFT_LOG, level=logging.WARNING) as captured:
            sent = send_drift_alert(execution)
        self.assertFalse(sent)
        mock_send_mail.assert_not_called()
        joined = "\n".join(captured.output)
        self.assertIn("no valid recipients", joined)
