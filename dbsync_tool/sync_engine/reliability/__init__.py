"""Reliability primitives for the sync engine.

This package hosts retry policy, idempotent batch coordination, dead-letter
collection, and the typed exceptions that tie those subsystems together.

Day 1 introduced the typed exceptions and the data-layer surfaces. Day 2
added idempotent batch coordination (``BatchCoordinator``,
``recover_table``). Day 3 added the centralized per-table retry policy
(``RetryPolicy``, ``with_policy``, ``classify_error``) sitting one level
above the BatchCoordinator at the sync_table boundary. Day 4 adds
row-scope dead-letter capture with a per-table tolerance budget
(``DeadLetterCollector``, ``DeadLetterStats``,
``DEFAULT_DEAD_LETTER_MAX_PCT``).
"""

from .errors import (
    TransientSyncError,
    FatalSyncError,
    DeadLetterRowError,
    IdempotencyViolation,
)
from .idempotency import (
    BatchCoordinator,
    recover_table,
    increment_log_attempts,
)
from .retry_policy import (
    RetryPolicy,
    classify_error,
    with_policy,
    to_dead_letter,
    is_dead_letter,
    ERROR_CODES,
    CATEGORY_TRANSIENT,
    CATEGORY_FATAL,
    CATEGORY_DEAD_LETTER,
)
from .dead_letter import (
    DeadLetterCollector,
    DeadLetterStats,
    DEFAULT_DEAD_LETTER_MAX_PCT,
)

__all__ = [
    "TransientSyncError",
    "FatalSyncError",
    "DeadLetterRowError",
    "IdempotencyViolation",
    "BatchCoordinator",
    "recover_table",
    "increment_log_attempts",
    "RetryPolicy",
    "classify_error",
    "with_policy",
    "to_dead_letter",
    "is_dead_letter",
    "ERROR_CODES",
    "CATEGORY_TRANSIENT",
    "CATEGORY_FATAL",
    "CATEGORY_DEAD_LETTER",
    "DeadLetterCollector",
    "DeadLetterStats",
    "DEFAULT_DEAD_LETTER_MAX_PCT",
]
