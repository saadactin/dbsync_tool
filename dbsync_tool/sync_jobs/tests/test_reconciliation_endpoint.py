"""Day-6 tests: reconciliation aggregation, JSON/CSV export, and download endpoint.

Covers:
- ``reconciliation_service.build_execution_report`` aggregation (pre+post packs).
- Either-side-missing tolerance (log without recon, recon without log).
- ``export_json`` / ``export_csv`` payload shape.
- ``GET /sync-jobs/<job>/executions/<execution>/reconciliation/`` returns
  attachment headers, and is tenant-scoped + login-required.
"""

from __future__ import annotations

import csv
import io
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_jobs.models import (
    ReconciliationReport,
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
)
from sync_jobs.services import reconciliation_service


def _make_user(username: str, password: str = "pw", role=Role.ADMIN, tenant=None):
    user = User.objects.create_user(
        username=username, password=password, email=f"{username}@example.com"
    )
    UserProfile.objects.update_or_create(
        user=user,
        defaults={"role": role, "tenant": tenant or user},
    )
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


class BuildExecutionReportTests(TestCase):
    def setUp(self):
        self.user = _make_user("rec_owner")
        self.job = _make_job("rec1", self.user)
        self.execution = SyncExecution.objects.create(
            job=self.job, status="completed", total_tables=2, completed_tables=2,
        )

    def test_aggregates_pre_post_packs(self):
        SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            status="completed",
            rows_fetched=1000,
            rows_inserted=996,
            attempts=1,
            dead_letter_count=4,
            verification_summary="Parity[sampled]: source=1000 target=996 decision=warning",
        )
        ReconciliationReport.objects.create(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            decision="warning",
            confidence=0.7,
            dq_pre_json={"warnings": ["pk_duplication"], "errors": []},
            dq_post_json={
                "warnings": ["distribution_drift"],
                "errors": [],
                "parity": {
                    "source_count": 1000,
                    "target_count": 996,
                    "sample_hash_match": False,
                    "decision": "warning",
                },
            },
            source_metrics_json={"row_count": 1000},
            target_metrics_json={"row_count": 996},
            drift_json={"distribution_drift": [{"column": "amount"}]},
        )

        report = reconciliation_service.build_execution_report(self.execution)

        self.assertEqual(report["schema_version"], reconciliation_service.SCHEMA_VERSION)
        self.assertEqual(report["execution"]["id"], str(self.execution.id))
        self.assertEqual(report["execution"]["job_id"], str(self.job.id))
        self.assertEqual(report["execution"]["job_name"], self.job.name)
        self.assertEqual(report["execution"]["sync_type"], "incremental")
        self.assertEqual(report["totals"]["tables"], 1)
        self.assertEqual(report["totals"]["warning"], 1)
        self.assertEqual(report["totals"]["dead_letter_count"], 4)
        self.assertEqual(report["totals"]["attempts_sum"], 1)

        self.assertEqual(len(report["tables"]), 1)
        t0 = report["tables"][0]
        self.assertEqual(t0["schema_name"], "public")
        self.assertEqual(t0["table_name"], "orders")
        self.assertEqual(t0["decision"], "warning")
        self.assertAlmostEqual(t0["confidence"], 0.7)
        self.assertEqual(t0["attempts"], 1)
        self.assertEqual(t0["dead_letter_count"], 4)
        self.assertEqual(t0["rows_fetched"], 1000)
        self.assertEqual(t0["rows_inserted"], 996)
        self.assertEqual(t0["dq_pre"]["warnings"], ["pk_duplication"])
        self.assertEqual(t0["dq_post"]["parity"]["source_count"], 1000)
        self.assertEqual(t0["drift"]["distribution_drift"][0]["column"], "amount")

    def test_handles_log_without_recon_row(self):
        SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name="public",
            table_name="legacy",
            status="completed",
            rows_fetched=10,
            rows_inserted=10,
        )

        report = reconciliation_service.build_execution_report(self.execution)
        self.assertEqual(report["totals"]["tables"], 1)
        self.assertEqual(report["totals"]["unknown"], 1)
        t0 = report["tables"][0]
        self.assertEqual(t0["decision"], "unknown")
        self.assertIsNone(t0["confidence"])
        self.assertEqual(t0["dq_pre"], {})
        self.assertEqual(t0["dq_post"], {})
        self.assertEqual(t0["rows_fetched"], 10)

    def test_handles_recon_row_without_log(self):
        ReconciliationReport.objects.create(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="skipped",
            decision="ok",
            confidence=1.0,
            dq_pre_json={"warnings": []},
            dq_post_json={},
        )

        report = reconciliation_service.build_execution_report(self.execution)
        self.assertEqual(report["totals"]["tables"], 1)
        self.assertEqual(report["totals"]["ok"], 1)
        t0 = report["tables"][0]
        self.assertEqual(t0["decision"], "ok")
        self.assertEqual(t0["rows_fetched"], 0)
        self.assertEqual(t0["rows_inserted"], 0)
        self.assertEqual(t0["attempts"], 0)
        self.assertIsNone(t0["last_error_code"])

    def test_export_json_is_valid_utf8_json(self):
        ReconciliationReport.objects.create(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            decision="ok",
            confidence=1.0,
            dq_pre_json={},
            dq_post_json={},
        )
        body = reconciliation_service.export_json(self.execution)
        self.assertIsInstance(body, bytes)
        decoded = json.loads(body.decode("utf-8"))
        self.assertEqual(decoded["execution"]["id"], str(self.execution.id))
        self.assertEqual(decoded["totals"]["ok"], 1)

    def test_export_csv_columns_are_stable_and_flat(self):
        ReconciliationReport.objects.create(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            decision="warning",
            confidence=0.55,
            dq_pre_json={"warnings": ["a", "b"], "errors": []},
            dq_post_json={
                "warnings": ["x"],
                "errors": ["y", "z"],
                "parity": {
                    "source_count": 100,
                    "target_count": 99,
                    "sample_hash_match": False,
                    "decision": "warning",
                },
            },
        )
        SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            status="completed",
            rows_fetched=100,
            rows_inserted=99,
            attempts=2,
            last_error_code="TIMEOUT",
            dead_letter_count=1,
        )

        body = reconciliation_service.export_csv(self.execution)
        text = body.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertEqual(tuple(header), reconciliation_service.CSV_COLUMNS)

        rows = list(reader)
        self.assertEqual(len(rows), 1)
        row = dict(zip(header, rows[0]))
        self.assertEqual(row["schema_name"], "public")
        self.assertEqual(row["table_name"], "orders")
        self.assertEqual(row["decision"], "warning")
        self.assertEqual(row["confidence"], "0.55")
        self.assertEqual(row["attempts"], "2")
        self.assertEqual(row["last_error_code"], "TIMEOUT")
        self.assertEqual(row["dead_letter_count"], "1")
        self.assertEqual(row["rows_fetched"], "100")
        self.assertEqual(row["rows_inserted"], "99")
        self.assertEqual(row["source_count"], "100")
        self.assertEqual(row["target_count"], "99")
        self.assertEqual(row["sample_hash_match"], "False")
        self.assertEqual(row["parity_decision"], "warning")
        self.assertEqual(row["dq_pre_warnings"], "2")
        self.assertEqual(row["dq_post_warnings"], "1")
        self.assertEqual(row["dq_post_errors"], "2")

    def test_has_drift_detects_warning_and_low_confidence(self):
        report_warning = {
            "tables": [{"decision": "warning", "confidence": 0.9}],
        }
        report_repair = {
            "tables": [{"decision": "repair_full", "confidence": 0.4}],
        }
        report_low_conf = {
            "tables": [{"decision": "ok", "confidence": 0.5}],
        }
        report_clean = {
            "tables": [{"decision": "ok", "confidence": 1.0}],
        }
        self.assertTrue(reconciliation_service.has_drift(report_warning))
        self.assertTrue(reconciliation_service.has_drift(report_repair))
        self.assertTrue(reconciliation_service.has_drift(report_low_conf))
        self.assertFalse(reconciliation_service.has_drift(report_clean))


class ReconciliationEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = _make_user("end_owner")
        self.job = _make_job("end1", self.user)
        self.execution = SyncExecution.objects.create(
            job=self.job, status="completed", total_tables=1, completed_tables=1,
        )
        ReconciliationReport.objects.create(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            decision="ok",
            confidence=1.0,
            dq_pre_json={},
            dq_post_json={},
        )
        SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            status="completed",
            rows_fetched=10,
            rows_inserted=10,
        )

    def _url(self) -> str:
        return reverse(
            "sync_jobs:execution_reconciliation",
            kwargs={"job_id": self.job.id, "execution_id": self.execution.id},
        )

    def test_endpoint_requires_login(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_endpoint_returns_json_with_attachment_disposition(self):
        self.client.force_login(self.user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn(
            f'reconciliation_{self.execution.id}.json',
            response["Content-Disposition"],
        )
        self.assertIn("attachment", response["Content-Disposition"])
        body = json.loads(response.content.decode("utf-8"))
        self.assertEqual(body["execution"]["id"], str(self.execution.id))

    def test_endpoint_returns_csv_with_attachment_disposition(self):
        self.client.force_login(self.user)
        response = self.client.get(self._url() + "?format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn(
            f'reconciliation_{self.execution.id}.csv',
            response["Content-Disposition"],
        )
        self.assertIn("attachment", response["Content-Disposition"])
        text = response.content.decode("utf-8")
        first_line = text.splitlines()[0]
        self.assertEqual(first_line.split(","), list(reconciliation_service.CSV_COLUMNS))

    def test_endpoint_is_tenant_scoped(self):
        other = _make_user("other_owner_x")
        self.client.force_login(other)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    def test_endpoint_unknown_format_falls_back_to_json(self):
        self.client.force_login(self.user)
        response = self.client.get(self._url() + "?format=xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_execution_detail_renders_quality_chip_and_download_links(self):
        """Day-6 sanity: execution_detail page renders the new Quality chip
        and Download report buttons without templatetag errors."""
        self.client.force_login(self.user)
        url = reverse(
            "sync_jobs:execution_detail",
            kwargs={"job_id": self.job.id, "execution_id": self.execution.id},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn(">Quality</th>", body)
        self.assertIn("Report (JSON)", body)
        self.assertIn("Report (CSV)", body)
        self.assertIn("OK", body)
