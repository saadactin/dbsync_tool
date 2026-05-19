"""Day-5 unit tests for structured DQ pack computation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from connections.connectors.base import ColumnInfo
from sync_engine.dq.pack import (
    compute_post_pack,
    compute_pre_pack,
    discover_numeric_or_date_columns,
)
from sync_engine.verification import VerificationResult


def _pg_conn():
    c = MagicMock()
    type(c).__name__ = "PostgresConnector"
    return c


class DQPrePackTests(SimpleTestCase):
    def test_pre_pack_happy_path_postgres(self):
        conn = _pg_conn()
        conn.count_rows = MagicMock(return_value=100)
        conn.execute_query_fetchall = MagicMock(
            side_effect=[
                [(100, 100)],
                [(0.0,)],
                [("2020-01-01", "2021-01-01")],
            ]
        )
        job = MagicMock()
        job_table = MagicMock()
        execution = MagicMock()
        pack = compute_pre_pack(
            execution=execution,
            job=job,
            job_table=job_table,
            source_connector=conn,
            source_schema="public",
            source_table="t",
            sync_mode="incremental",
            incremental_column="updated_at",
            pk_columns=["id"],
        )
        self.assertEqual(pack.metrics["source"]["row_count"], 100)
        self.assertTrue(pack.metrics["source"]["pk_unique"])
        self.assertEqual(pack.metrics["source"]["null_ratio"].get("id"), 0.0)

    def test_pre_pack_skips_pk_unique_when_no_pk(self):
        conn = _pg_conn()
        conn.count_rows = MagicMock(return_value=10)
        conn.execute_query_fetchall = MagicMock()
        pack = compute_pre_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=conn,
            source_schema="public",
            source_table="t",
            pk_columns=[],
        )
        self.assertEqual(pack.metrics["source"]["pk_unique_skipped_reason"], "no_pk_columns")
        conn.execute_query_fetchall.assert_not_called()

    def test_pre_pack_records_schema_drift_added_columns(self):
        conn = _pg_conn()
        conn.count_rows = MagicMock(return_value=1)
        conn.execute_query_fetchall = MagicMock(return_value=[(1, 1)])
        pack = compute_pre_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=conn,
            source_schema="public",
            source_table="t",
            pk_columns=["id"],
            schema_drift_added_columns=["new_col"],
        )
        self.assertEqual(pack.metrics["schema_drift"]["added_columns"], ["new_col"])

    def test_pre_pack_swallows_count_failure_and_records_error(self):
        conn = _pg_conn()
        conn.count_rows = MagicMock(side_effect=RuntimeError("boom"))
        pack = compute_pre_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=conn,
            source_schema="public",
            source_table="t",
            pk_columns=["id"],
        )
        self.assertIsNone(pack.metrics["source"]["row_count"])
        self.assertTrue(any("boom" in e for e in pack.errors))

    def test_no_exception_ever_escapes_compute_pre_pack(self):
        conn = _pg_conn()
        conn.count_rows = MagicMock(side_effect=RuntimeError("x"))
        with patch(
            "sync_engine.dq.pack._compute_pre_pack_core",
            side_effect=RuntimeError("core boom"),
        ):
            pack = compute_pre_pack(
                execution=MagicMock(),
                job=MagicMock(),
                job_table=MagicMock(),
                source_connector=conn,
                source_schema="public",
                source_table="t",
                pk_columns=[],
            )
        self.assertIn("schema_version", pack.metrics)
        self.assertEqual(pack.confidence, 0.0)


class DQPostPackTests(SimpleTestCase):
    def _base_conns(self, *, with_distribution: bool = False):
        src = _pg_conn()
        tgt = _pg_conn()
        src.count_rows = MagicMock(return_value=50)
        tgt.count_rows = MagicMock(return_value=50)
        if with_distribution:
            tgt.execute_query_fetchall = MagicMock(
                side_effect=[[(0,)], [(0,)], [(1, 2, 3.0)]]
            )
            src.execute_query_fetchall = MagicMock(
                side_effect=[[(0,)], [(1, 2, 3.0)]]
            )
        else:
            tgt.execute_query_fetchall = MagicMock(side_effect=[[(0,)], [(0,)]])
            src.execute_query_fetchall = MagicMock(side_effect=[[(0,)]])
        return src, tgt

    def test_post_pack_decision_ok_with_clean_parity(self):
        src, tgt = self._base_conns(with_distribution=True)
        parity = VerificationResult(
            decision="ok",
            source_count=50,
            target_count=50,
            sample_hash_match=True,
            details="",
        )
        pack = compute_post_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=src,
            target_connector=tgt,
            source_schema="public",
            source_table="t",
            target_schema="public",
            target_table="t2",
            parity_result=parity,
            pk_columns=["id"],
            numeric_columns=["id"],
        )
        self.assertEqual(pack.decision, "ok")

    def test_post_pack_decision_repair_full_on_parity_drift(self):
        src, tgt = self._base_conns()
        parity = VerificationResult(
            decision="repair_full",
            source_count=10,
            target_count=9,
            sample_hash_match=False,
            details="",
        )
        pack = compute_post_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=src,
            target_connector=tgt,
            source_schema="public",
            source_table="t",
            target_schema="public",
            target_table="t2",
            parity_result=parity,
            pk_columns=["id"],
            numeric_columns=[],
        )
        self.assertEqual(pack.decision, "repair_full")

    def test_post_pack_decision_warning_when_pk_dupes_present(self):
        src, tgt = self._base_conns()
        tgt.execute_query_fetchall = MagicMock(
            side_effect=[
                [(3,)],
                [(0,)],
                [(0,)],
            ]
        )
        parity = VerificationResult(
            decision="ok",
            source_count=5,
            target_count=5,
            sample_hash_match=True,
            details="",
        )
        pack = compute_post_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=src,
            target_connector=tgt,
            source_schema="public",
            source_table="t",
            target_schema="public",
            target_table="t2",
            parity_result=parity,
            pk_columns=["id"],
            numeric_columns=[],
        )
        self.assertEqual(pack.decision, "warning")

    def test_post_pack_distribution_drift_skipped_when_aggregate_fails(self):
        src, tgt = self._base_conns(with_distribution=True)
        tgt.execute_query_fetchall = MagicMock(side_effect=[(0,), (0,), (0,), None])
        src.execute_query_fetchall = MagicMock(side_effect=[(0,), (1, 2, 3.0)])
        parity = VerificationResult(
            decision="ok",
            source_count=1,
            target_count=1,
            sample_hash_match=True,
            details="",
        )
        pack = compute_post_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=src,
            target_connector=tgt,
            source_schema="public",
            source_table="t",
            target_schema="public",
            target_table="t2",
            parity_result=parity,
            pk_columns=["id"],
            numeric_columns=["id"],
        )
        drift = pack.metrics["distribution_drift"]["id"]
        self.assertEqual(drift["skipped_reason"], "aggregate_unsupported")

    def test_post_pack_dead_letter_count_demotes_to_warning(self):
        src, tgt = self._base_conns()
        parity = VerificationResult(
            decision="ok",
            source_count=10,
            target_count=10,
            sample_hash_match=True,
            details="",
        )
        pack = compute_post_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=src,
            target_connector=tgt,
            source_schema="public",
            source_table="t",
            target_schema="public",
            target_table="t2",
            parity_result=parity,
            pk_columns=["id"],
            numeric_columns=[],
            dead_letter_count=2,
        )
        self.assertEqual(pack.decision, "warning")

    def test_post_pack_confidence_drops_per_error(self):
        src, tgt = self._base_conns()
        tgt.count_rows = MagicMock(side_effect=RuntimeError("no"))
        parity = VerificationResult(
            decision="ok",
            source_count=1,
            target_count=1,
            sample_hash_match=True,
            details="",
        )
        pack = compute_post_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=src,
            target_connector=tgt,
            source_schema="public",
            source_table="t",
            target_schema="public",
            target_table="t2",
            parity_result=parity,
            pk_columns=[],
            numeric_columns=[],
        )
        self.assertLess(pack.confidence, 1.0)

    def test_flat_file_skips_source_side_distribution_and_null_parity(self):
        conn = _pg_conn()
        conn.count_rows = MagicMock(return_value=5)
        conn.execute_query_fetchall = MagicMock(
            side_effect=[[(0,)], [(0,)], [(0,)]]
        )
        parity = None
        pack = compute_post_pack(
            execution=MagicMock(),
            job=MagicMock(),
            job_table=MagicMock(),
            source_connector=conn,
            target_connector=conn,
            source_schema="public",
            source_table="t",
            target_schema="public",
            target_table="t2",
            parity_result=parity,
            pk_columns=["id"],
            numeric_columns=["id"],
            flat_file=True,
        )
        self.assertEqual(pack.metrics["distribution_drift"], {})
        self.assertEqual(pack.metrics["target"]["null_count_parity"], {})

    def test_no_exception_ever_escapes_compute_post_pack(self):
        src, tgt = self._base_conns()
        with patch(
            "sync_engine.dq.pack._compute_post_pack_core",
            side_effect=RuntimeError("post core boom"),
        ):
            pack = compute_post_pack(
                execution=MagicMock(),
                job=MagicMock(),
                job_table=MagicMock(),
                source_connector=src,
                target_connector=tgt,
                source_schema="public",
                source_table="t",
                target_schema="public",
                target_table="t2",
            )
        self.assertEqual(pack.decision, "warning")
        self.assertEqual(pack.confidence, 0.0)


class DiscoverNumericColumnsTests(SimpleTestCase):
    def test_discover_from_column_infos(self):
        from sync_engine.dq.pack import numeric_columns_from_column_infos

        cols = [
            ColumnInfo(name="a", data_type="varchar", is_nullable=True),
            ColumnInfo(name="b", data_type="int4", is_nullable=True),
            ColumnInfo(name="c", data_type="float", is_nullable=True),
        ]
        names = numeric_columns_from_column_infos(cols, limit=8)
        self.assertEqual(names, ["b", "c"])

    def test_discover_numeric_or_date_columns_warns_without_get_columns(self):
        c = MagicMock(spec=["count_rows"])
        names, warns = discover_numeric_or_date_columns(c, "s", "t")
        self.assertEqual(names, [])
        self.assertTrue(warns)
