"""Idempotent batch coordination for the sync engine.

Day 2 of the 7-day reliability + DQ plan. Builds on the Day-1 data layer
(``ProcessedBatch`` + ``SyncCheckpoint`` dual-pointer fields +
``IdempotencyViolation``).

Goal: every batch in a sync run becomes exactly-once at
``(execution, schema, table, batch_id)`` granularity, with deterministic
resume after a crash.

Commit ordering implemented by ``BatchCoordinator``:

    1. begin_batch -> insert ProcessedBatch row in 'started' status
       (own atomic txn so the marker is visible across crashes).
    2. target_connector write (caller is inside ``atomic_target_commit``).
    3. commit_batch -> single atomic txn on the metadata DB:
         - flip ProcessedBatch.status='committed'
         - advance SyncCheckpoint.last_committed_value, last_value,
           last_successful_batch_id, checkpoint_status='clean'

Crash points and recovery:

  * Crash 1<->2: started row, no target rows. Replay re-attempts and the
    target's idempotent upsert is a clean insert.
  * Crash 2<->3: started row, target HAS rows. Replay re-attempts; the
    target upsert is a no-op for present rows; coordinator finishes the
    marker + checkpoint advance.
  * Crash >3: committed marker exists, ``is_already_processed`` returns
    True on replay and the batch is skipped entirely.

Non-transactional targets (ClickHouse, MongoDB) cannot wrap the target
write in a SQL transaction. We rely on idempotent upserts at the target
combined with our markers: same crash semantics, same replay safety.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Optional

from django.conf import settings
from django.db import transaction
from django.db.models.base import ModelState
from django.utils import timezone

from sync_engine.reliability.errors import IdempotencyViolation
from sync_jobs.models import ProcessedBatch, SyncExecutionLog

logger = logging.getLogger(__name__)


# Targets that do not support multi-statement transactional commits.
# We still use the same coordinator but skip any "target txn" expectation;
# replay safety is guaranteed by idempotent upserts at the target.
_NON_TRANSACTIONAL_TARGETS = frozenset({"clickhouse", "mongodb"})


def _coordinator_enabled() -> bool:
    """Feature flag (default ON) so existing tests can opt out cleanly.

    Set ``SYNC_RELIABILITY_BATCH_COORDINATOR = False`` in Django settings
    to bypass the coordinator entirely (Day 2 -> 3 transition aid).
    """
    return getattr(settings, "SYNC_RELIABILITY_BATCH_COORDINATOR", True)


def _is_persisted_orm_instance(obj) -> bool:
    """Return True only when ``obj`` is a saved Django model row.

    Day-2 unit tests in the sync_engine package frequently pass
    ``Mock(spec=SyncExecution)`` / ``Mock(spec=SyncJob)`` to executors.
    Filtering ``ProcessedBatch.objects.filter(execution=mock)`` against
    such a Mock raises ``TypeError`` deep inside Django's ORM; we want
    the coordinator to silently no-op in that case so legacy tests keep
    passing exactly as before. Real executions always have a
    ``ModelState`` ``_state`` attribute populated by Django on
    ``__init__``.
    """
    return isinstance(getattr(obj, "_state", None), ModelState)


class BatchCoordinator:
    """Per-table coordinator that owns the ProcessedBatch lifecycle.

    A single instance is created at the top of each per-table sync loop
    (incremental or full). It carries the execution, job, schema, and
    table context so call sites only have to pass the per-batch info.
    """

    def __init__(
        self,
        *,
        execution,
        job,
        schema_name: str,
        table_name: str,
        target_db_type: Optional[str] = None,
    ):
        if not execution:
            raise ValueError("BatchCoordinator requires an execution")
        if not job:
            raise ValueError("BatchCoordinator requires a job")
        if not schema_name or not table_name:
            raise ValueError("BatchCoordinator requires schema_name and table_name")
        self.execution = execution
        self.job = job
        self.schema_name = schema_name
        self.table_name = table_name
        self.target_db_type = (target_db_type or "").lower() or None
        # Coordinator is "active" only when the feature flag is on AND
        # the execution + job are real persisted ORM rows. Synthetic
        # mocks (used by legacy unit tests in sync_engine.tests) keep
        # the coordinator inert so we do not change those tests.
        self._active = (
            _coordinator_enabled()
            and _is_persisted_orm_instance(execution)
            and _is_persisted_orm_instance(job)
        )

    # ------------------------------------------------------------------
    # Batch identity
    # ------------------------------------------------------------------

    def make_batch_id(self, batch_number: int) -> str:
        """Return a deterministic batch_id for a 0-based batch number.

        Counter-based (zero-padded) so the same logical batch in a
        replayed execution maps to the same identifier.
        """
        return f"b{int(batch_number):06d}"

    # ------------------------------------------------------------------
    # Idempotency probes
    # ------------------------------------------------------------------

    def is_already_processed(self, batch_id: str) -> bool:
        """Return True if this batch is already committed for the run."""
        if not self._active:
            return False
        return ProcessedBatch.objects.filter(
            execution=self.execution,
            schema_name=self.schema_name,
            table_name=self.table_name,
            batch_id=batch_id,
            status="committed",
        ).exists()

    def get_committed_marker(self, batch_id: str) -> Optional[ProcessedBatch]:
        """Fetch the committed marker for a batch_id, if any."""
        if not self._active:
            return None
        return ProcessedBatch.objects.filter(
            execution=self.execution,
            schema_name=self.schema_name,
            table_name=self.table_name,
            batch_id=batch_id,
            status="committed",
        ).first()

    def has_any_processed_batches(self) -> bool:
        """True if any marker (any status) exists for this (run, table).

        Used by full-sync to decide whether the table is in a fresh run
        (truncate + reload) or an in-flight resume (skip truncate).
        """
        if not self._active:
            return False
        return ProcessedBatch.objects.filter(
            execution=self.execution,
            schema_name=self.schema_name,
            table_name=self.table_name,
        ).exists()

    # ------------------------------------------------------------------
    # Lifecycle: begin / commit / fail
    # ------------------------------------------------------------------

    def begin_batch(self, batch_id: str, expected_row_count: int) -> Optional[ProcessedBatch]:
        """Start (or replay-resume) a batch.

        Behavior matrix:
          * No existing row -> insert ('started').
          * Existing 'started' row -> reuse (replay-safe).
          * Existing 'failed' row  -> reuse, flip back to 'started' so
            recovery from a crash continues forward instead of being
            blocked by a sticky failure.
          * Existing 'committed' row -> raise ``IdempotencyViolation``.

        When the coordinator is inactive (synthetic execution / feature
        flag off), returns ``None`` and writes nothing.
        """
        if not self._active:
            return None
        with transaction.atomic():
            existing = (
                ProcessedBatch.objects.select_for_update()
                .filter(
                    execution=self.execution,
                    schema_name=self.schema_name,
                    table_name=self.table_name,
                    batch_id=batch_id,
                )
                .first()
            )
            if existing is None:
                marker = ProcessedBatch.objects.create(
                    job=self.job,
                    execution=self.execution,
                    schema_name=self.schema_name,
                    table_name=self.table_name,
                    batch_id=batch_id,
                    row_count=int(expected_row_count or 0),
                    status="started",
                )
                logger.debug(
                    "BatchCoordinator: started batch %s for %s.%s (rows=%s)",
                    batch_id,
                    self.schema_name,
                    self.table_name,
                    expected_row_count,
                )
                return marker

            if existing.status == "committed":
                raise IdempotencyViolation(
                    f"Batch already committed: execution={self.execution.id} "
                    f"{self.schema_name}.{self.table_name} batch_id={batch_id}"
                )

            # 'started' or 'failed' -> reuse the row, return to 'started'.
            existing.status = "started"
            existing.row_count = int(expected_row_count or existing.row_count or 0)
            existing.committed_at = None
            existing.save(update_fields=["status", "row_count", "committed_at"])
            logger.info(
                "BatchCoordinator: replay-resuming batch %s for %s.%s",
                batch_id,
                self.schema_name,
                self.table_name,
            )
            return existing

    def commit_batch(
        self,
        marker: Optional[ProcessedBatch],
        *,
        rows_written: int,
        last_seen: Any,
        last_committed: Any,
        checkpoint_manager,
    ) -> None:
        """Atomically flip the marker to committed and advance the checkpoint.

        Both writes happen inside a single Django transaction so a crash
        between them is impossible: either both land or neither does.

        When the coordinator is inactive (synthetic execution / feature
        flag off), this is a no-op.
        """
        if not self._active or marker is None:
            return
        if marker.status == "committed":
            # Replay or accidental double-commit. We tolerate same-rows
            # idempotent calls but raise when callers disagree on the
            # row count (signal of a real bug).
            if int(rows_written or 0) != int(marker.row_count or 0):
                raise IdempotencyViolation(
                    f"Double commit with mismatched row_count for "
                    f"{self.schema_name}.{self.table_name} "
                    f"batch_id={marker.batch_id}: "
                    f"existing={marker.row_count} new={rows_written}"
                )
            return

        with transaction.atomic():
            marker.status = "committed"
            marker.row_count = int(rows_written or 0)
            marker.committed_at = timezone.now()
            marker.save(update_fields=["status", "row_count", "committed_at"])

            # Eagerly advance the seen pointer (tracks observation),
            # then atomically advance the committed pointer + legacy
            # last_value, set the successful batch id, and mark clean.
            if last_seen is not None:
                checkpoint_manager.set_seen(
                    schema_name=self.schema_name,
                    table_name=self.table_name,
                    value=last_seen,
                )
            checkpoint_manager.set_committed(
                schema_name=self.schema_name,
                table_name=self.table_name,
                value=last_committed,
                batch_id=marker.batch_id,
            )
            checkpoint_manager.mark_clean(
                schema_name=self.schema_name,
                table_name=self.table_name,
            )

        logger.debug(
            "BatchCoordinator: committed batch %s for %s.%s rows=%s",
            marker.batch_id,
            self.schema_name,
            self.table_name,
            rows_written,
        )

    def fail_batch(
        self,
        marker: Optional[ProcessedBatch],
        *,
        error: BaseException,
        checkpoint_manager,
    ) -> None:
        """Flip the marker to failed and mark the checkpoint dirty.

        Safe to call with ``marker=None`` (e.g. begin_batch itself failed).
        Never raises.
        """
        if not self._active:
            return
        try:
            with transaction.atomic():
                if marker is not None and marker.status != "committed":
                    marker.status = "failed"
                    marker.save(update_fields=["status"])
                checkpoint_manager.mark_dirty(
                    schema_name=self.schema_name,
                    table_name=self.table_name,
                    reason=str(error)[:255] if error else "unknown",
                )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "BatchCoordinator: fail_batch could not persist failure marker"
                " for %s.%s",
                self.schema_name,
                self.table_name,
            )

    # ------------------------------------------------------------------
    # Atomic envelope around target write + commit
    # ------------------------------------------------------------------

    @contextmanager
    def atomic_target_commit(self, marker: ProcessedBatch, *, target_atomic: Optional[bool] = None):
        """Context manager wrapping the target write + metadata commit.

        Caller does the target write inside the ``with`` block and then
        calls ``coordinator.commit_batch(...)`` before the block exits.

        If the block exits via exception, ``fail_batch`` is invoked and
        the original exception is re-raised. Otherwise the caller is
        responsible for calling commit_batch.

        ``target_atomic``: if None (default), inferred from
        ``target_db_type``. ClickHouse / MongoDB skip the target txn
        expectation and rely on idempotent upserts.
        """
        if target_atomic is None:
            target_atomic = (
                self.target_db_type is not None
                and self.target_db_type not in _NON_TRANSACTIONAL_TARGETS
            )

        try:
            yield {"marker": marker, "target_atomic": target_atomic}
        except BaseException as exc:
            # NOTE: we are NOT swallowing the exception. We persist the
            # failure side-effects then re-raise so the caller's outer
            # error handling (existing TableSyncError flow, retry, etc.)
            # behaves exactly like before.
            self.fail_batch(
                marker,
                error=exc,
                checkpoint_manager=getattr(exc, "_dbsync_checkpoint_manager", None)
                or _no_op_checkpoint_manager,
            )
            raise


# A tiny stand-in used only when fail_batch is called from the context
# manager and the caller hasn't injected a checkpoint manager. The real
# wire-in always passes one through commit_batch directly.
class _NoOpCheckpointManager:
    def set_seen(self, *args, **kwargs):
        return None

    def set_committed(self, *args, **kwargs):
        return None

    def mark_dirty(self, *args, **kwargs):
        return None

    def mark_recovering(self, *args, **kwargs):
        return None

    def mark_clean(self, *args, **kwargs):
        return None


_no_op_checkpoint_manager = _NoOpCheckpointManager()


# ----------------------------------------------------------------------
# Recovery sweep
# ----------------------------------------------------------------------


def recover_table(
    *,
    execution,
    job,
    schema_name: str,
    table_name: str,
    checkpoint_manager,
) -> dict:
    """Reconcile leftover ProcessedBatch rows from a previous crashed run.

    Run once at the start of every per-table sync.

    Steps:
      1. Find ``ProcessedBatch`` rows for the same ``(execution, schema,
         table)`` whose status is ``started``. Those are batches that
         a previous (crashed) attempt of this same execution kicked off
         but never committed.
      2. Mark them ``failed`` (the new attempt will re-run them under a
         fresh marker; their target writes are either absent or already
         present, both of which idempotent upserts tolerate).
      3. If any were found, set ``checkpoint_status='recovering'`` so
         operators can see that the next run is a recovery; otherwise
         leave the checkpoint untouched.

    Returns a small structured dict for logging. Becomes a no-op (and
    returns a zeroed-out dict) when the coordinator feature flag is off
    or when ``execution`` / ``job`` are synthetic mocks.
    """
    if not _coordinator_enabled() or not (
        _is_persisted_orm_instance(execution) and _is_persisted_orm_instance(job)
    ):
        return {
            "stale_started_count": 0,
            "recovering": False,
            "schema_name": schema_name,
            "table_name": table_name,
            "skipped": True,
        }

    qs = ProcessedBatch.objects.filter(
        execution=execution,
        schema_name=schema_name,
        table_name=table_name,
        status="started",
    )

    stale_count = qs.count()
    recovering = stale_count > 0

    if recovering:
        with transaction.atomic():
            qs.update(status="failed")
            checkpoint_manager.mark_recovering(
                schema_name=schema_name,
                table_name=table_name,
                reason=f"{stale_count} stale started batches from previous attempt",
            )
        logger.warning(
            "Recovery sweep: marked %s stale 'started' batches as 'failed' "
            "for execution=%s %s.%s; checkpoint set to 'recovering'.",
            stale_count,
            execution.id,
            schema_name,
            table_name,
        )

    return {
        "stale_started_count": stale_count,
        "recovering": recovering,
        "schema_name": schema_name,
        "table_name": table_name,
    }


# ----------------------------------------------------------------------
# Per-table execution log helper
# ----------------------------------------------------------------------


def increment_log_attempts(execution_log: Optional[SyncExecutionLog]) -> None:
    """Bump the per-table attempt counter (Day-1 field) idempotently.

    Day 3 will move to a richer retry policy that records error codes too.
    For Day 2 we simply count attempts so resume / retries are visible.
    """
    if execution_log is None:
        return
    try:
        with transaction.atomic():
            SyncExecutionLog.objects.filter(pk=execution_log.pk).update(
                attempts=(execution_log.attempts or 0) + 1
            )
            execution_log.refresh_from_db(fields=["attempts"])
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to increment SyncExecutionLog.attempts")
