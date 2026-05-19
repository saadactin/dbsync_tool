"""Typed exceptions for reliability and DQ surfaces.

These exceptions are introduced in Day 1 so that downstream modules
(retry policy, batch coordinator, dead-letter collector, DQ packs) can
import a stable set of types from day one. They are NOT yet raised from
runtime code today; that wiring lands in Days 2-4.

Hierarchy:

    SyncExecutionError (existing base)
    +-- TransientSyncError      # safe to retry
    +-- FatalSyncError          # never retry, escalate
    +-- DeadLetterRowError      # row-scoped, capture-and-continue
    +-- IdempotencyViolation    # same batch committed twice
"""

from sync_engine.exceptions import SyncExecutionError


class TransientSyncError(SyncExecutionError):
    """Retryable failure (timeout, deadlock, transient connection issue).

    Raised by Day-3 retry classification; the retry policy will replay the
    operation up to ``retry_policy.max_retries`` with backoff.
    """


class FatalSyncError(SyncExecutionError):
    """Non-retryable failure (schema mismatch, permission denied, auth).

    Day-3 retry policy escalates this immediately without sleep/backoff.
    """


class DeadLetterRowError(SyncExecutionError):
    """Per-row failure suitable for dead-letter capture rather than abort.

    Day-4 collector catches this, writes a ``SyncDeadLetterRow`` row, and
    lets the rest of the batch continue as long as the run stays under
    the configured dead-letter budget.
    """

    def __init__(self, message: str, *, row=None, error_code: str = "ROW_ERROR"):
        super().__init__(message)
        self.row = row
        self.error_code = error_code


class IdempotencyViolation(SyncExecutionError):
    """Same (execution, schema, table, batch_id) attempted to commit twice.

    Day-2 BatchCoordinator raises this when the unique constraint on
    ``ProcessedBatch`` rejects a duplicate commit attempt that the
    coordinator could not classify as a safe replay.
    """
