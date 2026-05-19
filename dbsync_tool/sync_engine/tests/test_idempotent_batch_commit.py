"""Tests for the Day-2 idempotent batch commit + dual-pointer checkpoints.

These tests live at the unit level: they exercise ``BatchCoordinator``,
``recover_table``, and the new ``CheckpointManager`` methods without
spinning up a real source/target database. The only DB touched is the
Django metadata DB (sqlite by default in dev).

Coverage goals (from the Day-2 plan):
  * happy path: begin -> commit advances marker + dual-pointer checkpoint
  * idempotency probe skips already-committed batches
  * double-commit on a committed marker raises IdempotencyViolation
  * crash between target write and marker commit is safe on replay
  * crash between marker commit and checkpoint update is atomic (txn rollback)
  * recovery sweep flips stale 'started' markers to 'failed' and sets
    checkpoint_status='recovering'
  * dual-pointer resume skips already-committed batches end-to-end
  * non-transactional target path runs the same lifecycle without a
    target SQL transaction
"""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_engine.checkpoint_manager import CheckpointManager
from sync_engine.reliability import (
    BatchCoordinator,
    IdempotencyViolation,
    recover_table,
)
from sync_jobs.models import (
    ProcessedBatch,
    SyncCheckpoint,
    SyncExecution,
    SyncJob,
)


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


def _make_job_execution(prefix: str, *, sync_type: str = "incremental"):
    user, src, tgt = _make_user_and_conns(prefix)
    job = SyncJob.objects.create(
        name=f"{prefix}-job",
        source_connection_type="database",
        source_connection=src,
        target_connection=tgt,
        sync_type=sync_type,
        created_by=user,
        tenant=user,
    )
    execution = SyncExecution.objects.create(job=job)
    return user, job, execution


class BatchIdHelpersTests(TestCase):
    def test_make_batch_id_is_zero_padded_and_deterministic(self):
        _, job, execution = _make_job_execution("bid")
        coord = BatchCoordinator(
            execution=execution,
            job=job,
            schema_name="public",
            table_name="orders",
            target_db_type="postgres",
        )
        self.assertEqual(coord.make_batch_id(1), "b000001")
        self.assertEqual(coord.make_batch_id(123), "b000123")
        self.assertEqual(coord.make_batch_id(1), coord.make_batch_id(1))


class HappyPathTests(TestCase):
    def setUp(self):
        _, self.job, self.execution = _make_job_execution("hp")
        self.cpm = CheckpointManager(self.job)
        self.coord = BatchCoordinator(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            target_db_type="postgres",
        )

    def test_begin_then_commit_creates_marker_and_advances_checkpoint(self):
        bid = self.coord.make_batch_id(1)

        marker = self.coord.begin_batch(bid, expected_row_count=50)
        self.assertEqual(marker.status, "started")
        self.assertEqual(marker.row_count, 50)

        self.coord.commit_batch(
            marker,
            rows_written=50,
            last_seen="2024-01-01T00:00:00",
            last_committed="2024-01-01T00:00:00",
            checkpoint_manager=self.cpm,
        )

        marker.refresh_from_db()
        self.assertEqual(marker.status, "committed")
        self.assertEqual(marker.row_count, 50)
        self.assertIsNotNone(marker.committed_at)

        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.last_seen_value, "2024-01-01T00:00:00")
        self.assertEqual(cp.last_committed_value, "2024-01-01T00:00:00")
        self.assertEqual(cp.last_value, "2024-01-01T00:00:00")
        self.assertEqual(cp.last_successful_batch_id, bid)
        self.assertEqual(cp.checkpoint_status, "clean")
        self.assertIsNone(cp.last_status_reason)

    def test_commit_with_none_value_does_not_clobber_legacy_last_value(self):
        # Pre-seed a legacy last_value so we can prove None is non-destructive.
        SyncCheckpoint.objects.create(
            job=self.job,
            schema_name="public",
            table_name="orders",
            last_value="seed",
        )
        bid = self.coord.make_batch_id(1)
        marker = self.coord.begin_batch(bid, expected_row_count=10)
        self.coord.commit_batch(
            marker,
            rows_written=10,
            last_seen=None,
            last_committed=None,
            checkpoint_manager=self.cpm,
        )

        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.last_value, "seed")
        self.assertEqual(cp.last_successful_batch_id, bid)
        self.assertEqual(cp.checkpoint_status, "clean")


class IdempotencyProbeTests(TestCase):
    def setUp(self):
        _, self.job, self.execution = _make_job_execution("ip")
        self.cpm = CheckpointManager(self.job)
        self.coord = BatchCoordinator(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            target_db_type="postgres",
        )

    def test_already_committed_batch_is_skipped(self):
        bid = self.coord.make_batch_id(1)
        marker = self.coord.begin_batch(bid, expected_row_count=5)
        self.coord.commit_batch(
            marker,
            rows_written=5,
            last_seen=10,
            last_committed=10,
            checkpoint_manager=self.cpm,
        )
        self.assertTrue(self.coord.is_already_processed(bid))
        recovered = self.coord.get_committed_marker(bid)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.row_count, 5)

    def test_double_commit_with_same_rows_is_idempotent(self):
        bid = self.coord.make_batch_id(1)
        marker = self.coord.begin_batch(bid, expected_row_count=5)
        self.coord.commit_batch(
            marker,
            rows_written=5,
            last_seen=10,
            last_committed=10,
            checkpoint_manager=self.cpm,
        )
        marker.refresh_from_db()
        # Re-calling commit_batch with the same row_count must not raise.
        self.coord.commit_batch(
            marker,
            rows_written=5,
            last_seen=10,
            last_committed=10,
            checkpoint_manager=self.cpm,
        )

    def test_double_commit_with_different_rows_raises_idempotency_violation(self):
        bid = self.coord.make_batch_id(1)
        marker = self.coord.begin_batch(bid, expected_row_count=5)
        self.coord.commit_batch(
            marker,
            rows_written=5,
            last_seen=10,
            last_committed=10,
            checkpoint_manager=self.cpm,
        )
        marker.refresh_from_db()
        with self.assertRaises(IdempotencyViolation):
            self.coord.commit_batch(
                marker,
                rows_written=99,
                last_seen=10,
                last_committed=10,
                checkpoint_manager=self.cpm,
            )

    def test_begin_on_committed_batch_raises_violation(self):
        bid = self.coord.make_batch_id(1)
        marker = self.coord.begin_batch(bid, expected_row_count=5)
        self.coord.commit_batch(
            marker,
            rows_written=5,
            last_seen=10,
            last_committed=10,
            checkpoint_manager=self.cpm,
        )
        with self.assertRaises(IdempotencyViolation):
            self.coord.begin_batch(bid, expected_row_count=5)


class CrashRecoveryTests(TestCase):
    def setUp(self):
        _, self.job, self.execution = _make_job_execution("crash")
        self.cpm = CheckpointManager(self.job)
        self.coord = BatchCoordinator(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            target_db_type="postgres",
        )

    def test_crash_between_target_write_and_marker_commit_is_safe_on_replay(self):
        # First attempt: begin succeeds, "target write" succeeds, but the
        # commit step fails midway. We simulate the crash by raising
        # before commit_batch is reached.
        bid = self.coord.make_batch_id(1)
        marker = self.coord.begin_batch(bid, expected_row_count=10)
        # marker is in 'started' state; checkpoint not advanced.
        self.coord.fail_batch(
            marker, error=RuntimeError("boom"), checkpoint_manager=self.cpm
        )
        marker.refresh_from_db()
        self.assertEqual(marker.status, "failed")
        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.checkpoint_status, "dirty")

        # Replay: begin_batch with the SAME batch_id reuses the row,
        # flips it back to 'started', and we can commit normally.
        replayed = self.coord.begin_batch(bid, expected_row_count=10)
        self.assertEqual(replayed.id, marker.id)
        self.assertEqual(replayed.status, "started")
        self.coord.commit_batch(
            replayed,
            rows_written=10,
            last_seen="11",
            last_committed="11",
            checkpoint_manager=self.cpm,
        )
        replayed.refresh_from_db()
        self.assertEqual(replayed.status, "committed")
        cp.refresh_from_db()
        self.assertEqual(cp.last_committed_value, "11")
        self.assertEqual(cp.checkpoint_status, "clean")

    def test_crash_between_marker_commit_and_checkpoint_update_is_atomic(self):
        # Force a failure inside set_seen; the whole atomic block must
        # roll back so the marker stays 'started' and no checkpoint
        # value lands.
        bid = self.coord.make_batch_id(1)
        marker = self.coord.begin_batch(bid, expected_row_count=7)

        original_set_seen = self.cpm.set_seen

        def raise_on_set_seen(*args, **kwargs):  # noqa: ANN001
            raise RuntimeError("simulated metadata failure")

        with patch.object(self.cpm, "set_seen", side_effect=raise_on_set_seen):
            with self.assertRaises(RuntimeError):
                self.coord.commit_batch(
                    marker,
                    rows_written=7,
                    last_seen="X",
                    last_committed="X",
                    checkpoint_manager=self.cpm,
                )

        marker.refresh_from_db()
        self.assertEqual(marker.status, "started")
        self.assertIsNone(marker.committed_at)
        # Checkpoint either does not exist or was never advanced.
        cp = SyncCheckpoint.objects.filter(
            job=self.job, schema_name="public", table_name="orders"
        ).first()
        if cp is not None:
            self.assertIsNone(cp.last_committed_value)
            self.assertIsNone(cp.last_successful_batch_id)

        # Sanity: a second attempt without the patch succeeds.
        # (Restoring set_seen happens automatically when the patch ctx exits.)
        self.coord.commit_batch(
            marker,
            rows_written=7,
            last_seen="X",
            last_committed="X",
            checkpoint_manager=self.cpm,
        )
        marker.refresh_from_db()
        self.assertEqual(marker.status, "committed")


class RecoverTableTests(TestCase):
    def setUp(self):
        _, self.job, self.execution = _make_job_execution("rec")
        self.cpm = CheckpointManager(self.job)

    def _seed_started(self, *, batch_id="b000001", schema="public", table="orders"):
        return ProcessedBatch.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name=schema,
            table_name=table,
            batch_id=batch_id,
            row_count=10,
            status="started",
        )

    def test_recover_table_marks_stale_started_as_failed_and_sets_recovering(self):
        marker = self._seed_started()

        result = recover_table(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            checkpoint_manager=self.cpm,
        )
        self.assertEqual(result["stale_started_count"], 1)
        self.assertTrue(result["recovering"])

        marker.refresh_from_db()
        self.assertEqual(marker.status, "failed")
        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.checkpoint_status, "recovering")
        self.assertIn("stale started batches", cp.last_status_reason)

    def test_recover_table_no_stale_rows_is_noop(self):
        result = recover_table(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            checkpoint_manager=self.cpm,
        )
        self.assertEqual(result["stale_started_count"], 0)
        self.assertFalse(result["recovering"])
        self.assertFalse(
            SyncCheckpoint.objects.filter(
                job=self.job, schema_name="public", table_name="orders"
            ).exists()
        )

    def test_recover_table_only_touches_started_status(self):
        # 'committed' and 'failed' must NOT be flipped.
        committed = ProcessedBatch.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            batch_id="b000001",
            row_count=5,
            status="committed",
        )
        failed = ProcessedBatch.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            batch_id="b000002",
            row_count=5,
            status="failed",
        )
        recover_table(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            checkpoint_manager=self.cpm,
        )
        committed.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual(committed.status, "committed")
        self.assertEqual(failed.status, "failed")


class DualPointerResumeTests(TestCase):
    """End-to-end style: 5 batches, kill after 3, resume cleanly."""

    def setUp(self):
        _, self.job, self.execution = _make_job_execution("resume")
        self.cpm = CheckpointManager(self.job)
        self.coord = BatchCoordinator(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            target_db_type="postgres",
        )

    def test_dual_pointer_resume_skips_already_committed_batches(self):
        # First attempt: commit batches 1-3, leave batch 4 in 'started'.
        for n in (1, 2, 3):
            bid = self.coord.make_batch_id(n)
            marker = self.coord.begin_batch(bid, expected_row_count=10)
            self.coord.commit_batch(
                marker,
                rows_written=10,
                last_seen=str(n * 100),
                last_committed=str(n * 100),
                checkpoint_manager=self.cpm,
            )
        # Crash in the middle of batch 4: 'started' marker, no commit.
        crashed = self.coord.begin_batch(
            self.coord.make_batch_id(4), expected_row_count=10
        )
        self.assertEqual(crashed.status, "started")

        # Resume:
        recover_table(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            checkpoint_manager=self.cpm,
        )
        crashed.refresh_from_db()
        self.assertEqual(crashed.status, "failed")

        # Walk batches 1..5 again. 1-3 must skip, 4 replays, 5 is fresh.
        write_count = 0
        for n in (1, 2, 3, 4, 5):
            bid = self.coord.make_batch_id(n)
            if self.coord.is_already_processed(bid):
                continue
            marker = self.coord.begin_batch(bid, expected_row_count=10)
            self.coord.commit_batch(
                marker,
                rows_written=10,
                last_seen=str(n * 100),
                last_committed=str(n * 100),
                checkpoint_manager=self.cpm,
            )
            write_count += 1

        self.assertEqual(write_count, 2)  # only batches 4 and 5
        committed = ProcessedBatch.objects.filter(
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            status="committed",
        )
        self.assertEqual(committed.count(), 5)

        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.last_committed_value, "500")
        self.assertEqual(cp.last_successful_batch_id, "b000005")
        self.assertEqual(cp.checkpoint_status, "clean")


class NonTransactionalTargetTests(TestCase):
    def setUp(self):
        _, self.job, self.execution = _make_job_execution("nontx")
        self.cpm = CheckpointManager(self.job)

    def test_clickhouse_target_runs_full_lifecycle_without_target_atomic(self):
        coord = BatchCoordinator(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            target_db_type="clickhouse",
        )
        bid = coord.make_batch_id(1)
        marker = coord.begin_batch(bid, expected_row_count=8)
        coord.commit_batch(
            marker,
            rows_written=8,
            last_seen="2024-01-02",
            last_committed="2024-01-02",
            checkpoint_manager=self.cpm,
        )
        marker.refresh_from_db()
        self.assertEqual(marker.status, "committed")
        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.last_committed_value, "2024-01-02")


class FullSyncResumeFlagTests(TestCase):
    """Full sync truncate-on-rerun must be skipped on in-flight resume."""

    def setUp(self):
        _, self.job, self.execution = _make_job_execution("fs", sync_type="full")

    def test_has_any_processed_batches_signals_resume(self):
        coord = BatchCoordinator(
            execution=self.execution,
            job=self.job,
            schema_name="public",
            table_name="orders",
            target_db_type="postgres",
        )
        self.assertFalse(coord.has_any_processed_batches())

        ProcessedBatch.objects.create(
            job=self.job,
            execution=self.execution,
            schema_name="public",
            table_name="orders",
            batch_id="b000001",
            row_count=10,
            status="started",
        )
        self.assertTrue(coord.has_any_processed_batches())


class CheckpointManagerExtensionsTests(TestCase):
    def setUp(self):
        _, self.job, _ = _make_job_execution("cpmgr")
        self.cpm = CheckpointManager(self.job)

    def test_set_seen_writes_only_seen_pointer(self):
        self.cpm.set_seen("public", "orders", "abc")
        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.last_seen_value, "abc")
        self.assertIsNone(cp.last_committed_value)
        self.assertIsNone(cp.last_value)

    def test_set_committed_writes_committed_and_legacy(self):
        self.cpm.set_committed("public", "orders", "abc", "b000001")
        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.last_committed_value, "abc")
        self.assertEqual(cp.last_value, "abc")
        self.assertEqual(cp.last_successful_batch_id, "b000001")

    def test_mark_dirty_recovering_clean_transitions(self):
        self.cpm.mark_dirty("public", "orders", reason="boom")
        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.checkpoint_status, "dirty")
        self.assertEqual(cp.last_status_reason, "boom")

        self.cpm.mark_recovering("public", "orders", reason="recover")
        cp.refresh_from_db()
        self.assertEqual(cp.checkpoint_status, "recovering")
        self.assertEqual(cp.last_status_reason, "recover")

        self.cpm.mark_clean("public", "orders")
        cp.refresh_from_db()
        self.assertEqual(cp.checkpoint_status, "clean")
        self.assertIsNone(cp.last_status_reason)

    def test_set_committed_with_none_value_preserves_last_value(self):
        SyncCheckpoint.objects.create(
            job=self.job,
            schema_name="public",
            table_name="orders",
            last_value="seed",
        )
        self.cpm.set_committed("public", "orders", value=None, batch_id="b000001")
        cp = SyncCheckpoint.objects.get(
            job=self.job, schema_name="public", table_name="orders"
        )
        self.assertEqual(cp.last_value, "seed")
        self.assertEqual(cp.last_successful_batch_id, "b000001")
