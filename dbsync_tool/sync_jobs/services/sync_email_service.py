"""
Send sync execution summary emails.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email

from sync_jobs.models import SyncExecution
from sync_jobs.services.execution_summary_service import build_execution_summary

logger = logging.getLogger(__name__)

# Day-6: dedicated structured drift channel.  A separate logger lets ops route
# drift signals into a SIEM/alerts pipeline without touching the noisy
# ``sync_jobs`` channel.
DRIFT_LOG = logging.getLogger("sync_jobs.drift")


def _valid_email(value: str) -> bool:
    if not value:
        return False
    try:
        validate_email(value)
        return True
    except ValidationError:
        return False


def resolve_summary_recipients(execution: SyncExecution) -> list[str]:
    """
    Resolve recipients from ADMIN_EMAILS + creator email (deduplicated).
    """
    recipients: list[str] = []

    admin_emails = getattr(settings, "ADMIN_EMAILS", []) or []
    if isinstance(admin_emails, str):
        admin_emails = [x.strip() for x in admin_emails.split(",")]
    for email in admin_emails:
        if isinstance(email, str) and _valid_email(email.strip()):
            recipients.append(email.strip())

    creator_email = ((execution.job.created_by.email or "") if execution.job and execution.job.created_by else "").strip()
    if _valid_email(creator_email):
        recipients.append(creator_email)

    # Preserve order, deduplicate
    return list(dict.fromkeys(recipients))


def _build_subject(summary: dict[str, Any]) -> str:
    status = (summary.get("status") or "").lower()
    state = "Completed" if status == "completed" else "Failed"
    return f"[DB Sync] {state}: {summary.get('job_name', '-') } ({summary.get('sync_type', '-')})"


def _build_text_body(summary: dict[str, Any]) -> str:
    header = [
        f"Job: {summary.get('job_name', '-')}",
        f"Execution ID: {summary.get('execution_id', '-')}",
        f"Status: {summary.get('status', '-')}",
        f"Sync Type: {summary.get('sync_type', '-')}",
        f"Migration: {summary.get('migration_path', '-')}",
        f"Started: {summary.get('started_at', '-')}",
        f"Completed: {summary.get('completed_at', '-')}",
        f"Duration: {summary.get('duration_display', '-')}",
        "",
        "Summary",
        f"- Total Rows Added/Synced: {summary.get('total_rows_synced', 0)}",
        f"- Tables Total: {summary.get('total_tables', 0)}",
        f"- Tables Completed: {summary.get('completed_tables', 0)}",
        f"- Tables Failed: {summary.get('failed_tables', 0)}",
        f"- Tables Changed: {summary.get('tables_changed', 0)}",
        "",
    ]

    notes = summary.get("notes") or []
    if notes:
        header.extend(["Notes:"] + [f"- {n}" for n in notes] + [""])

    table_logs = summary.get("table_logs") or []
    body = header + ["Top Table Logs"]
    if not table_logs:
        body.append("- No table logs available.")
    else:
        for row in table_logs[:20]:
            body.append(
                (
                    f"- {row.get('schema_name', '-')}.{row.get('table_name', '-')}: "
                    f"status={row.get('status', '-')}, "
                    f"inserted={row.get('rows_inserted', 0)}, "
                    f"fetched={row.get('rows_fetched', 0)}"
                )
            )
            if row.get("error_message"):
                body.append(f"  error={row['error_message']}")
            elif row.get("verification_summary"):
                body.append(f"  verification={row['verification_summary']}")

    return "\n".join(body)


def send_execution_summary_email(execution: SyncExecution) -> dict[str, Any]:
    """
    Send one post-execution summary email.

    Returns:
        {"sent": bool, "error_message": str, "recipients": list[str]}
    """
    try:
        summary = build_execution_summary(execution)
        recipients = resolve_summary_recipients(execution)
        if not recipients:
            msg = "No valid recipients resolved for sync summary email."
            logger.warning(
                "%s execution=%s job=%s",
                msg,
                execution.id,
                execution.job_id,
            )
            return {"sent": False, "error_message": msg, "recipients": []}

        send_mail(
            subject=_build_subject(summary),
            message=_build_text_body(summary),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipients,
            fail_silently=False,
        )
        logger.info(
            "Sync summary email sent. execution=%s job=%s recipients=%s",
            execution.id,
            execution.job_id,
            ",".join(recipients),
        )
        return {"sent": True, "error_message": "", "recipients": recipients}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(
            "Sync summary email failed. execution=%s job=%s error=%s",
            getattr(execution, "id", None),
            getattr(execution, "job_id", None),
            exc,
            exc_info=True,
        )
        return {"sent": False, "error_message": str(exc), "recipients": []}


def _build_drift_text_body(report: Dict[str, Any]) -> str:
    """Build the plain-text body for a Day-6 drift alert email."""
    from sync_jobs.services import reconciliation_service

    execution = report.get("execution") or {}
    totals = report.get("totals") or {}
    lines = [
        f"Job: {execution.get('job_name', '-')}",
        f"Execution ID: {execution.get('id', '-')}",
        f"Sync Type: {execution.get('sync_type', '-')}",
        f"Status: {execution.get('status', '-')}",
        f"Started: {execution.get('started_at', '-')}",
        f"Completed: {execution.get('completed_at', '-')}",
        "",
        "Drift Summary",
        f"- Tables Total: {totals.get('tables', 0)}",
        f"- OK: {totals.get('ok', 0)}",
        f"- Warning: {totals.get('warning', 0)}",
        f"- Repair Full: {totals.get('repair_full', 0)}",
        f"- Repair Incremental: {totals.get('repair_incremental', 0)}",
        f"- Dead-letter rows: {totals.get('dead_letter_count', 0)}",
        f"- Attempts (sum): {totals.get('attempts_sum', 0)}",
        "",
        "Affected Tables",
    ]

    affected = list(reconciliation_service.drift_tables(report))
    if not affected:
        lines.append("- (none)")
    else:
        for table in affected[:50]:
            schema = table.get("schema_name", "-")
            name = table.get("table_name", "-")
            decision = (table.get("decision") or "unknown").upper()
            confidence = table.get("confidence")
            confidence_str = (
                f"{float(confidence):.2f}" if confidence is not None else "-"
            )
            lines.append(
                f"- {schema}.{name} | decision={decision} "
                f"| confidence={confidence_str} "
                f"| dead_letter={table.get('dead_letter_count', 0)} "
                f"| attempts={table.get('attempts', 0)}"
            )
        if len(affected) > 50:
            lines.append(f"- ... and {len(affected) - 50} more")

    lines.extend([
        "",
        "Full report: download via the execution detail page (Report JSON / CSV).",
    ])
    return "\n".join(lines)


def send_drift_alert(execution: SyncExecution) -> bool:
    """Send a single batched drift alert per execution.

    Always-on but safe-no-op when no drift is detected.  Returns ``True`` only
    when an email was actually dispatched.  Never raises - the executor
    finalization wraps this in its own ``try/except`` for belt-and-braces.
    """
    from sync_jobs.services import reconciliation_service

    execution_id = getattr(execution, "id", None)
    try:
        report = reconciliation_service.build_execution_report(execution)
    except Exception:
        DRIFT_LOG.exception(
            "execution %s: failed to build reconciliation report for drift alert",
            execution_id,
        )
        return False

    extra_base = {
        "execution_id": str(execution_id) if execution_id is not None else None,
        "job_id": str(getattr(execution, "job_id", "")) or None,
    }

    if not reconciliation_service.has_drift(report):
        DRIFT_LOG.info(
            "execution %s: no drift",
            execution_id,
            extra={**extra_base, "drift": False},
        )
        return False

    recipients = resolve_summary_recipients(execution)
    if not recipients:
        DRIFT_LOG.warning(
            "execution %s: drift detected but no valid recipients; alert skipped",
            execution_id,
            extra={
                **extra_base,
                "drift": True,
                "totals": report.get("totals", {}),
                "alert_sent": False,
            },
        )
        return False

    job_name = (report.get("execution") or {}).get("job_name") or "-"
    subject = f"[dbsync] Drift detected in execution {job_name}"
    body = _build_drift_text_body(report)

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        DRIFT_LOG.exception(
            "execution %s: drift alert send failed",
            execution_id,
        )
        return False

    totals = report.get("totals", {}) or {}
    DRIFT_LOG.warning(
        "execution %s: drift alert sent (tables=%s, warning=%s, repair_full=%s, repair_incremental=%s)",
        execution_id,
        totals.get("tables", 0),
        totals.get("warning", 0),
        totals.get("repair_full", 0),
        totals.get("repair_incremental", 0),
        extra={
            **extra_base,
            "drift": True,
            "totals": totals,
            "alert_sent": True,
            "recipients": recipients,
        },
    )
    return True


def _format_slo_value(slo_name: str, value: Any) -> str:
    """Compact, ops-friendly rendering of an SLO value for emails/logs."""
    try:
        if value is None:
            return "-"
        if slo_name in ("ok_rate", "confidence_floor"):
            return f"{float(value):.4f}"
        if slo_name == "dead_letter_pct":
            return f"{float(value):.6f}"
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _build_slo_breach_text_body(execution: SyncExecution, breaches: list) -> str:
    """Build the plain-text body for a Day-7 SLO breach email.

    ``breaches`` is the list returned by
    :func:`sync_jobs.services.ops_metrics_service.detect_slo_breach`.
    """
    job = getattr(execution, "job", None)
    job_name = getattr(job, "name", "-") if job else "-"
    sync_type = getattr(job, "sync_type", "-") if job else "-"
    started_at = getattr(execution, "started_at", None)
    completed_at = getattr(execution, "completed_at", None)

    lines = [
        f"Job: {job_name}",
        f"Execution ID: {execution.id}",
        f"Sync Type: {sync_type}",
        f"Status: {getattr(execution, 'status', '-')}",
        f"Started: {started_at.isoformat() if started_at else '-'}",
        f"Completed: {completed_at.isoformat() if completed_at else '-'}",
        "",
        "SLO Breach Summary",
        "Breached SLOs (consecutive breach across recent executions):",
    ]
    if not breaches:
        lines.append("- (none)")
    else:
        for breach in breaches:
            slo_name = breach.get("slo", "-")
            value_str = _format_slo_value(slo_name, breach.get("value"))
            target_str = _format_slo_value(slo_name, breach.get("target"))
            streak = breach.get("streak", "-")
            lines.append(
                f"- {slo_name}: value={value_str} | target={target_str} "
                f"| streak={streak}"
            )

    lines.extend([
        "",
        "Investigate via the ops health page (Recent 24h) and the per-execution",
        "reconciliation report (Report JSON / CSV) on the execution detail page.",
    ])
    return "\n".join(lines)


def send_slo_breach_email(execution: SyncExecution, breaches: list) -> bool:
    """Send a single SLO breach email when ``breaches`` is non-empty.

    Composed by the executor close hook *after* ``send_drift_alert`` so a
    misconfigured SMTP cannot suppress the summary or drift email.  Never
    raises; exceptions are logged via ``DRIFT_LOG.exception`` and return
    ``False``.

    Returns ``True`` only when an email was actually dispatched.
    """
    execution_id = getattr(execution, "id", None)
    extra_base = {
        "execution_id": str(execution_id) if execution_id is not None else None,
        "job_id": str(getattr(execution, "job_id", "")) or None,
        "slo_breach": True,
    }

    if not breaches:
        DRIFT_LOG.info(
            "execution %s: no SLO breach",
            execution_id,
            extra={**extra_base, "slo_breach": False},
        )
        return False

    recipients = resolve_summary_recipients(execution)
    if not recipients:
        DRIFT_LOG.warning(
            "execution %s: SLO breach detected but no valid recipients; alert skipped",
            execution_id,
            extra={
                **extra_base,
                "breaches": breaches,
                "alert_sent": False,
            },
        )
        return False

    job = getattr(execution, "job", None)
    job_name = getattr(job, "name", "-") if job else "-"
    subject = f"[dbsync] SLO breach: {job_name}"
    body = _build_slo_breach_text_body(execution, breaches)

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        DRIFT_LOG.exception(
            "execution %s: SLO breach email send failed",
            execution_id,
        )
        return False

    DRIFT_LOG.error(
        "execution %s: SLO breach alert sent (count=%s, slos=%s)",
        execution_id,
        len(breaches),
        ",".join(b.get("slo", "-") for b in breaches),
        extra={
            **extra_base,
            "breaches": breaches,
            "alert_sent": True,
            "recipients": recipients,
        },
    )
    return True

