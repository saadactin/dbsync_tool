"""
Build normalized sync execution summary payloads.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from sync_jobs.models import SyncExecution, SyncExecutionLog


def _format_duration(duration: timedelta | None) -> str:
    if not duration:
        return "-"
    total_seconds = max(int(duration.total_seconds()), 0)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _format_db_label(conn: Any) -> str:
    name = getattr(conn, "name", "Database")
    db_type = getattr(conn, "db_type", "db")
    host = getattr(conn, "host", "-")
    db_name = getattr(conn, "database_name", "-")
    port = getattr(conn, "port", "-")
    return f"{name} ({db_type}) - {host}:{port}/{db_name}"


def _format_api_label(conn: Any) -> str:
    name = getattr(conn, "name", "API")
    api_type = getattr(conn, "api_type", "api")
    return f"{name} ({api_type})"


def _get_source_and_target_labels(execution: SyncExecution) -> tuple[str, str]:
    job = execution.job
    source_label = "Unknown source"
    target_label = "Unknown target"

    if job.source_connection_type == "api" and job.source_api_connection:
        source_label = _format_api_label(job.source_api_connection)
    elif job.source_connection:
        source_label = _format_db_label(job.source_connection)

    if job.target_connection:
        target_label = _format_db_label(job.target_connection)

    return source_label, target_label


def build_execution_summary(execution: SyncExecution) -> dict[str, Any]:
    """
    Build a reusable summary payload for emails and future APIs.
    """
    execution = (
        SyncExecution.objects.select_related(
            "job",
            "job__created_by",
            "job__source_connection",
            "job__source_api_connection",
            "job__target_connection",
        )
        .get(pk=execution.pk)
    )

    logs = list(
        SyncExecutionLog.objects.filter(execution=execution).order_by(
            "-rows_inserted", "schema_name", "table_name"
        )
    )
    source_label, target_label = _get_source_and_target_labels(execution)

    failed_tables = sum(1 for log in logs if log.status == "failed")
    completed_tables = sum(1 for log in logs if log.status == "completed")
    tables_changed = sum(1 for log in logs if int(log.rows_inserted or 0) > 0)
    total_tables = execution.total_tables or len(logs)
    completed_at = execution.completed_at or timezone.now()
    started_at = execution.started_at
    duration = completed_at - started_at if started_at else None

    table_rows = [
        {
            "schema_name": log.schema_name,
            "table_name": log.table_name,
            "status": log.status,
            "rows_fetched": int(log.rows_fetched or 0),
            "rows_inserted": int(log.rows_inserted or 0),
            "batch_number": log.batch_number,
            "error_message": log.error_message or "",
            "verification_summary": log.verification_summary or "",
        }
        for log in logs
    ]

    return {
        "job_id": str(execution.job_id),
        "job_name": execution.job.name,
        "sync_type": execution.job.sync_type,
        "execution_id": str(execution.id),
        "status": execution.status,
        "started_at": started_at,
        "completed_at": execution.completed_at,
        "duration_display": _format_duration(duration),
        "source_label": source_label,
        "target_label": target_label,
        "migration_path": f"{source_label} -> {target_label}",
        "total_tables": int(total_tables),
        "completed_tables": int(execution.completed_tables or completed_tables),
        "failed_tables": int(failed_tables),
        "tables_changed": int(tables_changed),
        "total_rows_synced": int(execution.total_rows_synced or 0),
        "table_logs": table_rows,
        "has_table_logs": bool(table_rows),
        "notes": [] if table_rows else ["No table logs available for this execution."],
    }

