"""Day-6 reconciliation service.

Pure module: aggregates Day-5 ``ReconciliationReport`` rows + Day 1-4
``SyncExecutionLog`` columns into a single execution-scoped artifact and
provides JSON / CSV export bytes.

This module has **no** Django request, email, or logging side-effect.  The
view layer and email layer compose on top of these functions.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.conf import settings

from sync_jobs.models import (
    ReconciliationReport,
    SyncExecutionLog,
)

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1
DRIFT_DECISIONS = {"warning", "repair_full", "repair_incremental"}
DEFAULT_CONFIDENCE_FLOOR = 0.8


def _confidence_floor() -> float:
    raw = getattr(settings, "SLO_DRIFT_CONFIDENCE_FLOOR", DEFAULT_CONFIDENCE_FLOOR)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE_FLOOR


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


def _duration_seconds(execution) -> Optional[float]:
    started = getattr(execution, "started_at", None)
    completed = getattr(execution, "completed_at", None)
    if not started or not completed:
        return None
    try:
        return float((completed - started).total_seconds())
    except Exception:
        return None


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count_warnings(block: Dict[str, Any]) -> int:
    """Count entries flagged as 'warning' or with non-empty 'errors' list."""
    if not isinstance(block, dict):
        return 0
    warnings = block.get("warnings")
    if isinstance(warnings, list):
        return len(warnings)
    return 0


def _count_errors(block: Dict[str, Any]) -> int:
    if not isinstance(block, dict):
        return 0
    errors = block.get("errors")
    if isinstance(errors, list):
        return len(errors)
    return 0


def _empty_recon_table(schema: str, table: str) -> Dict[str, Any]:
    return {
        "schema_name": schema,
        "table_name": table,
        "decision": "unknown",
        "confidence": None,
        "attempts": 0,
        "last_error_code": None,
        "dead_letter_count": 0,
        "rows_fetched": 0,
        "rows_inserted": 0,
        "verification_summary": None,
        "dq_pre": {},
        "dq_post": {},
        "source_metrics": {},
        "target_metrics": {},
        "drift": {},
    }


def _table_from_recon(report: ReconciliationReport) -> Dict[str, Any]:
    return {
        "schema_name": report.schema_name,
        "table_name": report.table_name,
        "decision": report.decision or "unknown",
        "confidence": (
            float(report.confidence)
            if report.confidence is not None
            else None
        ),
        "attempts": 0,
        "last_error_code": None,
        "dead_letter_count": 0,
        "rows_fetched": 0,
        "rows_inserted": 0,
        "verification_summary": None,
        "dq_pre": _safe_dict(report.dq_pre_json),
        "dq_post": _safe_dict(report.dq_post_json),
        "source_metrics": _safe_dict(report.source_metrics_json),
        "target_metrics": _safe_dict(report.target_metrics_json),
        "drift": _safe_dict(report.drift_json),
    }


def _merge_log_into_table(table: Dict[str, Any], log: SyncExecutionLog) -> None:
    table["attempts"] = int(getattr(log, "attempts", 0) or 0)
    table["last_error_code"] = getattr(log, "last_error_code", None) or None
    table["dead_letter_count"] = int(getattr(log, "dead_letter_count", 0) or 0)
    table["rows_fetched"] = int(getattr(log, "rows_fetched", 0) or 0)
    table["rows_inserted"] = int(getattr(log, "rows_inserted", 0) or 0)
    table["verification_summary"] = getattr(log, "verification_summary", None) or None


def build_execution_report(execution) -> Dict[str, Any]:
    """Aggregate ``ReconciliationReport`` + ``SyncExecutionLog`` into one dict.

    Tolerates either side missing:
      - log without recon row -> ``decision='unknown'`` and empty DQ blocks
      - recon without log     -> log fields zeroed / nulled
    """
    job = getattr(execution, "job", None)
    job_id = str(getattr(job, "id", "")) if job else ""
    job_name = getattr(job, "name", "") if job else ""
    sync_type = getattr(job, "sync_type", "") if job else ""
    tenant_obj = getattr(job, "tenant", None) if job else None
    tenant_id = str(getattr(tenant_obj, "id", "")) if tenant_obj else None

    recon_qs = ReconciliationReport.objects.filter(execution=execution).order_by(
        "schema_name", "table_name"
    )
    log_qs = SyncExecutionLog.objects.filter(execution=execution).order_by(
        "schema_name", "table_name"
    )

    tables_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in recon_qs:
        key = (r.schema_name, r.table_name)
        tables_by_key[key] = _table_from_recon(r)

    for log in log_qs:
        key = (log.schema_name, log.table_name)
        if key not in tables_by_key:
            tables_by_key[key] = _empty_recon_table(log.schema_name, log.table_name)
        _merge_log_into_table(tables_by_key[key], log)

    tables: List[Dict[str, Any]] = [
        tables_by_key[k] for k in sorted(tables_by_key.keys())
    ]

    totals = {
        "tables": len(tables),
        "ok": 0,
        "warning": 0,
        "repair_full": 0,
        "repair_incremental": 0,
        "unknown": 0,
        "dead_letter_count": 0,
        "attempts_sum": 0,
    }
    for t in tables:
        decision = (t.get("decision") or "unknown").lower()
        if decision in totals:
            totals[decision] += 1
        else:
            totals["unknown"] += 1
        totals["dead_letter_count"] += int(t.get("dead_letter_count") or 0)
        totals["attempts_sum"] += int(t.get("attempts") or 0)

    return {
        "schema_version": SCHEMA_VERSION,
        "execution": {
            "id": str(getattr(execution, "id", "")),
            "job_id": job_id,
            "job_name": job_name,
            "sync_type": sync_type,
            "status": getattr(execution, "status", ""),
            "started_at": _iso(getattr(execution, "started_at", None)),
            "completed_at": _iso(getattr(execution, "completed_at", None)),
            "duration_seconds": _duration_seconds(execution),
            "tenant_id": tenant_id,
        },
        "totals": totals,
        "tables": tables,
    }


def export_json(execution) -> bytes:
    """Return UTF-8 JSON bytes of ``build_execution_report``."""
    report = build_execution_report(execution)
    return json.dumps(report, indent=2, default=str, sort_keys=False).encode("utf-8")


CSV_COLUMNS: Tuple[str, ...] = (
    "schema_name",
    "table_name",
    "decision",
    "confidence",
    "attempts",
    "last_error_code",
    "dead_letter_count",
    "rows_fetched",
    "rows_inserted",
    "source_count",
    "target_count",
    "sample_hash_match",
    "parity_decision",
    "dq_pre_warnings",
    "dq_post_warnings",
    "dq_post_errors",
    "verification_summary",
)


def _csv_row(table: Dict[str, Any]) -> Dict[str, Any]:
    parity = _safe_dict(_safe_dict(table.get("dq_post")).get("parity"))
    pre = _safe_dict(table.get("dq_pre"))
    post = _safe_dict(table.get("dq_post"))
    return {
        "schema_name": table.get("schema_name", ""),
        "table_name": table.get("table_name", ""),
        "decision": table.get("decision", ""),
        "confidence": "" if table.get("confidence") is None else table.get("confidence"),
        "attempts": table.get("attempts", 0),
        "last_error_code": table.get("last_error_code") or "",
        "dead_letter_count": table.get("dead_letter_count", 0),
        "rows_fetched": table.get("rows_fetched", 0),
        "rows_inserted": table.get("rows_inserted", 0),
        "source_count": parity.get("source_count", "") if parity else "",
        "target_count": parity.get("target_count", "") if parity else "",
        "sample_hash_match": parity.get("sample_hash_match", "") if parity else "",
        "parity_decision": parity.get("decision", "") if parity else "",
        "dq_pre_warnings": _count_warnings(pre),
        "dq_post_warnings": _count_warnings(post),
        "dq_post_errors": _count_errors(post),
        "verification_summary": table.get("verification_summary") or "",
    }


def export_csv(execution) -> bytes:
    """Return UTF-8 CSV bytes for the execution-scoped report."""
    report = build_execution_report(execution)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for table in report.get("tables", []):
        writer.writerow(_csv_row(table))
    return buf.getvalue().encode("utf-8")


def has_drift(report: Dict[str, Any]) -> bool:
    """True iff any table's decision is not OK or confidence is below floor."""
    if not isinstance(report, dict):
        return False
    floor = _confidence_floor()
    for table in report.get("tables") or []:
        decision = (table.get("decision") or "").lower()
        if decision in DRIFT_DECISIONS:
            return True
        confidence = table.get("confidence")
        if confidence is not None:
            try:
                if float(confidence) < floor:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def drift_tables(report: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Yield only tables that contributed to drift (helper for alert body)."""
    if not isinstance(report, dict):
        return []
    floor = _confidence_floor()
    out: List[Dict[str, Any]] = []
    for table in report.get("tables") or []:
        decision = (table.get("decision") or "").lower()
        confidence = table.get("confidence")
        below_floor = False
        if confidence is not None:
            try:
                below_floor = float(confidence) < floor
            except (TypeError, ValueError):
                below_floor = False
        if decision in DRIFT_DECISIONS or below_floor:
            out.append(table)
    return out


__all__ = [
    "SCHEMA_VERSION",
    "DRIFT_DECISIONS",
    "CSV_COLUMNS",
    "build_execution_report",
    "export_json",
    "export_csv",
    "has_drift",
    "drift_tables",
]
