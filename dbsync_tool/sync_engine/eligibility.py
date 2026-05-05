"""Eligibility classifier for incremental vs full sync per table.

Decides whether a SyncJobTable can safely run incremental sync, or must fall back
to full sync for correctness. Used to make watermark-based SQL Server -> Postgres
sync provably correct without CDC.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from connections.connectors.base import ColumnInfo

DATETIME_TYPES = (
    "timestamp",
    "datetime",
    "datetime2",
    "datetimeoffset",
    "smalldatetime",
    "timestamptz",
)
ROWVERSION_TYPES = ("rowversion", "timestamp")
NUMERIC_INCREMENTAL_TYPES = (
    "int",
    "integer",
    "bigint",
    "smallint",
    "serial",
    "bigserial",
    "numeric",
    "decimal",
)


@dataclass
class EligibilityDecision:
    """Result of evaluating a table for incremental sync."""

    mode: str  # "incremental" or "full"
    reasons: List[str] = field(default_factory=list)
    chosen_incremental_column: Optional[str] = None
    upsert_keys: List[str] = field(default_factory=list)

    def summary(self) -> str:
        reasons_text = "; ".join(self.reasons) if self.reasons else "no_reasons"
        col = self.chosen_incremental_column or "none"
        keys = ",".join(self.upsert_keys) if self.upsert_keys else "none"
        return f"mode={self.mode}; incremental_column={col}; keys={keys}; reasons={reasons_text}"


class IncrementalEligibility:
    """Classifies a table as 'incremental' or 'full' based on schema-driven rules."""

    @staticmethod
    def _is_datetime_only_date(col_type: str) -> bool:
        ct = (col_type or "").lower()
        return ("date" in ct) and ("datetime" not in ct) and ("timestamp" not in ct)

    @staticmethod
    def _is_datetime_like(col_type: str) -> bool:
        ct = (col_type or "").lower()
        return any(token in ct for token in DATETIME_TYPES) or "timestamp" in ct

    @staticmethod
    def _is_rowversion(col_type: str) -> bool:
        ct = (col_type or "").lower()
        return any(token in ct for token in ROWVERSION_TYPES) and "datetime" not in ct

    @staticmethod
    def _is_numeric_incremental(col_type: str) -> bool:
        ct = (col_type or "").lower()
        return any(token in ct for token in NUMERIC_INCREMENTAL_TYPES)

    @staticmethod
    def _pick_incremental_column(
        configured: Optional[str],
        columns: Sequence[ColumnInfo],
        pk_columns: Sequence[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Return (column_name, reason) selecting the strongest available watermark."""
        cols_by_lower = {c.name.lower(): c for c in columns}

        if configured:
            col = cols_by_lower.get(configured.strip().lower())
            if col is None:
                return None, f"configured_column_missing:{configured}"
            if IncrementalEligibility._is_datetime_only_date(col.data_type):
                return None, f"configured_column_is_date_only:{configured}"
            return col.name, "configured"

        for col in columns:
            if IncrementalEligibility._is_rowversion(col.data_type):
                return col.name, "auto_rowversion"

        preferred_names = ("updated_at", "modified_at", "modified_date", "last_modified")
        for pname in preferred_names:
            col = cols_by_lower.get(pname)
            if col and IncrementalEligibility._is_datetime_like(col.data_type) \
                    and not IncrementalEligibility._is_datetime_only_date(col.data_type):
                return col.name, f"auto_named:{pname}"

        for col in columns:
            if IncrementalEligibility._is_datetime_like(col.data_type) \
                    and not IncrementalEligibility._is_datetime_only_date(col.data_type):
                return col.name, "auto_first_datetime"

        pk_lower = {(p or "").strip().lower() for p in pk_columns or []}
        for col in columns:
            if col.name.lower() in pk_lower and IncrementalEligibility._is_numeric_incremental(col.data_type):
                return col.name, "auto_numeric_pk"

        return None, "no_safe_incremental_column"

    @staticmethod
    def evaluate(
        *,
        configured_incremental_column: Optional[str],
        configured_key_columns: Optional[Sequence[str]],
        columns: Sequence[ColumnInfo],
        pk_columns: Sequence[str],
        assume_incremental_monotonic: bool = True,
    ) -> EligibilityDecision:
        """Evaluate a job table for incremental sync eligibility.

        Required for incremental:
        - Has unique upsert key (PK or configured non-empty), all keys present in columns.
        - Has a usable monotonic incremental column (rowversion / datetime / numeric PK).
        - Incremental column is not a date-only type.
        """
        decision = EligibilityDecision(mode="full")
        if not columns:
            decision.reasons.append("no_source_columns")
            return decision

        column_names_lower = {c.name.lower() for c in columns}

        upsert_keys: List[str] = []
        if pk_columns:
            upsert_keys = [p for p in pk_columns if (p or "").strip().lower() in column_names_lower]
            if upsert_keys:
                decision.reasons.append("upsert_key_source:primary_key")

        if not upsert_keys and configured_key_columns:
            upsert_keys = [
                k for k in configured_key_columns
                if k and k.strip().lower() in column_names_lower
            ]
            if upsert_keys:
                decision.reasons.append("upsert_key_source:configured")

        if not upsert_keys:
            decision.reasons.append("no_upsert_key_available")
            return decision

        col_name, reason = IncrementalEligibility._pick_incremental_column(
            configured=configured_incremental_column,
            columns=columns,
            pk_columns=pk_columns,
        )
        if not col_name:
            decision.reasons.append(reason or "incremental_column_unavailable")
            return decision

        # If we can't assume monotonic updates (watermark correctness), only allow
        # increments for rowversion-like columns (provably monotonic for updates).
        if not assume_incremental_monotonic:
            chosen_col = None
            col_name_lower = (col_name or "").strip().lower()
            for c in columns:
                if (c.name or "").strip().lower() == col_name_lower:
                    chosen_col = c
                    break
            if chosen_col is not None and not IncrementalEligibility._is_rowversion(chosen_col.data_type):
                decision.reasons.append(
                    f"monotonic_unknown_disallow_non_rowversion:{chosen_col.data_type}"
                )
                return decision

        decision.mode = "incremental"
        decision.chosen_incremental_column = col_name
        decision.upsert_keys = upsert_keys
        decision.reasons.append(f"incremental_column:{reason}")
        return decision
