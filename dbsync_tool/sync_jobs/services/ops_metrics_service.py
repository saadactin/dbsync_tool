"""Day-7 ops metrics service.

Pure aggregation module that derives rolling reliability + DQ rollups and
per-execution SLO status from the existing models.  No new DB schema is
introduced - this only reads ``SyncJob``, ``SyncExecution``,
``SyncExecutionLog`` and ``ReconciliationReport``.

The module has no Django request, email, or logging side-effect.  The view
layer composes ``compute_health_rollup`` / ``compute_job_health`` for the
ops health dashboard, and the executor close hook composes
``detect_slo_breach`` to drive the Day-7 SLO breach email.
"""

from __future__ import annotations

import logging
import statistics
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from accounts.services.tenant_service import TenantService
from sync_jobs.models import (
    ReconciliationReport,
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
)

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1

# SLO defaults.  Day-7 introduces these centrally.  ``settings.py`` ships the
# same defaults so an ops engineer only has to set the env-var to override.
DEFAULT_SLO_OK_RATE = 0.99
DEFAULT_SLO_DEAD_LETTER_PCT_MAX = 0.001
DEFAULT_SLO_RETRY_ATTEMPT_P95 = 1
DEFAULT_SLO_DRIFT_CONFIDENCE_FLOOR = 0.8
DEFAULT_SLO_BREACH_STREAK_N = 3

# Cap how many executions per job we walk back to keep the breach detector
# fast on jobs with thousands of historical runs.
_MAX_STREAK_LOOKBACK = 50

DRIFT_DECISIONS = {"warning", "repair_full", "repair_incremental"}
TERMINAL_STATUSES = ("completed", "failed")


def _setting(name: str, default: Any) -> Any:
    raw = getattr(settings, name, default)
    if raw is None:
        return default
    return raw


def _setting_float(name: str, default: float) -> float:
    raw = _setting(name, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _setting_int(name: str, default: int) -> int:
    raw = _setting(name, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def slo_targets() -> Dict[str, Any]:
    """Return the live SLO target values for the four tracked metrics."""
    return {
        "ok_rate": _setting_float("SLO_RECONCILIATION_OK_RATE", DEFAULT_SLO_OK_RATE),
        "dead_letter_pct": _setting_float(
            "SLO_DEAD_LETTER_PCT_MAX", DEFAULT_SLO_DEAD_LETTER_PCT_MAX
        ),
        "attempts_p95": _setting_int(
            "SLO_RETRY_ATTEMPT_P95", DEFAULT_SLO_RETRY_ATTEMPT_P95
        ),
        "confidence_floor": _setting_float(
            "SLO_DRIFT_CONFIDENCE_FLOOR", DEFAULT_SLO_DRIFT_CONFIDENCE_FLOOR
        ),
        "breach_streak_n": max(
            1, _setting_int("SLO_BREACH_STREAK_N", DEFAULT_SLO_BREACH_STREAK_N)
        ),
    }


def _ratio(numer: float, denom: float, *, default: float = 1.0) -> float:
    if denom <= 0:
        return default
    try:
        return float(numer) / float(denom)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def _percentile(values: List[int], pct: float) -> float:
    """Robust percentile that degrades to ``max`` on tiny samples."""
    if not values:
        return 0.0
    if len(values) < 5:
        return float(max(values))
    try:
        cuts = statistics.quantiles(values, n=100, method="inclusive")
        idx = max(0, min(98, int(round(pct * 100)) - 1))
        return float(cuts[idx])
    except statistics.StatisticsError:
        return float(max(values))


def _user_jobs_qs(user):
    """Tenant-scoped ``SyncJob`` queryset for ``user``.  May be empty."""
    return TenantService.get_queryset_for_user(SyncJob.objects.all(), user)


def _aggregate_decision_counts(reports) -> Dict[str, int]:
    counts: Dict[str, int] = {
        "ok": 0,
        "warning": 0,
        "repair_full": 0,
        "repair_incremental": 0,
        "unknown": 0,
    }
    for r in reports:
        decision = (r.decision or "unknown").lower()
        if decision in counts:
            counts[decision] += 1
        else:
            counts["unknown"] += 1
    return counts


def _execution_ok(execution_id: str, reports_by_exec: Dict[str, List[Any]]) -> bool:
    """An execution is OK when every per-table decision is 'ok'."""
    rows = reports_by_exec.get(execution_id) or []
    if not rows:
        return False
    return all((r.decision or "unknown").lower() == "ok" for r in rows)


def _build_slo_block(
    *,
    ok_rate: float,
    dead_letter_pct: float,
    attempts_p95: float,
    confidence_floor_seen: Optional[float],
    targets: Dict[str, Any],
) -> Dict[str, Any]:
    confidence_target = float(targets["confidence_floor"])
    confidence_value = (
        float(confidence_floor_seen)
        if confidence_floor_seen is not None
        else float("nan")
    )
    confidence_ok = (
        True
        if confidence_floor_seen is None
        else confidence_value >= confidence_target
    )
    return {
        "ok_rate": {
            "value": float(ok_rate),
            "target": float(targets["ok_rate"]),
            "ok": ok_rate >= float(targets["ok_rate"]),
        },
        "dead_letter_pct": {
            "value": float(dead_letter_pct),
            "target": float(targets["dead_letter_pct"]),
            "ok": dead_letter_pct <= float(targets["dead_letter_pct"]),
        },
        "attempts_p95": {
            "value": float(attempts_p95),
            "target": float(targets["attempts_p95"]),
            "ok": attempts_p95 <= float(targets["attempts_p95"]),
        },
        "confidence_floor": {
            "value": confidence_value,
            "target": confidence_target,
            "ok": confidence_ok,
        },
    }


def _empty_rollup(window_hours: int) -> Dict[str, Any]:
    targets = slo_targets()
    return {
        "schema_version": SCHEMA_VERSION,
        "window": {"hours": int(window_hours), "since": None},
        "totals": {
            "executions": 0,
            "ok": 0,
            "warning": 0,
            "repair_full": 0,
            "repair_incremental": 0,
            "ok_rate": 1.0,
            "tables": 0,
            "dead_letter_rows": 0,
            "dead_letter_pct": 0.0,
            "attempts_p95": 0.0,
            "drift_incidents": 0,
        },
        "by_decision": {
            "ok": 0,
            "warning": 0,
            "repair_full": 0,
            "repair_incremental": 0,
            "unknown": 0,
        },
        "slo": _build_slo_block(
            ok_rate=1.0,
            dead_letter_pct=0.0,
            attempts_p95=0.0,
            confidence_floor_seen=None,
            targets=targets,
        ),
    }


def compute_health_rollup(user, *, window_hours: int) -> Dict[str, Any]:
    """Tenant-scoped rolling-window health dictionary.

    Always returns a stable shape even on DB error or empty data.  This is
    the data source for ops health cards on the dashboard.
    """
    window_hours = int(window_hours)
    if window_hours <= 0:
        window_hours = 24
    targets = slo_targets()
    since = timezone.now() - timedelta(hours=window_hours)

    try:
        user_jobs = _user_jobs_qs(user)
        executions = list(
            SyncExecution.objects.filter(
                job__in=user_jobs,
                started_at__gte=since,
                status__in=TERMINAL_STATUSES,
            ).only("id", "status", "started_at", "completed_at")[:5000]
        )
    except Exception:
        logger.exception(
            "compute_health_rollup: failed to load executions for user=%s",
            getattr(user, "id", None),
        )
        return _empty_rollup(window_hours)

    if not executions:
        rollup = _empty_rollup(window_hours)
        rollup["window"]["since"] = since.isoformat()
        return rollup

    execution_ids = [e.id for e in executions]

    try:
        reports = list(
            ReconciliationReport.objects.filter(execution_id__in=execution_ids).only(
                "execution_id", "decision", "confidence",
            )
        )
    except Exception:
        logger.exception(
            "compute_health_rollup: failed to load reconciliation reports for user=%s",
            getattr(user, "id", None),
        )
        reports = []

    try:
        log_agg = SyncExecutionLog.objects.filter(
            execution_id__in=execution_ids
        ).aggregate(
            dead_letter_rows=Sum("dead_letter_count"),
            rows_fetched=Sum("rows_fetched"),
        )
    except Exception:
        log_agg = {"dead_letter_rows": 0, "rows_fetched": 0}

    dead_letter_rows = int(log_agg.get("dead_letter_rows") or 0)
    rows_fetched = int(log_agg.get("rows_fetched") or 0)

    try:
        attempts_values = list(
            SyncExecutionLog.objects.filter(
                execution_id__in=execution_ids
            ).values_list("attempts", flat=True)[:10000]
        )
    except Exception:
        attempts_values = []

    reports_by_exec: Dict[str, List[Any]] = {}
    for r in reports:
        reports_by_exec.setdefault(str(r.execution_id), []).append(r)

    by_decision = _aggregate_decision_counts(reports)

    ok_executions = sum(
        1 for e in executions if _execution_ok(str(e.id), reports_by_exec)
    )
    total_executions = len(executions)

    confidence_values = [
        float(r.confidence)
        for r in reports
        if r.confidence is not None
    ]
    min_confidence = min(confidence_values) if confidence_values else None

    drift_incidents = sum(
        1
        for execution in executions
        if any(
            (r.decision or "").lower() in DRIFT_DECISIONS
            for r in reports_by_exec.get(str(execution.id)) or []
        )
    )

    ok_rate = _ratio(ok_executions, total_executions, default=1.0)
    dead_letter_pct = _ratio(dead_letter_rows, rows_fetched, default=0.0)
    attempts_p95 = _percentile([int(v or 0) for v in attempts_values], 0.95)

    return {
        "schema_version": SCHEMA_VERSION,
        "window": {"hours": window_hours, "since": since.isoformat()},
        "totals": {
            "executions": total_executions,
            "ok": ok_executions,
            "warning": by_decision.get("warning", 0),
            "repair_full": by_decision.get("repair_full", 0),
            "repair_incremental": by_decision.get("repair_incremental", 0),
            "ok_rate": ok_rate,
            "tables": len(reports),
            "dead_letter_rows": dead_letter_rows,
            "dead_letter_pct": dead_letter_pct,
            "attempts_p95": attempts_p95,
            "drift_incidents": drift_incidents,
        },
        "by_decision": by_decision,
        "slo": _build_slo_block(
            ok_rate=ok_rate,
            dead_letter_pct=dead_letter_pct,
            attempts_p95=attempts_p95,
            confidence_floor_seen=min_confidence,
            targets=targets,
        ),
    }


def compute_job_health(user, *, window_hours: int) -> List[Dict[str, Any]]:
    """Per-job summary rows for the ops health dashboard.

    Ordered by the most recent execution first so the operator sees their
    freshly-completed jobs at the top.
    """
    window_hours = int(window_hours)
    if window_hours <= 0:
        window_hours = 24
    since = timezone.now() - timedelta(hours=window_hours)

    try:
        user_jobs = list(
            _user_jobs_qs(user).only("id", "name", "sync_type", "status")
        )
    except Exception:
        logger.exception(
            "compute_job_health: failed to list jobs for user=%s",
            getattr(user, "id", None),
        )
        return []

    if not user_jobs:
        return []

    job_ids = [j.id for j in user_jobs]
    try:
        executions = list(
            SyncExecution.objects.filter(
                job_id__in=job_ids,
                started_at__gte=since,
                status__in=TERMINAL_STATUSES,
            )
            .only("id", "job_id", "status", "started_at", "completed_at")
            .order_by("-started_at")[:5000]
        )
    except Exception:
        logger.exception(
            "compute_job_health: failed to list executions for user=%s",
            getattr(user, "id", None),
        )
        executions = []

    execution_ids = [e.id for e in executions]
    try:
        reports = list(
            ReconciliationReport.objects.filter(execution_id__in=execution_ids).only(
                "execution_id", "decision", "confidence",
            )
        )
    except Exception:
        reports = []

    try:
        log_rows = list(
            SyncExecutionLog.objects.filter(execution_id__in=execution_ids).only(
                "execution_id", "attempts", "dead_letter_count",
            )
        )
    except Exception:
        log_rows = []

    reports_by_exec: Dict[str, List[Any]] = {}
    for r in reports:
        reports_by_exec.setdefault(str(r.execution_id), []).append(r)

    logs_by_exec: Dict[str, List[Any]] = {}
    for log in log_rows:
        logs_by_exec.setdefault(str(log.execution_id), []).append(log)

    job_to_execs: Dict[str, List[Any]] = {}
    for execution in executions:
        job_to_execs.setdefault(str(execution.job_id), []).append(execution)

    rows: List[Dict[str, Any]] = []
    for job in user_jobs:
        job_execs = job_to_execs.get(str(job.id)) or []
        last_execution = job_execs[0] if job_execs else None
        last_decision = "unknown"
        last_confidence: Optional[float] = None
        if last_execution is not None:
            last_reports = reports_by_exec.get(str(last_execution.id)) or []
            if last_reports:
                last_decision = _worst_decision(
                    [(r.decision or "unknown").lower() for r in last_reports]
                )
                conf_values = [
                    float(r.confidence)
                    for r in last_reports
                    if r.confidence is not None
                ]
                if conf_values:
                    last_confidence = min(conf_values)

        attempts: List[int] = []
        dead_letter_count = 0
        drift_count = 0
        for execution in job_execs:
            for log in logs_by_exec.get(str(execution.id)) or []:
                attempts.append(int(getattr(log, "attempts", 0) or 0))
                dead_letter_count += int(
                    getattr(log, "dead_letter_count", 0) or 0
                )
            for r in reports_by_exec.get(str(execution.id)) or []:
                if (r.decision or "").lower() in DRIFT_DECISIONS:
                    drift_count += 1

        rows.append({
            "job_id": str(job.id),
            "job_name": job.name,
            "sync_type": getattr(job, "sync_type", "") or "",
            "status": getattr(job, "status", "") or "",
            "executions_in_window": len(job_execs),
            "last_execution_id": (
                str(last_execution.id) if last_execution is not None else None
            ),
            "last_started_at": (
                last_execution.started_at.isoformat()
                if last_execution and last_execution.started_at
                else None
            ),
            "last_completed_at": (
                last_execution.completed_at.isoformat()
                if last_execution and last_execution.completed_at
                else None
            ),
            "last_status": (
                last_execution.status if last_execution is not None else None
            ),
            "last_decision": last_decision,
            "last_confidence": last_confidence,
            "attempts_p95": _percentile(attempts, 0.95),
            "dead_letter_count": dead_letter_count,
            "drift_count": drift_count,
        })

    rows.sort(
        key=lambda r: (r.get("last_started_at") or ""),
        reverse=True,
    )
    return rows


def _worst_decision(decisions: List[str]) -> str:
    """Pick the most severe decision in the list (drift > unknown > ok)."""
    order = {
        "repair_full": 4,
        "repair_incremental": 3,
        "warning": 2,
        "unknown": 1,
        "ok": 0,
    }
    if not decisions:
        return "unknown"
    return max(decisions, key=lambda d: order.get(d, 1))


def latest_terminal_executions_for_job(job, *, limit: int) -> List[Any]:
    """Return up to ``limit`` most recent terminal executions for ``job``.

    Includes the supplied execution itself when it is already terminal so
    the SLO breach detector can include the just-finished run.
    """
    limit = max(1, min(int(limit), _MAX_STREAK_LOOKBACK))
    try:
        return list(
            SyncExecution.objects.filter(
                job=job,
                status__in=TERMINAL_STATUSES,
            )
            .only("id", "status", "started_at", "completed_at")
            .order_by("-started_at")[:limit]
        )
    except Exception:
        logger.exception(
            "latest_terminal_executions_for_job: failed for job=%s",
            getattr(job, "id", None),
        )
        return []


def execution_slo_status(execution) -> Dict[str, Any]:
    """Return a per-execution SLO snapshot.

    Mirrors the ``slo`` block from ``compute_health_rollup`` but scoped to
    the single execution.  Used by ``detect_slo_breach`` per-execution.
    """
    targets = slo_targets()
    try:
        reports = list(
            ReconciliationReport.objects.filter(execution=execution).only(
                "decision", "confidence",
            )
        )
    except Exception:
        logger.exception(
            "execution_slo_status: failed to load reports for execution=%s",
            getattr(execution, "id", None),
        )
        reports = []

    try:
        logs = list(
            SyncExecutionLog.objects.filter(execution=execution).only(
                "attempts", "dead_letter_count", "rows_fetched",
            )
        )
    except Exception:
        logger.exception(
            "execution_slo_status: failed to load logs for execution=%s",
            getattr(execution, "id", None),
        )
        logs = []

    total_tables = len(reports)
    ok_tables = sum(
        1 for r in reports if (r.decision or "unknown").lower() == "ok"
    )
    ok_rate = _ratio(ok_tables, total_tables, default=1.0) if total_tables else 1.0

    rows_fetched = sum(int(getattr(l, "rows_fetched", 0) or 0) for l in logs)
    dead_letter_rows = sum(
        int(getattr(l, "dead_letter_count", 0) or 0) for l in logs
    )
    dead_letter_pct = _ratio(dead_letter_rows, rows_fetched, default=0.0)

    attempts_values = [int(getattr(l, "attempts", 0) or 0) for l in logs]
    attempts_p95 = _percentile(attempts_values, 0.95)

    confidence_values = [
        float(r.confidence) for r in reports if r.confidence is not None
    ]
    min_confidence = min(confidence_values) if confidence_values else None

    return {
        "execution_id": str(getattr(execution, "id", "")),
        "totals": {
            "tables": total_tables,
            "ok_tables": ok_tables,
            "rows_fetched": rows_fetched,
            "dead_letter_rows": dead_letter_rows,
        },
        "slo": _build_slo_block(
            ok_rate=ok_rate,
            dead_letter_pct=dead_letter_pct,
            attempts_p95=attempts_p95,
            confidence_floor_seen=min_confidence,
            targets=targets,
        ),
    }


def detect_slo_breach(execution) -> List[Dict[str, Any]]:
    """Return the list of SLOs breached for N consecutive executions.

    The detector walks back the most recent ``SLO_BREACH_STREAK_N`` terminal
    executions of the same job (newest first, including ``execution`` if it
    is already terminal) and only emits a breach when *every* execution in
    that window violates the same SLO.  An empty list means no breach.

    Never raises - on any DB error returns ``[]`` and logs.
    """
    try:
        job = getattr(execution, "job", None)
        if job is None:
            return []
        targets = slo_targets()
        n = int(targets["breach_streak_n"])
        recent = latest_terminal_executions_for_job(job, limit=n)
        if len(recent) < n:
            return []

        # Make sure ``execution`` is part of the streak (it might not be if
        # the executor close hook is run before status flips to terminal).
        recent_ids = {str(e.id) for e in recent}
        execution_id = str(getattr(execution, "id", ""))
        if execution_id and execution_id not in recent_ids:
            recent = [execution] + recent
            recent = recent[:n]

        per_execution = [execution_slo_status(e) for e in recent]
        breaches: List[Dict[str, Any]] = []
        for slo_name in ("ok_rate", "dead_letter_pct", "attempts_p95", "confidence_floor"):
            statuses = [p["slo"].get(slo_name) for p in per_execution]
            if not statuses or any(s is None for s in statuses):
                continue
            if all(s.get("ok") is False for s in statuses):
                latest = statuses[0]
                breaches.append({
                    "slo": slo_name,
                    "value": latest.get("value"),
                    "target": latest.get("target"),
                    "streak": n,
                })
        return breaches
    except Exception:
        logger.exception(
            "detect_slo_breach: unexpected error for execution=%s",
            getattr(execution, "id", None),
        )
        return []


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_SLO_OK_RATE",
    "DEFAULT_SLO_DEAD_LETTER_PCT_MAX",
    "DEFAULT_SLO_RETRY_ATTEMPT_P95",
    "DEFAULT_SLO_DRIFT_CONFIDENCE_FLOOR",
    "DEFAULT_SLO_BREACH_STREAK_N",
    "DRIFT_DECISIONS",
    "TERMINAL_STATUSES",
    "slo_targets",
    "compute_health_rollup",
    "compute_job_health",
    "latest_terminal_executions_for_job",
    "execution_slo_status",
    "detect_slo_breach",
]
