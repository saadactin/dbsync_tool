from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Role
from connections.models import DatabaseConnection
from sync_engine.dq.persistence import persist_dq_packs
from sync_jobs.models import ReconciliationReport, SyncDeadLetterRow, SyncExecution, SyncJob, SyncJobTable


class _Pack:
    def __init__(self, decision="ok", confidence=1.0):
        self.decision = decision
        self.confidence = confidence
        self.metrics = {"parity": {"decision": decision}, "target": {}, "distribution_drift": {}}


def _setup(prefix: str):
    u = User.objects.create_user(f"{prefix}_u", f"{prefix}@x.com", "pw")
    p = u.userprofile
    p.role = Role.ADMIN
    p.tenant = u
    p.save(update_fields=["role", "tenant"])
    s = DatabaseConnection.objects.create(
        name=f"{prefix}-s", db_type="postgres", host="localhost", port=5432,
        username="u", password="p", database_name="d", created_by=u, tenant=u,
    )
    t = DatabaseConnection.objects.create(
        name=f"{prefix}-t", db_type="postgres", host="localhost", port=5432,
        username="u", password="p", database_name="d2", created_by=u, tenant=u,
    )
    job = SyncJob.objects.create(
        name=f"{prefix}-job", source_connection_type="database", source_connection=s,
        target_connection=t, sync_type="incremental", created_by=u, tenant=u,
    )
    ex = SyncExecution.objects.create(job=job, status="completed")
    jt = SyncJobTable.objects.create(job=job, schema_name="public", table_name="orders")
    return u, job, ex, jt


class SnapshotPersistenceTests(TestCase):
    def test_populated_for_non_ok(self):
        _, job, ex, jt = _setup("snap1")
        SyncDeadLetterRow.objects.create(
            execution=ex, job=job, schema_name="public", table_name="orders",
            batch_id="b1", source_pk_text="1", source_row_hash="h1",
            raw_row_json={"id": 1}, error_code="E1", error_message="bad row",
        )
        persist_dq_packs(
            execution=ex, job=job, job_table=jt, source_schema="public", source_table="orders",
            pre_pack=_Pack("ok", 1.0), post_pack=_Pack("warning", 0.6), parity_result=None,
        )
        rr = ReconciliationReport.objects.get(execution=ex, schema_name="public", table_name="orders")
        snap = rr.snapshots_json or {}
        self.assertEqual(snap.get("row_count"), 1)
        self.assertEqual(len(snap.get("rows") or []), 1)

    def test_skipped_for_ok(self):
        _, job, ex, jt = _setup("snap2")
        SyncDeadLetterRow.objects.create(
            execution=ex, job=job, schema_name="public", table_name="orders",
            batch_id="b1", source_pk_text="1", source_row_hash="h1",
            raw_row_json={"id": 1}, error_code="E1", error_message="bad row",
        )
        persist_dq_packs(
            execution=ex, job=job, job_table=jt, source_schema="public", source_table="orders",
            pre_pack=_Pack("ok", 1.0), post_pack=_Pack("ok", 1.0), parity_result=None,
        )
        rr = ReconciliationReport.objects.get(execution=ex, schema_name="public", table_name="orders")
        self.assertEqual(rr.snapshots_json, {})

    def test_capped_at_50(self):
        _, job, ex, jt = _setup("snap3")
        rows = []
        for i in range(60):
            rows.append(SyncDeadLetterRow(
                execution=ex, job=job, schema_name="public", table_name="orders",
                batch_id="b", source_pk_text=str(i), source_row_hash=f"h{i}",
                raw_row_json={"id": i}, error_code="E", error_message=f"bad {i}",
            ))
        SyncDeadLetterRow.objects.bulk_create(rows)
        persist_dq_packs(
            execution=ex, job=job, job_table=jt, source_schema="public", source_table="orders",
            pre_pack=_Pack("ok", 1.0), post_pack=_Pack("warning", 0.4), parity_result=None,
        )
        rr = ReconciliationReport.objects.get(execution=ex, schema_name="public", table_name="orders")
        snap = rr.snapshots_json or {}
        self.assertEqual(snap.get("limit"), 50)
        self.assertEqual(len(snap.get("rows") or []), 50)

    def test_failure_swallowed(self):
        _, job, ex, jt = _setup("snap4")
        with patch("sync_engine.dq.persistence._build_snapshots", side_effect=RuntimeError("boom")):
            result = persist_dq_packs(
                execution=ex, job=job, job_table=jt, source_schema="public", source_table="orders",
                pre_pack=_Pack("ok", 1.0), post_pack=_Pack("warning", 0.5), parity_result=None,
            )
        self.assertIsNotNone(result)
