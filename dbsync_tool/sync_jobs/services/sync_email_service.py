"""
Send sync execution summary emails.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email

from sync_jobs.models import SyncExecution
from sync_jobs.services.execution_summary_service import build_execution_summary

logger = logging.getLogger(__name__)


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

