"""
SAP Business One → ClickHouse runner.

Executes the ultra-optimized SAP sync scripts (sap_full.py / sap_increment.py)
for a given SyncJob by building the correct environment from the job's API and DB connections.
"""

import os
import sys
import logging
import subprocess
import re
import json
from pathlib import Path
from typing import Literal
from datetime import datetime

from django.utils import timezone
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog
from connections.models import APIConnection, DatabaseConnection

logger = logging.getLogger(__name__)

Mode = Literal["full", "incremental"]

def _get_sap_and_clickhouse_params(job: SyncJob) -> tuple[dict, dict]:
    """
    Extract SAP B1 and ClickHouse connection parameters from the job.
    """
    api_conn: APIConnection = job.source_api_connection
    if not api_conn:
        raise ValueError("SAP B1 job is missing source_api_connection")
    if api_conn.api_type != "sap_b1":
        raise ValueError(f"Expected sap_b1 api_type, got {api_conn.api_type!r}")

    db_conn: DatabaseConnection = job.target_connection
    if not db_conn:
        raise ValueError("SAP B1 job is missing target_connection (ClickHouse)")

    # Extracted from APIConnection (includes decrypted sap_password)
    sap_params = api_conn.get_connection_params()
    
    # Extracted from DatabaseConnection (includes decrypted password)
    db_params = db_conn.get_connection_params()

    clickhouse_params = {
        "host": db_params["host"],
        "port": str(db_params["port"]),
        "user": db_params["username"],
        "password": db_params["password"],
        "database": db_params["database_name"],
    }

    return sap_params, clickhouse_params

def _populate_execution_logs_from_stdout(execution: SyncExecution, stdout: str) -> None:
    """
    Parse SAP script output and create SyncExecutionLog rows for UI visibility.
    """
    if not stdout:
        return

    selected_endpoints = {
        t.table_name for t in execution.job.tables.filter(is_enabled=True).all()
    }
    
    # If no tables are explicitly defined in SyncJobTable, check connection sap_endpoints
    if not selected_endpoints:
        api_conn = execution.job.source_api_connection
        if api_conn and api_conn.sap_endpoints:
            selected_endpoints = set(api_conn.sap_endpoints)

    current_module: str | None = None
    total_rows = 0
    tables_seen = set()

    # Regex patterns based on sap_increment.py / sap_full.py logging
    # [1/25] Journal Entry
    module_start_re = re.compile(r"\[\d+/\d+\]\s+(.+)$")
    #  ✓ Batch X: Inserted 1,234 records (Total: 5,678)
    #  ✓ Journal Entry (INC): 123 updates in 1.2s
    #  • Records in DB: 155
    count_re = re.compile(r"(?:Total(?:\s+fetched)?|Records in DB|updates):\s*([\d,]+)", re.IGNORECASE)

    for line in stdout.splitlines():
        line = line.strip()
        
        # Check for module start
        module_match = module_start_re.search(line)
        if module_match:
            current_module = module_match.group(1).strip()
            continue

        if current_module:
            count_match = count_re.search(line)
            if count_match:
                rows = int(count_match.group(1).replace(",", ""))
                
                # Check if this module is complete
                if "COMPLETE" in line.upper() or "updates" in line:
                    SyncExecutionLog.objects.create(
                        execution=execution,
                        schema_name="api",
                        table_name=current_module,
                        status="completed",
                        rows_fetched=rows,
                        rows_inserted=rows,
                        batch_number=1,
                        completed_at=timezone.now(),
                    )
                    tables_seen.add(current_module)
                    total_rows += rows
                    current_module = None

    # Update execution aggregates
    execution.completed_tables = len(tables_seen)
    execution.total_rows_synced = total_rows

def run_sap_b1_sync(job: SyncJob, execution: SyncExecution, mode: Mode = "full") -> None:
    """
    Execute SAP B1 → ClickHouse sync for the given job using standalone scripts.
    """
    mode_normalized: Mode = "incremental" if str(mode).lower() == "incremental" else "full"
    
    sap_params, clickhouse_params = _get_sap_and_clickhouse_params(job)
    
    project_root = Path(__file__).resolve().parents[1]
    scripts_dir = str(project_root / "scripts")
    
    env = os.environ.copy()
    _pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{str(project_root)}{os.pathsep}{scripts_dir}" + (os.pathsep + _pp if _pp else "")

    # Injecting environment variables for sap_increment.py / sap_full.py
    env.update({
        "SAP_API_BASE_URL": sap_params.get("base_url") or "",
        "SAP_USERNAME": json.dumps(sap_params.get("username", {})),
        "SAP_PASSWORD": sap_params.get("password") or "",
        "CLICKHOUSE_HOST": clickhouse_params["host"],
        "CLICKHOUSE_PORT": clickhouse_params["port"],
        "CLICKHOUSE_USER": clickhouse_params["user"],
        "CLICKHOUSE_PASS": clickhouse_params["password"],
        "CLICKHOUSE_DB": clickhouse_params["database"],
    })

    # Add module filter if specific tables are selected
    selected_tables = job.tables.filter(is_enabled=True).values_list('table_name', flat=True)
    if selected_tables:
        env["SAP_MODULE_FILTER"] = ",".join(selected_tables)
    elif job.source_api_connection.sap_endpoints:
        env["SAP_MODULE_FILTER"] = ",".join(job.source_api_connection.sap_endpoints)

    script_name = "sap_increment.py" if mode_normalized == "incremental" else "sap_full.py"
    script_path = Path(scripts_dir) / script_name

    if not script_path.exists():
        raise FileNotFoundError(f"SAP sync script not found at {script_path}")

    logger.info(
        "Starting SAP B1 %s sync for job %s (execution %s) - db=%s, script=%s",
        mode_normalized, job.id, execution.id, clickhouse_params["database"], script_name
    )

    execution.status = "running"
    execution.started_at = timezone.now()
    execution.save(update_fields=["status", "started_at"])

    cmd = [sys.executable, str(script_path)]
    
    # We might want to pass --days if it's an incremental run
    if mode_normalized == "incremental":
        # Check if job has lookback config (placeholder or specific field)
        cmd.extend(["--days", "2"])

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
        
        log_snippet = f"STDOUT:\n{stdout[:2000]}\n\nSTDERR:\n{stderr[:2000]}"
        
        if result.returncode == 0:
            execution.status = "completed"
            try:
                _populate_execution_logs_from_stdout(execution, stdout)
            except Exception as e:
                logger.warning(f"Failed to populate SAP execution logs: {e}")
            execution.error_message = f"Sync successful.\n{log_snippet}"
        else:
            execution.status = "failed"
            execution.error_message = f"Script failed with code {result.returncode}.\n{log_snippet}"
            logger.error(f"SAP sync script failed for job {job.id}")

    except Exception as e:
        execution.status = "failed"
        execution.error_message = f"Runner exception: {str(e)}"
        logger.exception(f"SAP runner crashed for job {job.id}")

    finally:
        execution.completed_at = timezone.now()
        execution.save()
