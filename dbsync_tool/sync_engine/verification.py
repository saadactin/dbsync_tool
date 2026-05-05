"""Post-run parity verification utilities for SQL Server -> Postgres sync.

The verifier compares source vs target row counts (and optionally an order-invariant
hash digest) after a table finishes syncing, then writes a SyncVerificationReport
row capturing the decision (ok / repair_full / repair_incremental / warning).

Designed to be safe for any source/target combination: when either connector does
not expose the helpers (count_rows / aggregate_hash / aggregate_checksum_agg),
the verifier degrades to count-only or returns a warning instead of failing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

from sync_jobs.models import (
    SyncExecution,
    SyncJob,
    SyncVerificationReport,
)

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    decision: str
    source_count: int
    target_count: int
    sample_hash_match: Optional[bool]
    details: str

    @property
    def is_ok(self) -> bool:
        return self.decision == "ok"


def _safe_count_rows(connector, schema: str, table: str, where: Optional[str]) -> Optional[int]:
    fn = getattr(connector, "count_rows", None)
    if not callable(fn):
        return None
    try:
        return int(fn(schema, table, where))
    except Exception as e:
        logger.warning("count_rows failed on %s.%s: %s", schema, table, e)
        return None


def _safe_source_hash(connector, schema: str, table: str, columns: Iterable[str]) -> Optional[str]:
    """Source-side digest (SQL Server CHECKSUM_AGG -> hex string for comparability)."""
    cols = list(columns)
    fn = getattr(connector, "aggregate_checksum_agg", None)
    if callable(fn):
        try:
            return f"checksum_agg:{int(fn(schema, table, cols))}"
        except Exception as e:
            logger.warning("aggregate_checksum_agg failed on %s.%s: %s", schema, table, e)
    fn2 = getattr(connector, "aggregate_hash", None)
    if callable(fn2):
        try:
            return f"md5:{fn2(schema, table, cols)}"
        except Exception as e:
            logger.warning("aggregate_hash failed on %s.%s: %s", schema, table, e)
    return None


def _safe_target_hash(connector, schema: str, table: str, columns: Iterable[str]) -> Optional[str]:
    cols = list(columns)
    fn = getattr(connector, "aggregate_hash", None)
    if callable(fn):
        try:
            return f"md5:{fn(schema, table, cols)}"
        except Exception as e:
            logger.warning("aggregate_hash failed on %s.%s: %s", schema, table, e)
    fn2 = getattr(connector, "aggregate_checksum_agg", None)
    if callable(fn2):
        try:
            return f"checksum_agg:{int(fn2(schema, table, cols))}"
        except Exception as e:
            logger.warning("aggregate_checksum_agg failed on %s.%s: %s", schema, table, e)
    return None


def verify_table_parity(
    *,
    job: SyncJob,
    execution: Optional[SyncExecution],
    source_connector,
    target_connector,
    source_schema: str,
    source_table: str,
    target_schema: str,
    target_table: str,
    sync_mode: str,
    source_where: Optional[str] = None,
    target_where: Optional[str] = None,
    hash_columns: Optional[List[str]] = None,
    source_hash_columns: Optional[List[str]] = None,
    target_hash_columns: Optional[List[str]] = None,
    no_delete_propagation: bool = True,
) -> VerificationResult:
    """Run a parity check and persist a SyncVerificationReport row.

    Decision rules:
    - mode=full:        ok iff source_count == target_count (and hash matches if computed).
    - mode=incremental: ok iff target_count >= source_count (deletes not propagated).
    - any helper unavailable -> decision='warning' with details.
    """
    source_count = _safe_count_rows(source_connector, source_schema, source_table, source_where)
    target_count = _safe_count_rows(target_connector, target_schema, target_table, target_where)

    sample_hash_match: Optional[bool] = None
    hash_detail = ""
    src_cols = source_hash_columns or hash_columns
    tgt_cols = target_hash_columns or hash_columns
    if src_cols and tgt_cols:
        src_hash = _safe_source_hash(source_connector, source_schema, source_table, src_cols)
        tgt_hash = _safe_target_hash(target_connector, target_schema, target_table, tgt_cols)
        if src_hash is not None and tgt_hash is not None:
            sample_hash_match = src_hash == tgt_hash
            hash_detail = f"; src_hash={src_hash}; tgt_hash={tgt_hash}"

    if source_count is None or target_count is None:
        decision = "warning"
        details = (
            f"counts unavailable (source={source_count}, target={target_count})"
            f"{hash_detail}"
        )
    else:
        if sync_mode == "full":
            if source_count == target_count and (sample_hash_match is None or sample_hash_match):
                decision = "ok"
            else:
                decision = "repair_full"
        else:
            if no_delete_propagation:
                drifted = target_count < source_count
            else:
                drifted = target_count != source_count
            if drifted or sample_hash_match is False:
                decision = "repair_full"
            else:
                decision = "ok"
        details = (
            f"source_count={source_count}; target_count={target_count}; "
            f"sample_hash_match={sample_hash_match}; "
            f"no_delete_propagation={no_delete_propagation}"
            f"{hash_detail}"
        )

    try:
        SyncVerificationReport.objects.create(
            job=job,
            execution=execution,
            schema_name=source_schema,
            table_name=source_table,
            sync_mode=sync_mode,
            source_count=int(source_count or 0),
            target_count=int(target_count or 0),
            sample_hash_match=sample_hash_match,
            decision=decision,
            details=details[:5000],
        )
    except Exception as e:
        logger.warning(
            "Failed to persist SyncVerificationReport for %s.%s: %s",
            source_schema,
            source_table,
            e,
        )

    return VerificationResult(
        decision=decision,
        source_count=int(source_count or 0),
        target_count=int(target_count or 0),
        sample_hash_match=sample_hash_match,
        details=details,
    )
