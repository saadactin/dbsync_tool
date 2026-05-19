"""Dead-letter row capture with per-table tolerance budget (Day 4).

Sits next to :mod:`sync_engine.reliability.idempotency` (Day 2) and
:mod:`sync_engine.reliability.retry_policy` (Day 3). The collector is
the single place that:

  * counts how many rows the per-table run has *seen*
  * captures rows that fail at row-scope (parse / constraint / single-row
    upsert) into ``SyncDeadLetterRow``
  * enforces the per-table ``dead_letter_max_pct`` budget
  * exposes a clean ``should_fail()`` predicate so executors can raise
    the appropriate ``FatalSyncError`` and let Day-2's
    ``BatchCoordinator.fail_batch`` + Day-3's retry policy deal with the
    fallout
  * redacts sensitive payload keys + caps oversized rows / messages
  * is safe to instantiate inside legacy unit tests (Mock job /
    job_table) without touching the database

Day 4 deliberately does not try to *cause* row-level errors itself; it
provides the recording surface. Producers (parsers, batch upsert
helpers, transform validators) raise ``DeadLetterRowError`` (Day 1) and
the executor wires those into ``record(...)``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from django.db import transaction
from django.utils import timezone

from sync_engine.reliability.errors import DeadLetterRowError
from sync_engine.reliability.retry_policy import classify_error
from sync_jobs.models import (
    SyncDeadLetterRow,
    SyncExecutionLog,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants - kept module-level so tests can reach them, not magic.
# ----------------------------------------------------------------------

DEFAULT_DEAD_LETTER_MAX_PCT = 0.001  # 0.1% - matches SyncJobTable default

#: Fields whose values are always replaced with "***REDACTED***" before
#: persistence. Lowercased substring match: ``"my_password_x"`` is
#: redacted because it contains ``"password"``.
_SENSITIVE_KEY_HINTS: tuple = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "authorization",
    "auth_header",
    "session",
    "cookie",
    "ssn",
    "credit_card",
    "card_number",
    "cvv",
)

_REDACTED_PLACEHOLDER = "***REDACTED***"

#: Hard caps; protects metadata DB from gigantic raw_row_json /
#: error_message values that some connectors love to emit.
_DEFAULT_MAX_ROW_CHARS = 16_000
_DEFAULT_MAX_ERROR_MSG_LEN = 2_000


# ----------------------------------------------------------------------
# Stats dataclass
# ----------------------------------------------------------------------


@dataclass
class DeadLetterStats:
    """Lightweight counters surface used by tests + status reporting."""

    rows_seen: int = 0
    dead_letter_count: int = 0
    last_error_code: Optional[str] = None
    failed_due_to_budget: bool = False
    bad_pk_examples: List[str] = field(default_factory=list)

    @property
    def dead_letter_pct(self) -> float:
        if self.rows_seen <= 0:
            return 0.0
        return self.dead_letter_count / float(self.rows_seen)


# ----------------------------------------------------------------------
# Collector
# ----------------------------------------------------------------------


class DeadLetterCollector:
    """Per-table dead-letter capture + threshold enforcement.

    One instance per ``(execution, job_table)``. Reusable across the
    batch loop: callers ``mark_seen`` before evaluating each row, then
    ``record(...)`` when the row fails at row-scope. ``flush()`` drains
    the in-memory buffer to the metadata DB; the executor must call it
    at least once per batch and once at the end of the table.

    The collector is also active when ``execution`` or ``job_table``
    are non-persisted Mock instances (legacy unit tests). In that mode
    it counts and runs the budget logic but skips DB writes, so old
    test fixtures continue to pass.
    """

    def __init__(
        self,
        *,
        execution,
        job,
        job_table,
        batch_id: Optional[str] = None,
        max_pct: Optional[float] = None,
        max_error_message_len: int = _DEFAULT_MAX_ERROR_MSG_LEN,
        max_row_chars: int = _DEFAULT_MAX_ROW_CHARS,
        flush_chunk_size: int = 200,
    ) -> None:
        self.execution = execution
        self.job = job
        self.job_table = job_table

        self.schema_name = getattr(job_table, "schema_name", None) or ""
        self.table_name = getattr(job_table, "table_name", None) or ""
        self.batch_id = batch_id

        self.max_error_message_len = int(max_error_message_len)
        self.max_row_chars = int(max_row_chars)
        self.flush_chunk_size = max(1, int(flush_chunk_size))

        self.max_pct = self._resolve_max_pct(max_pct)
        self._key_columns = self._discover_key_columns()

        self.stats = DeadLetterStats()
        self._buffer: List[SyncDeadLetterRow] = []
        self._active = self._is_persisted_orm_instance(execution) and self._is_persisted_orm_instance(job)

        if not self._active:
            logger.debug(
                "DeadLetterCollector running in no-DB mode (execution or job is not a "
                "persisted ORM instance); budget evaluation still active."
            )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def mark_seen(self, n: int = 1) -> None:
        """Increment the ``rows_seen`` counter.

        Always call this before invoking row-level work. It feeds the
        threshold computation; a collector that never ``mark_seen`` will
        always evaluate budget against ``max(rows_seen, 1) == 1``,
        which would fail-fast on the first bad row.
        """
        if n <= 0:
            return
        self.stats.rows_seen += int(n)

    def record(
        self,
        *,
        row: Optional[Mapping[str, Any]],
        error: BaseException,
        batch_number: Optional[int] = None,
        batch_id: Optional[str] = None,
    ) -> None:
        """Record a row-level failure into the buffer.

        ``row`` may be ``None`` when the producer cannot recover row
        context (e.g. a stream-level parse failure). In that case the
        record still bumps the dead-letter counter and persists a stub
        with ``raw_row_json`` set to ``None``.

        ``error`` is run through Day-3 ``classify_error`` to obtain a
        stable ``error_code`` string. ``DeadLetterRowError.error_code``
        wins when present.
        """
        self.stats.dead_letter_count += 1

        error_code = self._error_code(error)
        self.stats.last_error_code = error_code

        msg = (str(error) or type(error).__name__)[: self.max_error_message_len]

        sanitized_row = self._sanitize_row(row)
        source_pk = self._extract_source_pk(row)
        source_hash = self._row_hash(sanitized_row)

        if source_pk and len(self.stats.bad_pk_examples) < 10:
            self.stats.bad_pk_examples.append(source_pk)

        if not self._active:
            return  # no-op DB layer in mock mode

        marker = SyncDeadLetterRow(
            execution=self.execution,
            job=self.job,
            schema_name=self.schema_name,
            table_name=self.table_name,
            batch_id=batch_id or self.batch_id,
            source_pk_text=(source_pk or "")[:512] or None,
            source_row_hash=(source_hash or "")[:128] or None,
            raw_row_json=sanitized_row,
            error_code=error_code,
            error_message=msg,
        )
        self._buffer.append(marker)

        if len(self._buffer) >= self.flush_chunk_size:
            self.flush()

    def should_fail(self) -> bool:
        """Return ``True`` once the dead-letter ratio strictly exceeds budget.

        Strict inequality means an exact budget hit (e.g. ``1/1000`` at
        ``max_pct=0.001``) is allowed. Any further bad row tips the
        scale and returns ``True``.
        """
        if self.stats.dead_letter_count <= 0:
            return False
        denom = max(self.stats.rows_seen, 1)
        ratio = self.stats.dead_letter_count / float(denom)
        breached = ratio > float(self.max_pct or 0.0)
        if breached:
            self.stats.failed_due_to_budget = True
        return breached

    def failure_reason(self) -> str:
        """Operator-friendly failure reason string."""
        return (
            f"Dead-letter budget exceeded: {self.stats.dead_letter_count} bad "
            f"row(s) of {self.stats.rows_seen} seen "
            f"({self.stats.dead_letter_pct:.4%} > {float(self.max_pct or 0.0):.4%})."
        )

    def flush(self) -> None:
        """Persist any buffered ``SyncDeadLetterRow`` instances."""
        if not self._buffer or not self._active:
            self._buffer.clear()
            return
        try:
            with transaction.atomic():
                SyncDeadLetterRow.objects.bulk_create(
                    self._buffer,
                    batch_size=self.flush_chunk_size,
                )
        except Exception:
            logger.exception(
                "DeadLetterCollector: bulk_create failed for %s.%s; falling back "
                "to per-row create so budget tracking stays consistent.",
                self.schema_name,
                self.table_name,
            )
            for row in self._buffer:
                try:
                    row.created_at = timezone.now()
                    row.save()
                except Exception:
                    logger.exception(
                        "DeadLetterCollector: failed to persist dead-letter row for %s.%s",
                        self.schema_name,
                        self.table_name,
                    )
        finally:
            self._buffer.clear()

    def update_log_counters(self) -> None:
        """Bump ``SyncExecutionLog.dead_letter_count`` for this table.

        Called once per batch boundary (or at terminal close). Safe to
        call multiple times - it always writes the absolute count.
        """
        if not self._active:
            return
        try:
            SyncExecutionLog.objects.filter(
                execution=self.execution,
                schema_name=self.schema_name,
                table_name=self.table_name,
            ).update(dead_letter_count=self.stats.dead_letter_count)
        except Exception:
            logger.exception(
                "DeadLetterCollector: failed to update SyncExecutionLog.dead_letter_count "
                "for %s.%s",
                self.schema_name,
                self.table_name,
            )

    def raise_if_budget_exceeded(self) -> None:
        """Raise a :class:`DeadLetterRowError`-derived budget breach.

        Day-3 ``classify_error`` already maps ``DeadLetterRowError`` to
        ``("dead_letter", "ROW_ERROR")``, so the wrapping
        :func:`with_policy` will treat the breach as a non-retryable
        terminal outcome. The executor catches the exception, marks the
        active batch as ``failed`` via ``BatchCoordinator.fail_batch``,
        and surfaces the budget reason as ``last_error_code=ROW_ERROR``.
        """
        if not self.should_fail():
            return
        self.flush()
        self.update_log_counters()
        raise DeadLetterRowError(
            self.failure_reason(),
            error_code="ROW_ERROR",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_persisted_orm_instance(obj: Any) -> bool:
        """Cheap filter for Mock-vs-real-Django-instance detection.

        Mock objects (used heavily in legacy tests) are not Django model
        instances. ``hasattr`` won't disambiguate because Mocks return
        Mocks for every attribute. We rely on ``_meta`` + concrete type
        checks instead.
        """
        if obj is None:
            return False
        try:
            from django.db.models import Model

            if not isinstance(obj, Model):
                return False
            return getattr(obj, "pk", None) is not None
        except Exception:
            return False

    def _resolve_max_pct(self, override: Optional[float]) -> float:
        if override is not None:
            try:
                return max(0.0, float(override))
            except (TypeError, ValueError):
                pass
        raw = getattr(self.job_table, "dead_letter_max_pct", None)
        if raw is None:
            return DEFAULT_DEAD_LETTER_MAX_PCT
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_DEAD_LETTER_MAX_PCT
        return max(0.0, value)

    def _discover_key_columns(self) -> List[str]:
        """Best-effort PK column discovery for source_pk_text extraction."""
        cols: List[str] = []
        raw = getattr(self.job_table, "incremental_key_columns", None)
        if isinstance(raw, (list, tuple)):
            cols.extend(str(c) for c in raw if c)
        single = getattr(self.job_table, "incremental_column", None)
        if single and single not in cols:
            cols.append(str(single))
        protected = getattr(self.job_table, "protected_columns", None)
        if isinstance(protected, (list, tuple)):
            for c in protected:
                if c and str(c) not in cols:
                    cols.append(str(c))
        # Common id-like fallbacks for sources without explicit keys.
        for fallback in ("id", "_id", "uuid", "pk"):
            if fallback not in cols:
                cols.append(fallback)
        return cols

    def _extract_source_pk(self, row: Optional[Mapping[str, Any]]) -> Optional[str]:
        if not row:
            return None
        for key in self._key_columns:
            if key in row and row[key] not in (None, ""):
                try:
                    return str(row[key])
                except Exception:
                    return None
            lower = key.lower()
            for k, v in row.items():
                if isinstance(k, str) and k.lower() == lower and v not in (None, ""):
                    try:
                        return str(v)
                    except Exception:
                        return None
        return None

    def _sanitize_row(self, row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        try:
            sanitized = {
                str(k): self._scrub_value(k, v)
                for k, v in self._iter_items(row)
            }
            # Round-trip through json so any non-JSON-native values
            # (datetime, Decimal, custom objects) are coerced via our
            # fallback. This is critical because Django's JSONField
            # encoder runs without our fallback when persisting, and
            # would otherwise raise ``TypeError`` and abort the row.
            serialized = json.dumps(sanitized, default=_json_fallback, sort_keys=True)
            sanitized = json.loads(serialized)
        except Exception:
            return {"__raw_repr__": _safe_truncate(repr(row), self.max_row_chars)}

        if len(serialized) > self.max_row_chars:
            return {
                "__truncated__": True,
                "__row_chars__": len(serialized),
                "__row_excerpt__": serialized[: self.max_row_chars],
            }
        return sanitized

    @staticmethod
    def _iter_items(row: Mapping[str, Any]) -> Iterable:
        items = getattr(row, "items", None)
        if callable(items):
            return items()
        return list(row)

    @staticmethod
    def _scrub_value(key: Any, value: Any) -> Any:
        try:
            key_lower = str(key).lower()
        except Exception:
            return value
        if any(hint in key_lower for hint in _SENSITIVE_KEY_HINTS):
            return _REDACTED_PLACEHOLDER
        return value

    @staticmethod
    def _row_hash(sanitized_row: Optional[Dict[str, Any]]) -> Optional[str]:
        if not sanitized_row:
            return None
        try:
            payload = json.dumps(sanitized_row, default=_json_fallback, sort_keys=True)
        except Exception:
            return None
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _error_code(error: BaseException) -> str:
        if isinstance(error, DeadLetterRowError):
            return getattr(error, "error_code", None) or "ROW_ERROR"
        try:
            _, code = classify_error(error)
            return code or "ROW_ERROR"
        except Exception:
            return "ROW_ERROR"


# ----------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------


def _json_fallback(obj: Any) -> Any:
    """``json.dumps`` ``default`` for common non-JSON-native types."""
    try:
        from datetime import date, datetime, time
        from decimal import Decimal
        from uuid import UUID
    except Exception:  # pragma: no cover - defensive
        return repr(obj)

    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return f"<bytes len={len(obj)}>"
    return repr(obj)


def _safe_truncate(text: str, limit: int) -> str:
    if not isinstance(text, str):
        text = repr(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 13)] + "...[truncated]"
