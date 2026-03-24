"""
Azure DevOps → ClickHouse runner.

Executes the Phase‑1 Azure DevOps scripts (devops_Full_sync.py / devops_Increment_sync.py)
for a given SyncJob by building the correct environment from the job's API and DB connections.

Environment passed to scripts (see also scripts/devops_config.py):
  AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_ORGANIZATION,
  CLICKHOUSE_HOST, CLICKHOUSE_USER, CLICKHOUSE_PASS, CLICKHOUSE_DB,
  optional TARGET_TABLE_PREFIX (matches SyncJob.target_table_prefix).

Incremental script also reads from the **host process** environment if set: REDIS_HOST,
REDIS_PORT, REDIS_DB, REDIS_KEY_PREFIX (defaults in devops_config). Subprocess inherits
os.environ, so you may export REDIS_* for the Django process.

STRICT_INCREMENTAL_EXISTING_TABLES=1 is set for incremental runs so the script fails fast
if prefixed work-item tables are missing.
"""

import os
import sys
import logging
import subprocess
import re
from pathlib import Path
from typing import Literal
from datetime import datetime

from django.utils import timezone

from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog
from connections.models import APIConnection, DatabaseConnection


logger = logging.getLogger(__name__)


Mode = Literal["full", "incremental"]


def _get_azure_and_clickhouse_params(job: SyncJob) -> tuple[dict, dict]:
    """
    Extract Azure DevOps and ClickHouse connection parameters from the job.

    Returns:
        (azure_params, clickhouse_params)
    """
    api_conn: APIConnection = job.source_api_connection
    if not api_conn:
        raise ValueError("Azure DevOps job is missing source_api_connection")
    if api_conn.api_type != "azure_devops":
        raise ValueError(f"Expected azure_devops api_type, got {api_conn.api_type!r}")

    db_conn: DatabaseConnection = job.target_connection
    if not db_conn:
        raise ValueError("Azure DevOps job is missing target_connection (ClickHouse)")

    # Use existing helper to get decrypted Azure values
    azure_params = api_conn.get_connection_params()

    # Use DatabaseConnection helper to get decrypted DB values
    db_params = db_conn.get_connection_params()

    clickhouse_params = {
        "host": db_params["host"],
        "user": db_params["username"],
        "password": db_params["password"],
        "database": db_params["database_name"],
    }

    return azure_params, clickhouse_params


def _populate_execution_logs_from_stdout(execution: SyncExecution, stdout: str) -> None:
    """
    Parse Azure DevOps script output and create SyncExecutionLog rows for UI visibility.
    """
    if not stdout:
        return

    # UI for Azure DevOps jobs uses SyncJobTable entries that store project names
    # as `schema_name="api", table_name="<project_name>"`.
    # Our DevOps scripts log per-project progress in a human-readable form.
    selected_project_names = {
        t.table_name for t in execution.job.tables.filter(is_enabled=True).all()
    }
    if not selected_project_names:
        return

    # Example log lines in scripts (emojis may change depending on encoding):
    #   📂 Project 1/5: Embedded
    #     • Processing 123 work items (10 new, 113 updated)
    # or in full mode:
    #   Processing Project 1/5: Embedded
    current_project: str | None = None
    logs_created = 0
    total_rows = 0
    tables_seen: set[str] = set()

    project_re = re.compile(r"(?:Project\s+\d+/\d+:\s*|Processing Project\s+\d+/\d+:\s*)(.+)\s*$")
    processing_re = re.compile(r"Processing\s+([\d,]+)\s+work items?", re.IGNORECASE)

    for line in stdout.splitlines():
        proj_match = project_re.search(line.strip())
        if proj_match:
            current_project = proj_match.group(1).strip()
            continue

        if current_project and current_project in selected_project_names:
            proc_match = processing_re.search(line)
            if proc_match:
                rows = int(proc_match.group(1).replace(",", ""))

                SyncExecutionLog.objects.create(
                    execution=execution,
                    schema_name="api",
                    table_name=current_project,
                    status="completed",
                    rows_fetched=rows,
                    rows_inserted=rows,
                    batch_number=1,
                    completed_at=timezone.now(),
                )
                logs_created += 1
                tables_seen.add(current_project)
                total_rows += rows
                current_project = None

    # Projects with zero changed work items are not printed by the incremental script
    # ("Processing N work items" is omitted), so parse creates no log row for them.
    # Fill in zero-row logs so the UI shows e.g. 3/3 instead of 1/1 when only one
    # project had deltas — the sync still covered the whole job (script exit 0).
    for proj in selected_project_names:
        if proj not in tables_seen:
            SyncExecutionLog.objects.create(
                execution=execution,
                schema_name="api",
                table_name=proj,
                status="completed",
                rows_fetched=0,
                rows_inserted=0,
                batch_number=1,
                completed_at=timezone.now(),
            )
            tables_seen.add(proj)

    # Update execution aggregates for the UI cards.
    if selected_project_names:
        execution.total_tables = len(selected_project_names)
        execution.completed_tables = len(tables_seen)
        execution.total_rows_synced = total_rows


def run_azure_devops_sync(job: SyncJob, execution: SyncExecution, mode: Mode = "full") -> None:
    """
    Execute Azure DevOps → ClickHouse sync for the given job.

    This function:
      - Builds environment variables from the Azure DevOps APIConnection and
        ClickHouse DatabaseConnection on the job.
      - Invokes the appropriate Phase‑1 script via subprocess.
      - Updates the provided SyncExecution with status, timestamps, and error info.
    """
    mode_normalized: Mode = "incremental" if str(mode).lower() == "incremental" else "full"

    azure_params, clickhouse_params = _get_azure_and_clickhouse_params(job)

    # dbsync_tool/ (parent of sync_engine/)
    project_root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    # Ensure package imports work if the script directory is not first on sys.path.
    scripts_dir = str(project_root / "scripts")
    _pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{str(project_root)}{os.pathsep}{scripts_dir}"
        + (os.pathsep + _pp if _pp else "")
    )

    env.update(
        {
            # Azure DevOps
            "AZURE_TENANT_ID": azure_params.get("tenant_id") or "",
            "AZURE_CLIENT_ID": azure_params.get("client_id") or "",
            "AZURE_CLIENT_SECRET": azure_params.get("client_secret") or "",
            "AZURE_ORGANIZATION": azure_params.get("organization") or "",
            # ClickHouse
            "CLICKHOUSE_HOST": clickhouse_params["host"],
            "CLICKHOUSE_USER": clickhouse_params["user"],
            "CLICKHOUSE_PASS": clickhouse_params["password"],
            "CLICKHOUSE_DB": clickhouse_params["database"],
        }
    )
    # Correlate subprocess execution with a persistent log file.
    env["DEVOPS_EXECUTION_ID"] = str(execution.id)
    if getattr(job, "target_table_prefix", None):
        env["TARGET_TABLE_PREFIX"] = job.target_table_prefix
    else:
        env.pop("TARGET_TABLE_PREFIX", None)

    if mode_normalized == "incremental":
        env["STRICT_INCREMENTAL_EXISTING_TABLES"] = "1"
    else:
        env.pop("STRICT_INCREMENTAL_EXISTING_TABLES", None)

    scripts_dir_path = project_root / "scripts"
    script_name = "devops_Increment_sync.py" if mode_normalized == "incremental" else "devops_Full_sync.py"
    script_path = scripts_dir_path / script_name

    if not script_path.exists():
        raise FileNotFoundError(f"Azure DevOps script not found at {script_path}")

    # Non‑sensitive context logging
    logger.info(
        "Starting Azure DevOps %s sync for job %s (%s) (execution %s) - "
        "organization=%s, clickhouse=%s/%s, script=%s",
        mode_normalized,
        job.id,
        job.name,
        execution.id,
        azure_params.get("organization"),
        clickhouse_params["host"],
        clickhouse_params["database"],
        script_path.name,
    )

    execution.status = "running"
    execution.started_at = timezone.now()
    execution.save(update_fields=["status", "started_at"])

    cmd = [sys.executable, str(script_path)]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        log_snippet = (
            f"=== Azure DevOps {mode_normalized} sync ===\n"
            f"Job: {job.id} ({job.name})\n"
            f"Script: {script_path.name}\n"
            f"Organization: {azure_params.get('organization')}\n"
            f"ClickHouse: {clickhouse_params['host']}/{clickhouse_params['database']}\n"
            f"Exit code: {result.returncode}\n\n"
            f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n"
        )

        parse_source = stdout
        if result.returncode == 0:
            # For incremental scripts we also write a file log; if stdout was empty
            # or unusable due to encoding, fall back to the latest log file.
            if not parse_source.strip():
                try:
                    logs_dir = project_root / "logs"
                    increment_logs = sorted(
                        logs_dir.glob("devops_increment_*.log"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if increment_logs:
                        parse_source = increment_logs[0].read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    logger.warning("Failed to read incremental devops log file: %s", e)

            execution.status = "completed"
            
            # Repopulate logs from output
            try:
                _populate_execution_logs_from_stdout(execution, parse_source)
            except Exception as e:
                logger.warning(f"Failed to populate DevOps execution logs: {e}")

            # Store a concise success summary for visibility in the UI.
            execution.error_message = (
                f"Azure DevOps {mode_normalized} sync succeeded for job {job.id} "
                f"({job.name}) - organization={azure_params.get('organization')}, "
                f"clickhouse={clickhouse_params['host']}/{clickhouse_params['database']}"
            )[:5000]
            logger.info(
                "Azure DevOps %s sync completed successfully for job %s (execution %s)",
                mode_normalized,
                job.id,
                execution.id,
            )
        else:
            execution.status = "failed"
            # Store truncated log snippet in error_message for visibility in UI.
            execution.error_message = log_snippet[:5000]
            logger.error(
                "Azure DevOps %s sync failed for job %s (execution %s) with exit code %s",
                mode_normalized,
                job.id,
                execution.id,
                result.returncode,
            )

    except Exception as exc:
        execution.status = "failed"
        execution.error_message = f"Azure DevOps {mode_normalized} sync crashed: {exc}"
        logger.exception(
            "Azure DevOps %s sync crashed for job %s (execution %s)",
            mode_normalized,
            job.id,
            execution.id,
        )

    finally:
        execution.completed_at = timezone.now()
        execution.save(
            update_fields=[
                "status", 
                "error_message", 
                "completed_at", 
                "total_tables", 
                "completed_tables", 
                "total_rows_synced"
            ]
        )


