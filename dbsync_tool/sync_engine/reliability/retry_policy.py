"""Per-table retry policy + transient/fatal error taxonomy.

Day 3 of the 7-day reliability + DQ plan. Composes on top of:

  * Day 1: ``SyncJobTable.retry_policy`` JSONField + canonical
    ``default_retry_policy()`` factory + ``SyncExecutionLog.attempts``
    and ``SyncExecutionLog.last_error_code`` columns.
  * Day 2: ``BatchCoordinator`` + ``recover_table()`` so that retrying
    the WHOLE ``sync_table`` call is replay-safe (already-committed
    batches skip, half-done batches are recovered).

Public surface:

  * ``RetryPolicy``: immutable per-table policy parsed from the
    JSONField with hostile-value clamping.
  * ``classify_error(exc) -> (category, code)``: transient / fatal /
    dead_letter taxonomy. Walks ``__cause__`` so wrapped exceptions
    (e.g. ``TableSyncError(...) from OperationalError("deadlock")``)
    classify against the inner driver exception.
  * ``with_policy(callable, policy, ...)``: runs the callable with
    bounded retries, exponential backoff with 0..25% jitter, and a
    ``max_total_seconds`` safety cap. Sleep + RNG are dependency-
    injected so tests assert timing without sleeping.

Composition with the inner ``@retry_on_error`` decorators
(``_upsert_batch_with_retry``, ``_fetch_batch_with_retry`` and
similar driver-call shims) is intentional: the inner decorators keep
covering tight retries on a single driver call, and the outer policy
treats the whole table as one logical attempt. A single transient
deadlock is therefore retried by the inner shim first; if it fails
all the way out, the outer policy may also retry the table once
more, giving us belt-and-braces safety without surprising operators.
"""

from __future__ import annotations

import logging
import random
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple, TypeVar

from sync_engine.reliability.errors import (
    DeadLetterRowError,
    FatalSyncError,
    IdempotencyViolation,
    TransientSyncError,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Error code taxonomy (also written to SyncExecutionLog.last_error_code)
# ----------------------------------------------------------------------

ERROR_CODES = frozenset(
    {
        "TIMEOUT",
        "CONN_RESET",
        "DEADLOCK",
        "LOCK_TIMEOUT",
        "SCHEMA_MISMATCH",
        "PERMISSION_DENIED",
        "TABLE_NOT_FOUND",
        "AUTH_FAILED",
        "BAD_QUERY",
        "ROW_ERROR",
        "IDEMPOTENCY_VIOLATION",
        "UNKNOWN",
    }
)

CATEGORY_TRANSIENT = "transient"
CATEGORY_FATAL = "fatal"
CATEGORY_DEAD_LETTER = "dead_letter"


# Hostile-value clamps: a single bad JSON cannot DOS the executor.
_MAX_RETRIES_CLAMP = (0, 10)
_DELAY_CLAMP = (0.0, 300.0)
_BACKOFF_CLAMP = (1.0, 10.0)


T = TypeVar("T")


# ----------------------------------------------------------------------
# RetryPolicy
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable per-table retry policy.

    Attributes
    ----------
    max_retries:
        Number of retries AFTER the initial attempt. ``max_retries=0``
        means a single attempt with no retries. Clamped to [0, 10].
    initial_delay:
        Base delay in seconds before the first retry (attempt 2).
        Clamped to [0, 300].
    backoff:
        Multiplier applied to the delay after each retry. Clamped to
        [1.0, 10.0]; values < 1.0 would shrink the delay over time.
    retryable_errors:
        List of human-readable categories the operator considers
        retryable. ``classify_error()`` is the source of truth for the
        decision; this list documents intent and lets a future Day-N
        feature narrow the set per table.
    max_total_seconds:
        Optional safety cap on cumulative sleep across all retries.
        ``None`` means unlimited (still bounded by ``max_retries``).
    """

    max_retries: int
    initial_delay: float
    backoff: float
    retryable_errors: Tuple[str, ...] = field(default=())
    max_total_seconds: Optional[float] = None

    @classmethod
    def default(cls) -> "RetryPolicy":
        """Return the canonical default - mirrors ``default_retry_policy()``."""
        from sync_jobs.models import default_retry_policy

        raw = default_retry_policy()
        return cls(
            max_retries=int(raw.get("max_retries", 3)),
            initial_delay=float(raw.get("initial_delay", 1.0)),
            backoff=float(raw.get("backoff", 2.0)),
            retryable_errors=tuple(raw.get("retryable_errors") or ()),
            max_total_seconds=None,
        )

    @classmethod
    def disabled(cls) -> "RetryPolicy":
        """Single attempt, no retries. Useful for tests or hard opt-out."""
        return cls(
            max_retries=0,
            initial_delay=0.0,
            backoff=1.0,
            retryable_errors=(),
            max_total_seconds=0.0,
        )

    @classmethod
    def from_job_table(cls, job_table: Any) -> "RetryPolicy":
        """Parse from ``SyncJobTable.retry_policy`` JSONField.

        Tolerant of:
          * missing keys (fills from defaults)
          * empty dict (Day-1 default for new rows)
          * Mock objects in legacy unit tests (returns default)
          * hostile values (clamped to safe ranges)
        """
        raw = getattr(job_table, "retry_policy", None)
        if not isinstance(raw, dict) or not raw:
            return cls.default()

        from sync_jobs.models import default_retry_policy

        defaults = default_retry_policy()

        def _num(key: str, default_value: float) -> float:
            v = raw.get(key, default_value)
            try:
                return float(v)
            except (TypeError, ValueError):
                return float(default_value)

        max_retries = int(_clamp(int(_num("max_retries", defaults["max_retries"])), *_MAX_RETRIES_CLAMP))
        initial_delay = _clamp(_num("initial_delay", defaults["initial_delay"]), *_DELAY_CLAMP)
        backoff = _clamp(_num("backoff", defaults["backoff"]), *_BACKOFF_CLAMP)

        retryable = raw.get("retryable_errors") or defaults.get("retryable_errors") or []
        if not isinstance(retryable, (list, tuple)):
            retryable = []
        retryable = tuple(str(x) for x in retryable if x)

        cap_raw = raw.get("max_total_seconds")
        try:
            max_total = float(cap_raw) if cap_raw is not None else None
        except (TypeError, ValueError):
            max_total = None
        if max_total is not None:
            max_total = max(0.0, max_total)

        return cls(
            max_retries=max_retries,
            initial_delay=initial_delay,
            backoff=backoff,
            retryable_errors=retryable,
            max_total_seconds=max_total,
        )

    def delay_for(self, retry_number: int) -> float:
        """Return the (non-jittered) base delay before retry ``retry_number`` (1-indexed)."""
        if retry_number < 1:
            return 0.0
        return self.initial_delay * (self.backoff ** (retry_number - 1))


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# ----------------------------------------------------------------------
# Error classification
# ----------------------------------------------------------------------


_DEADLOCK_PATTERNS = re.compile(
    r"(deadlock|could not serialize|serialization failure)",
    re.IGNORECASE,
)
_LOCK_TIMEOUT_PATTERNS = re.compile(
    r"(lock[_ ]?timeout|lock wait timeout exceeded|could not obtain lock)",
    re.IGNORECASE,
)
_TIMEOUT_PATTERNS = re.compile(
    r"(timeout|timed out)",
    re.IGNORECASE,
)
_CONN_RESET_PATTERNS = re.compile(
    r"(connection reset|connection refused|broken pipe|connection closed|server closed the connection|"
    r"connection aborted|network is unreachable|temporary failure in name resolution|"
    r"could not connect to server)",
    re.IGNORECASE,
)
_PERMISSION_PATTERNS = re.compile(
    r"(permission denied|access denied|insufficient privilege|not authorized)",
    re.IGNORECASE,
)
_TABLE_NOT_FOUND_PATTERNS = re.compile(
    r"(does not exist|no such table|cannot find the object|invalid object name|"
    r"unknown table|table or view does not exist)",
    re.IGNORECASE,
)
_AUTH_PATTERNS = re.compile(
    r"(authentication failed|password authentication failed|login failed|invalid credentials)",
    re.IGNORECASE,
)


def classify_error(exc: BaseException) -> Tuple[str, str]:
    """Classify ``exc`` into ``(category, error_code)``.

    Walks the ``__cause__`` chain so wrapped exceptions classify
    against the inner driver exception when available. The first
    non-default match wins (cause-first preference).

    Returns one of:
      * ``("transient", code)`` - retryable
      * ``("fatal", code)``     - not retryable, abort the table
      * ``("dead_letter", code)`` - per-row error, surfaced for Day-4
    """
    if exc is None:
        return CATEGORY_FATAL, "UNKNOWN"

    # Walk the cause chain (max depth 5 to avoid pathological loops).
    chain: list[BaseException] = []
    cur: Optional[BaseException] = exc
    seen: set[int] = set()
    depth = 0
    while cur is not None and id(cur) not in seen and depth < 5:
        chain.append(cur)
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
        depth += 1

    # Prefer the most specific (innermost) classification - the inner
    # driver exception is the most informative.
    for candidate in reversed(chain):
        cat, code = _classify_single(candidate)
        if not (cat == CATEGORY_FATAL and code == "UNKNOWN"):
            return cat, code

    # Fall back to the outer if everything in the chain was unknown.
    return _classify_single(chain[0]) if chain else (CATEGORY_FATAL, "UNKNOWN")


def _classify_single(exc: BaseException) -> Tuple[str, str]:
    # Typed reliability errors first (Day 1).
    if isinstance(exc, IdempotencyViolation):
        return CATEGORY_FATAL, "IDEMPOTENCY_VIOLATION"
    if isinstance(exc, TransientSyncError):
        return CATEGORY_TRANSIENT, _code_from_message(str(exc), default="UNKNOWN")
    if isinstance(exc, FatalSyncError):
        return CATEGORY_FATAL, _code_from_message(str(exc), default="UNKNOWN")
    if isinstance(exc, DeadLetterRowError):
        return CATEGORY_DEAD_LETTER, getattr(exc, "error_code", None) or "ROW_ERROR"

    # Day 4: producers may tag any exception with ``dead_letter=True`` (and
    # optionally ``error_code=...``) to opt into row-scope routing without
    # constructing a ``DeadLetterRowError`` wrapper. We do NOT promote
    # generic IntegrityError/DataError to dead_letter automatically; that
    # would silently change Day-3 fatal defaults for batch-level failures.
    if getattr(exc, "dead_letter", False):
        return (
            CATEGORY_DEAD_LETTER,
            getattr(exc, "error_code", None) or "ROW_ERROR",
        )

    # Network / OS-level transient signals.
    if isinstance(exc, ConnectionError):
        return CATEGORY_TRANSIENT, "CONN_RESET"
    if isinstance(exc, TimeoutError):
        return CATEGORY_TRANSIENT, "TIMEOUT"
    if isinstance(exc, socket.timeout):
        return CATEGORY_TRANSIENT, "TIMEOUT"

    # Permission errors are fatal.
    if isinstance(exc, PermissionError):
        return CATEGORY_FATAL, "PERMISSION_DENIED"

    # Driver / DB-API exceptions: identify by class name + message because
    # we do not want hard imports on psycopg2 / pyodbc / etc. at module
    # load time.
    cls_name = type(exc).__name__
    msg = str(exc) or ""

    # SQLSTATE / pgcode hints when present.
    pgcode = getattr(exc, "pgcode", None) or ""
    sqlstate = pgcode or ""
    if not sqlstate and exc.args and isinstance(exc.args[0], str):
        # Some drivers stuff SQLSTATE into args[0] like ('40P01', ...).
        if re.fullmatch(r"[0-9A-Z]{5}", exc.args[0]):
            sqlstate = exc.args[0]

    # Deadlock / serialization failure (PostgreSQL: 40P01, 40001).
    if sqlstate in ("40P01", "40001") or _DEADLOCK_PATTERNS.search(msg):
        return CATEGORY_TRANSIENT, "DEADLOCK"
    # Lock timeout (PostgreSQL: 55P03; MySQL: HY000 with "Lock wait timeout exceeded").
    if sqlstate == "55P03" or _LOCK_TIMEOUT_PATTERNS.search(msg):
        return CATEGORY_TRANSIENT, "LOCK_TIMEOUT"
    # Network-y transient signals in messages.
    if _CONN_RESET_PATTERNS.search(msg):
        return CATEGORY_TRANSIENT, "CONN_RESET"
    if _TIMEOUT_PATTERNS.search(msg):
        return CATEGORY_TRANSIENT, "TIMEOUT"
    # Auth / permission.
    if _AUTH_PATTERNS.search(msg):
        return CATEGORY_FATAL, "AUTH_FAILED"
    if _PERMISSION_PATTERNS.search(msg):
        return CATEGORY_FATAL, "PERMISSION_DENIED"
    # Schema / object missing.
    if _TABLE_NOT_FOUND_PATTERNS.search(msg):
        return CATEGORY_FATAL, "TABLE_NOT_FOUND"

    # DB-API class-name heuristics (no hard imports).
    if cls_name == "OperationalError":
        # Default OperationalError without a known sub-pattern: be
        # conservative and call it transient. This is the standard
        # advice in psycopg2/MySQLdb docs.
        return CATEGORY_TRANSIENT, "UNKNOWN"
    if cls_name in ("IntegrityError", "ProgrammingError", "DataError", "NotSupportedError"):
        return CATEGORY_FATAL, "BAD_QUERY"

    # Default: fatal/UNKNOWN. We only retry when we are confident.
    return CATEGORY_FATAL, "UNKNOWN"


def _code_from_message(msg: str, *, default: str) -> str:
    if not msg:
        return default
    if _DEADLOCK_PATTERNS.search(msg):
        return "DEADLOCK"
    if _LOCK_TIMEOUT_PATTERNS.search(msg):
        return "LOCK_TIMEOUT"
    if _TIMEOUT_PATTERNS.search(msg):
        return "TIMEOUT"
    if _CONN_RESET_PATTERNS.search(msg):
        return "CONN_RESET"
    if _AUTH_PATTERNS.search(msg):
        return "AUTH_FAILED"
    if _PERMISSION_PATTERNS.search(msg):
        return "PERMISSION_DENIED"
    if _TABLE_NOT_FOUND_PATTERNS.search(msg):
        return "TABLE_NOT_FOUND"
    return default


# ----------------------------------------------------------------------
# Policy executor
# ----------------------------------------------------------------------


def with_policy(
    func: Callable[[], T],
    policy: RetryPolicy,
    *,
    classify: Callable[[BaseException], Tuple[str, str]] = classify_error,
    on_attempt: Optional[Callable[[int, Optional[str]], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: Optional[random.Random] = None,
) -> T:
    """Run ``func()`` with bounded retries on transient errors.

    Parameters
    ----------
    func:
        Zero-argument callable to invoke. Wrap your real call in a
        ``lambda`` so you can pass arguments + capture self.
    policy:
        ``RetryPolicy`` describing the retry budget + backoff curve.
    classify:
        Override the classifier (tests inject a stub; production uses
        the module-level :func:`classify_error`).
    on_attempt:
        Optional callback invoked at the START of each attempt, before
        ``func()`` runs. Signature ``(attempt_number, last_error_code)``
        where ``attempt_number`` is 1-indexed and ``last_error_code`` is
        ``None`` on attempt 1 and the prior attempt's error code on
        retries. Used by the wire-in to bump
        ``SyncExecutionLog.attempts`` and record the most recent code.
    sleep:
        Dependency-injected sleep function (default ``time.sleep``).
    rng:
        Dependency-injected ``random.Random`` for jitter. Defaults to
        ``random.SystemRandom()`` (cryptographically strong, no global
        state).

    Returns
    -------
    Whatever ``func()`` returns on the first successful attempt.

    Raises
    ------
    The last exception raised by ``func()`` when the retry budget is
    exhausted, when classification yields ``fatal`` /
    ``dead_letter``, or when the cumulative-sleep cap is reached.
    """
    rng_obj = rng if rng is not None else random.SystemRandom()
    total_attempts = max(1, policy.max_retries + 1)
    last_code: Optional[str] = None
    cumulative_sleep = 0.0

    for attempt_num in range(1, total_attempts + 1):
        if on_attempt is not None:
            try:
                on_attempt(attempt_num, last_code)
            except Exception:  # pragma: no cover - defensive
                logger.exception("with_policy: on_attempt callback failed; continuing")

        try:
            return func()
        except BaseException as exc:
            category, code = classify(exc)
            last_code = code

            # Fatal / dead_letter / IdempotencyViolation: never retry.
            if category != CATEGORY_TRANSIENT:
                logger.info(
                    "with_policy: %s error (code=%s) - aborting after %d attempt(s).",
                    category,
                    code,
                    attempt_num,
                )
                raise

            # Out of retry budget?
            if attempt_num >= total_attempts:
                logger.warning(
                    "with_policy: transient error (code=%s) exhausted retry budget "
                    "(%d attempts).",
                    code,
                    total_attempts,
                )
                raise

            # Compute backoff with jitter.
            base_delay = policy.delay_for(attempt_num)  # before retry attempt+1
            jitter = 1.0 + (rng_obj.random() * 0.25)
            sleep_seconds = base_delay * jitter

            # Cumulative-sleep safety cap.
            if policy.max_total_seconds is not None:
                remaining = policy.max_total_seconds - cumulative_sleep
                if remaining <= 0:
                    logger.warning(
                        "with_policy: cumulative-sleep cap reached (code=%s). "
                        "Stopping after %d attempt(s).",
                        code,
                        attempt_num,
                    )
                    raise
                if sleep_seconds > remaining:
                    sleep_seconds = remaining

            logger.info(
                "with_policy: transient error (code=%s) - retrying attempt %d in "
                "%.2fs (jitter=%.3fx).",
                code,
                attempt_num + 1,
                sleep_seconds,
                jitter,
            )
            if sleep_seconds > 0:
                sleep(sleep_seconds)
                cumulative_sleep += sleep_seconds

    # Unreachable under normal control flow.
    raise RuntimeError("with_policy exited without returning or raising")  # pragma: no cover


# ----------------------------------------------------------------------
# Day-4 helpers
# ----------------------------------------------------------------------


def to_dead_letter(
    exc: BaseException,
    *,
    row: Any = None,
    error_code: Optional[str] = None,
) -> DeadLetterRowError:
    """Convert ``exc`` into a :class:`DeadLetterRowError` for row-scope routing.

    Use this at producer call sites (per-row upsert, parser, transform
    validator) when you have row context and want the failure to flow
    through the Day-4 dead-letter path instead of failing the whole
    batch. The original exception is preserved as ``__cause__``.

    Idempotent: passing an existing ``DeadLetterRowError`` returns it
    unchanged (with ``row``/``error_code`` filled in if missing).
    """
    if isinstance(exc, DeadLetterRowError):
        if row is not None and getattr(exc, "row", None) is None:
            exc.row = row
        if error_code and not getattr(exc, "error_code", None):
            exc.error_code = error_code
        return exc

    if not error_code:
        try:
            _, code = classify_error(exc)
        except Exception:
            code = "ROW_ERROR"
        # Promote infrastructure/UNKNOWN to ROW_ERROR for row-scope context.
        if not code or code == "UNKNOWN":
            code = "ROW_ERROR"
        error_code = code

    wrapped = DeadLetterRowError(str(exc) or type(exc).__name__, row=row, error_code=error_code)
    wrapped.__cause__ = exc
    return wrapped


def is_dead_letter(exc: BaseException) -> bool:
    """Return ``True`` if ``exc`` will be classified as ``dead_letter``.

    Convenience for executor wire-in points that want to short-circuit
    on row-scope errors without constructing the full classification
    tuple twice.
    """
    if isinstance(exc, DeadLetterRowError) or getattr(exc, "dead_letter", False):
        return True
    try:
        cat, _ = classify_error(exc)
    except Exception:
        return False
    return cat == CATEGORY_DEAD_LETTER
