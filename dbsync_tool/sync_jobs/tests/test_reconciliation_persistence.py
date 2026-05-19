"""Day-5 tests for DQ pack persistence on ReconciliationReport + SVR mirror."""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_engine.dq.pack import compute_post_pack, compute_pre_pack
from sync_engine.dq.persistence import persist_dq_packs
from sync_engine.verification import VerificationResult
from sync_jobs.models import (
    ReconciliationReport,
    SyncExecution,
    SyncJob,
    SyncJobTable,
    SyncVerificationReport,
)


def _setup_job(prefix: str):
    user = User.objects.create_user(f"{prefix}_u", f"{prefix}@example.com", "pw")
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
    job = SyncJob.objects.create(
        name=f"{prefix}job",
        source_connection_type="database",
        source_connection=src,
        target_connection=tgt,
        sync_type="incremental",
        created_by=user,
        tenant=user,
    )
    execution = SyncExecution.objects.create(job=job, status="running")
    jt = SyncJobTable.objects.create(job=job, schema_name="public", table_name="orders")
    return user, job, execution, jt


class ReconciliationPersistenceTests(TestCase):
    def test_persist_dq_packs_creates_one_report_per_table(self):
        _, job, execution, jt = _setup_job("dq1")
        conn = MagicMock()
        type(conn).__name__ = "PostgresConnector"
        conn.count_rows = MagicMock(return_value=1)
        conn.execute_query_fetchall = MagicMock(
            side_effect=[[(1, 1)], [(0,)], [(0,)]]
        )

        pre = compute_pre_pack(
            execution=execution,
            job=job,
            job_table=jt,
            source_connector=conn,
            source_schema="public",
            source_table="orders",
            pk_columns=["id"],
        )
        post = compute_post_pack(
            execution=execution,
            job=job,
            job_table=jt,
            source_connector=conn,
            target_connector=conn,
            source_schema="public",
            source_table="orders",
            target_schema="public",
            target_table="orders",
            parity_result=None,
            pk_columns=["id"],
            numeric_columns=[],
            flat_file=True,
        )
        persist_dq_packs(
            execution=execution,
            job=job,
            job_table=jt,
            source_schema="public",
            source_table="orders",
            pre_pack=pre,
            post_pack=post,
        )
        self.assertEqual(ReconciliationReport.objects.filter(execution=execution).count(), 1)
        row = ReconciliationReport.objects.get(execution=execution, schema_name="public", table_name="orders")
        self.assertTrue(row.dq_pre_json)
        self.assertTrue(row.dq_post_json)

    def test_persist_dq_packs_is_idempotent_on_rerun(self):
        _, job, execution, jt = _setup_job("dq2")
        conn = MagicMock()
        type(conn).__name__ = "PostgresConnector"
        conn.count_rows = MagicMock(return_value=2)
        conn.execute_query_fetchall = MagicMock(side_effect=[[(2, 2)], [(0,)]])

        pre = compute_pre_pack(
            execution=execution,
            job=job,
            job_table=jt,
            source_connector=conn,
            source_schema="public",
            source_table="t",
            pk_columns=["id"],
        )
        persist_dq_packs(
            execution=execution,
            job=job,
            job_table=jt,
            source_schema="public",
            source_table="t",
            pre_pack=pre,
            post_pack=None,
        )
        rid_first = ReconciliationReport.objects.get(
            execution=execution, schema_name="public", table_name="t"
        ).id
        persist_dq_packs(
            execution=execution,
            job=job,
            job_table=jt,
            source_schema="public",
            source_table="t",
            pre_pack=pre,
            post_pack=None,
        )
        rid_second = ReconciliationReport.objects.get(
            execution=execution, schema_name="public", table_name="t"
        ).id
        self.assertEqual(rid_first, rid_second)
        self.assertEqual(ReconciliationReport.objects.filter(execution=execution).count(), 1)

    def test_persist_dq_packs_mirrors_into_sync_verification_report_metrics_json(self):
        _, job, execution, jt = _setup_job("dq3")
        conn = MagicMock()
        type(conn).__name__ = "PostgresConnector"
        conn.count_rows = MagicMock(return_value=1)
        conn.execute_query_fetchall = MagicMock(return_value=[(0,), (0,), (0,)])

        SyncVerificationReport.objects.create(
            job=job,
            execution=execution,
            schema_name="public",
            table_name="u",
            sync_mode="incremental",
            source_count=1,
            target_count=1,
            decision="ok",
            details="x",
        )
        pre = compute_pre_pack(
            execution=execution,
            job=job,
            job_table=jt,
            source_connector=conn,
            source_schema="public",
            source_table="u",
            pk_columns=["id"],
        )
        post = compute_post_pack(
            execution=execution,
            job=job,
            job_table=jt,
            source_connector=conn,
            target_connector=conn,
            source_schema="public",
            source_table="u",
            target_schema="public",
            target_table="u",
            parity_result=None,
            pk_columns=["id"],
            numeric_columns=[],
            flat_file=True,
        )
        persist_dq_packs(
            execution=execution,
            job=job,
            job_table=jt,
            source_schema="public",
            source_table="u",
            pre_pack=pre,
            post_pack=post,
        )
        svr = SyncVerificationReport.objects.get(
            execution=execution, schema_name="public", table_name="u"
        )
        self.assertIn("dq_pre", svr.metrics_json)
        self.assertIn("dq_post", svr.metrics_json)
        self.assertEqual(svr.metrics_json["decision"], post.decision)

    def test_persist_dq_packs_swallows_db_error_and_logs(self):
        _, job, execution, jt = _setup_job("dq4")
        pre = compute_pre_pack(
            execution=execution,
            job=job,
            job_table=jt,
            source_connector=MagicMock(),
            source_schema="public",
            source_table="z",
            pk_columns=[],
            flat_file_skip_source_metrics=True,
        )
        with patch(
            "sync_engine.dq.persistence.transaction.atomic",
            side_effect=RuntimeError("db boom"),
        ):
            out = persist_dq_packs(
                execution=execution,
                job=job,
                job_table=jt,
                source_schema="public",
                source_table="z",
                pre_pack=pre,
                post_pack=None,
            )
        self.assertIsNone(out)

    def test_dq_persistence_independent_of_strict_mode_failure_path(self):
        _, job, execution, jt = _setup_job("dq5")
        conn = MagicMock()
        type(conn).__name__ = "PostgresConnector"
        conn.count_rows = MagicMock(return_value=10)
        conn.execute_query_fetchall = MagicMock(side_effect=[[(0,)]])
        parity = VerificationResult(
            decision="repair_full",
            source_count=10,
            target_count=9,
            sample_hash_match=False,
            details="",
        )
        post = compute_post_pack(
            execution=execution,
            job=job,
            job_table=jt,
            source_connector=conn,
            target_connector=conn,
            source_schema="public",
            source_table="w",
            target_schema="public",
            target_table="w",
            parity_result=parity,
            pk_columns=["id"],
            numeric_columns=[],
            flat_file=True,
        )
        persist_dq_packs(
            execution=execution,
            job=job,
            job_table=jt,
            source_schema="public",
            source_table="w",
            pre_pack=None,
            post_pack=post,
        )
        row = ReconciliationReport.objects.get(execution=execution, table_name="w")
        self.assertEqual(row.decision, "repair_full")
