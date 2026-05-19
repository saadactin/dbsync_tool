from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from connections.models import DatabaseConnection
from sync_jobs.models import ReconciliationReport, SyncExecution, SyncExecutionLog, SyncJob


def _user(username: str) -> User:
    u = User.objects.create_user(username=username, password="pw", email=f"{username}@example.com")
    p = u.userprofile
    p.role = Role.ADMIN
    p.tenant = u
    p.save(update_fields=["role", "tenant"])
    return u


def _job(prefix: str, owner: User) -> SyncJob:
    s = DatabaseConnection.objects.create(
        name=f"{prefix}-src", db_type="postgres", host="localhost", port=5432,
        username="u", password="p", database_name="d", created_by=owner, tenant=owner,
    )
    t = DatabaseConnection.objects.create(
        name=f"{prefix}-tgt", db_type="postgres", host="localhost", port=5432,
        username="u", password="p", database_name="d", created_by=owner, tenant=owner,
    )
    return SyncJob.objects.create(
        name=f"{prefix}-job", source_connection_type="database",
        source_connection=s, target_connection=t, sync_type="incremental",
        created_by=owner, tenant=owner,
    )


def _exec(job: SyncJob, hours_ago: int, decision="ok"):
    e = SyncExecution.objects.create(job=job, status="completed")
    when = timezone.now() - timedelta(hours=hours_ago)
    SyncExecution.objects.filter(id=e.id).update(started_at=when, completed_at=when)
    e.refresh_from_db()
    SyncExecutionLog.objects.create(
        execution=e, schema_name="public", table_name="orders", status="completed",
        attempts=0, rows_fetched=10, rows_inserted=10, dead_letter_count=0,
    )
    ReconciliationReport.objects.create(
        execution=e, job=job, schema_name="public", table_name="orders",
        decision=decision, confidence=1.0 if decision == "ok" else 0.5,
    )
    return e


class OpsHealthViewTests(TestCase):
    def setUp(self):
        self.user = _user("ops_view_user")
        self.job = _job("ops_view", self.user)
        _exec(self.job, 1, decision="ok")
        self.url = reverse("sync_jobs:ops_health")

    def test_login_required(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_ops_health_redirects_to_dashboard(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("sync_jobs:dashboard"))

    def test_ops_health_redirect_ignores_window_query(self):
        self.client.force_login(self.user)
        resp = self.client.get(f"{self.url}?window=7d")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("sync_jobs:dashboard"))

    def test_dashboard_contains_embedded_reliability_insights(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("sync_jobs:dashboard"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn("Reliability Insights", body)
        self.assertIn("OK Rate", body)
        self.assertIn("Dead-letter %", body)
