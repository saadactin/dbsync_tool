"""
Zoho CRM → ClickHouse runner that delegates Zoho syncs to the standalone
`scripts/zoho_full.py` and `scripts/zoho_increment.py` scripts.

This mirrors the Azure DevOps runner pattern: we build environment variables
from the APIConnection + DatabaseConnection associated with the SyncJob,
spawn the external script, and wire stdout/stderr back into SyncExecution.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import Literal

from django.db import transaction
from django.utils import timezone

from connections.models import APIConnection, DatabaseConnection
from core.exceptions import EncryptionError
from sync_jobs.models import SyncExecution, SyncExecutionLog, SyncJob

logger = logging.getLogger(__name__)

Mode = Literal["full", "incremental"]


@dataclass(frozen=True)
class _ParsedZohoTableRow:
    table_suffix: str
    rows: int
    duration_s: float
    access_ok: bool  # False for NO_ACCESS / skipped module


def _build_clickhouse_env(db_conn: DatabaseConnection) -> dict:
    """
    Build ClickHouse-related environment variables for Zoho scripts.
    """
    try:
        password = db_conn.get_decrypted_password()
    except EncryptionError as exc:
        # Surface a clear error to the execution rather than silently failing.
        raise ValueError(
            f"Failed to decrypt ClickHouse password for connection '{db_conn.name}': {exc}"
        ) from exc

    return {
        "CLICKHOUSE_HOST": db_conn.host or "",
        "CLICKHOUSE_PORT": str(db_conn.port or 8123),
        "CLICKHOUSE_USER": db_conn.username or "",
        "CLICKHOUSE_PASS": password or "",
        "CLICKHOUSE_DB": db_conn.database_name or "",
    }


def _build_zoho_env(api_conn: APIConnection) -> dict:
    """
    Build Zoho-related environment variables for Zoho scripts.

    We intentionally keep names generic so the scripts can be reused in other
    contexts as long as these env vars are provided.
    """
    env: dict[str, str] = {}

    # Core OAuth credentials (decrypted)
    params = api_conn.get_connection_params()
    env["ZOHO_CLIENT_ID"] = params.get("client_id") or ""
    env["ZOHO_CLIENT_SECRET"] = params.get("client_secret") or ""
    env["ZOHO_REFRESH_TOKEN"] = params.get("refresh_token") or ""

    # Domain / token endpoints
    if params.get("api_domain"):
        env["ZOHO_API_DOMAIN"] = params["api_domain"]
    if params.get("token_url"):
        env["ZOHO_TOKEN_URL"] = params["token_url"]

    # Optional: prefix for all tables (we use the same default as the scripts)
    env.setdefault("PREFIX_ZOHO", "ZOHO_")

    return env


# Legacy script summary:
# ZOHO_leads  ✓ SUCCESS  +22 / -1 ( 17.5s)
_RE_LEGACY_SUCCESS = re.compile(
    r"ZOHO_(\S+)\s+✓ SUCCESS\s+\+(\d+)\s*/\s*-(\d+)\s*\(\s*([\d\.]+)s\)"
)

# Optimized MIGRATION SUMMARY (see logs/zoho_full_optimized_*.log):
# ... INFO - ZOHO_activities                     ✓ SUCCESS        50,890   210.8s
_RE_OPTIMIZED_SUCCESS = re.compile(
    r"ZOHO_(\S+)\s+✓ SUCCESS\s+([\d,]+)\s+([\d\.]+)s"
)

# ... INFO - ZOHO_projects                       ⚠ NO_ACCESS            0     0.1s
_RE_OPTIMIZED_NO_ACCESS = re.compile(
    r"ZOHO_(\S+)\s+⚠ NO_ACCESS\s+([\d,]+)\s+([\d\.]+)s"
)

# Machine-readable live line (emit from zoho_full.py for per-module UI updates):
# ZOHO_SYNC_LOG v1|table=activities|status=success|rows=50890|seconds=210.8
_RE_STRUCT_LINE = re.compile(r"^ZOHO_SYNC_LOG v1\|(.+)$")


def _parse_migration_summary_text(text: str) -> dict[str, _ParsedZohoTableRow]:
    """
    Parse all known Zoho log formats into a map table_suffix -> row data.
    Later patterns in the file do not override earlier ones for the same key
    (first wins), so streaming structured lines can be merged before a final
    summary pass if needed — callers should pass text in desired precedence.
    """
    # Last occurrence in the file wins (MIGRATION SUMMARY typically appears once at the end).
    out: dict[str, _ParsedZohoTableRow] = {}

    def _set(
        suffix: str,
        rows: int,
        duration_s: float,
        access_ok: bool,
    ) -> None:
        out[suffix] = _ParsedZohoTableRow(
            table_suffix=suffix,
            rows=rows,
            duration_s=duration_s,
            access_ok=access_ok,
        )

    for match in _RE_LEGACY_SUCCESS.finditer(text):
        suffix = match.group(1)
        upserted = int(match.group(2) or "0")
        duration_s = float(match.group(4) or "0")
        _set(suffix, upserted, duration_s, True)

    for match in _RE_OPTIMIZED_SUCCESS.finditer(text):
        suffix = match.group(1)
        raw_rows = (match.group(2) or "0").replace(",", "")
        rows = int(raw_rows)
        duration_s = float(match.group(3) or "0")
        _set(suffix, rows, duration_s, True)

    for match in _RE_OPTIMIZED_NO_ACCESS.finditer(text):
        suffix = match.group(1)
        duration_s = float(match.group(3) or "0")
        _set(suffix, 0, duration_s, False)

    return out


def _verification_and_times(
    duration_s: float, access_ok: bool
) -> tuple[str | None, datetime | None, datetime | None]:
    """Build verification text and optional started/completed for Duration column."""
    if not access_ok:
        summary = "NO_ACCESS"
        return summary, None, None
    summary = f"Duration: {duration_s:g}s"
    end = timezone.now()
    start = end - timedelta(seconds=max(duration_s, 0.001))
    return summary, start, end


def _sync_execution_logs_from_parsed_map(
    execution: SyncExecution,
    parsed: dict[str, _ParsedZohoTableRow],
) -> None:
    """Replace execution logs with rows built from parsed map."""
    SyncExecutionLog.objects.filter(execution=execution).delete()

    total_rows = 0
    schema_name = "api"

    for suffix, row in parsed.items():
        ver, started_at, completed_at = _verification_and_times(
            row.duration_s, row.access_ok
        )
        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name=schema_name,
            table_name=suffix,
            status="completed",
            rows_fetched=row.rows,
            rows_inserted=row.rows,
            batch_number=1,
            error_message=None,
            verification_summary=ver,
            started_at=started_at,
            completed_at=completed_at,
        )
        total_rows += row.rows

    if parsed:
        execution.total_tables = execution.total_tables or len(parsed)
        execution.completed_tables = len(parsed)
        execution.total_rows_synced = total_rows
        execution.save(
            update_fields=["total_tables", "completed_tables", "total_rows_synced"]
        )


def _populate_execution_logs_from_stdout(
    execution: SyncExecution,
    stdout: str,
) -> None:
    """
    Parse zoho_full/zoho_increment summary lines from stdout and create
    SyncExecutionLog rows so the UI can show per-table stats.

    Supports:
    - Legacy: ZOHO_leads  ✓ SUCCESS  +3 / -0 ( 13.5s)
    - Optimized MIGRATION SUMMARY: ZOHO_activities  ✓ SUCCESS  50,890  210.8s
    - NO_ACCESS: ZOHO_projects  ⚠ NO_ACCESS  0  0.1s
    """
    if not stdout:
        return

    parsed = _parse_migration_summary_text(stdout)
    if not parsed:
        return

    _sync_execution_logs_from_parsed_map(execution, parsed)


def _parse_structured_zoho_line(line: str) -> dict[str, str] | None:
    """Parse ZOHO_SYNC_LOG v1|key=value|... into a dict."""
    m = _RE_STRUCT_LINE.match(line.strip())
    if not m:
        return None
    out: dict[str, str] = {}
    for part in m.group(1).split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out if out else None


def _apply_structured_zoho_line(execution: SyncExecution, line: str) -> None:
    """
    Apply one live ZOHO_SYNC_LOG line — creates/updates a single log row
    and refreshes execution aggregates (for polling UI).
    """
    data = _parse_structured_zoho_line(line)
    if not data:
        return

    table_suffix = data.get("table") or data.get("table_suffix") or ""
    if not table_suffix:
        return

    status_raw = (data.get("status") or "success").lower()
    access_ok = status_raw in ("success", "completed", "ok")
    try:
        rows = int(data.get("rows") or "0")
    except ValueError:
        rows = 0
    try:
        duration_s = float(data.get("seconds") or data.get("duration_s") or "0")
    except ValueError:
        duration_s = 0.0

    ver, started_at, completed_at = _verification_and_times(duration_s, access_ok)

    SyncExecutionLog.objects.filter(
        execution=execution,
        schema_name="api",
        table_name=table_suffix,
    ).delete()
    SyncExecutionLog.objects.create(
        execution=execution,
        schema_name="api",
        table_name=table_suffix,
        status="completed",
        rows_fetched=rows,
        rows_inserted=rows,
        batch_number=1,
        error_message=None,
        verification_summary=ver,
        started_at=started_at,
        completed_at=completed_at,
    )

    logs = SyncExecutionLog.objects.filter(execution=execution)
    execution.completed_tables = logs.filter(status="completed").count()
    execution.total_tables = max(execution.total_tables or 0, logs.count())
    execution.total_rows_synced = sum(int(x or 0) for x in logs.values_list("rows_fetched", flat=True))
    execution.save(
        update_fields=["completed_tables", "total_tables", "total_rows_synced"]
    )


def _read_stderr_thread(proc: subprocess.Popen, bucket: list[str]) -> None:
    err = proc.stderr.read()
    if err:
        bucket.append(err if isinstance(err, str) else err.decode("utf-8", errors="replace"))


def _resolve_parse_source(
    project_root: Path,
    mode: Mode,
    stdout: str,
) -> str:
    """
    Backwards-compatible helper used by older callers/tests.

    Prefer stdout; if empty, fall back to reading today's Zoho disk log file(s).
    """
    if stdout:
        return stdout
    return _read_zoho_disk_logs(project_root, mode)


def _read_zoho_disk_logs(project_root: Path, mode: Mode) -> str:
    """
    Read today's Zoho log file(s) for the given mode.

    For "full": prefer `zoho_full_optimized_{today}.log`, then `zoho_full_{today}.log`.
    For both modes: also consider `zoho_increment_{today}.log` as a last resort.
    """
    try:
        logs_dir = project_root / "logs"
        today = datetime.now().strftime("%Y%m%d")

        candidates: list[Path] = []
        if mode == "full":
            candidates.extend(
                [
                    logs_dir / f"zoho_full_optimized_{today}.log",
                    logs_dir / f"zoho_full_{today}.log",
                ]
            )

        candidates.append(logs_dir / f"zoho_increment_{today}.log")

        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Failed to read Zoho log file fallback: %s", e)

    return ""


def run_zoho_sync(job: SyncJob, execution: SyncExecution, mode: Mode = "full") -> None:
    """
    Run Zoho sync for the given job by invoking zoho_full.py or
    zoho_increment.py based on mode.

    This assumes:
    - job.source_api_connection is a Zoho CRM APIConnection
    - job.target_connection is a ClickHouse DatabaseConnection
    - mode 'full' or 'incremental'
    """
    api_conn = job.source_api_connection
    db_conn = job.target_connection

    if not api_conn:
        raise ValueError("Zoho sync requires an API source connection")
    if not db_conn:
        raise ValueError("Zoho sync requires a target database connection")

    project_root = Path(__file__).resolve().parents[1]
    scripts_dir = project_root / "scripts"
    script_name = "zoho_increment.py" if mode == "incremental" else "zoho_full.py"
    script_path = scripts_dir / script_name

    if not script_path.exists():
        raise FileNotFoundError(f"{script_name} not found at {script_path}")

    base_env = os.environ.copy()
    env = {
        **base_env,
        **_build_clickhouse_env(db_conn),
        **_build_zoho_env(api_conn),
    }
    if getattr(job, "target_table_prefix", None):
        env["TARGET_TABLE_PREFIX"] = job.target_table_prefix
    if mode == "incremental":
        env["STRICT_INCREMENTAL_EXISTING_TABLES"] = "1"

    mode_label = mode or "full"

    logger.info(
        "Starting Zoho %s sync for job %s (%s) execution %s - "
        "api_connection=%s, clickhouse=%s/%s, script=%s",
        mode_label,
        job.id,
        job.name,
        execution.id,
        api_conn.name,
        db_conn.host,
        db_conn.database_name,
        script_path.name,
    )

    execution.status = "running"
    execution.started_at = timezone.now()
    execution.save(update_fields=["status", "started_at"])

    cmd = [sys.executable, str(script_path)]

    stderr_bucket: list[str] = []
    stdout_parts: list[str] = []

    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    err_thread = Thread(target=_read_stderr_thread, args=(proc, stderr_bucket))
    err_thread.start()

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            stdout_parts.append(line)
            if "ZOHO_SYNC_LOG v1|" in line:
                try:
                    _apply_structured_zoho_line(execution, line)
                except Exception as e:  # pragma: no cover
                    logger.warning("Zoho structured log line failed: %s", e)
    finally:
        proc.stdout.close()

    return_code = proc.wait()
    err_thread.join()
    stderr = (stderr_bucket[0] if stderr_bucket else "").strip()

    stdout = "".join(stdout_parts).strip()

    max_log = 20000
    combined_log = stdout
    if stderr:
        combined_log = (stdout + "\n\n[stderr]\n" + stderr).strip()

    # Zoho scripts often write the MIGRATION SUMMARY mainly to the log file,
    # not stdout. We merge disk + stdout so the execution detail page can
    # reliably populate per-table rows.
    disk_text = _read_zoho_disk_logs(project_root, mode)
    parse_source = (disk_text + "\n" + stdout).strip()

    if return_code == 0:
        try:
            with transaction.atomic():
                _populate_execution_logs_from_stdout(execution, parse_source or "")
        except Exception as e:  # pragma: no cover - defensive logging only
            logger.warning("Failed to populate Zoho execution logs: %s", e)

    if return_code == 0:
        execution.status = "completed"
        execution.error_message = (
            f"Zoho {mode_label} sync succeeded for job {job.id} "
            f"({job.name}) - api={api_conn.name}, "
            f"clickhouse={db_conn.host}/{db_conn.database_name}"
        )[:5000]
    else:
        execution.status = "failed"
        execution.error_message = (
            combined_log[:5000] if combined_log else f"{script_name} exited with code {return_code}"
        )

    execution.completed_at = timezone.now()
    execution.save(
        update_fields=[
            "status",
            "error_message",
            "completed_at",
            "total_tables",
            "completed_tables",
            "total_rows_synced",
        ]
    )

    logger.info(
        "Zoho %s sync finished for job %s (%s) execution %s with code %s",
        mode_label,
        job.id,
        job.name,
        execution.id,
        return_code,
    )
