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


def _read_sap_disk_logs(project_root: Path, mode: Mode) -> str:
    """
    Read today's SAP sync log file for parser fallback.

    The SAP scripts commonly emit detailed module telemetry into disk logs
    (e.g. incremental_sync_YYYYMMDD.log) while stdout can be sparse.
    """
    try:
        logs_dir = project_root / "logs"
        today = datetime.now().strftime("%Y%m%d")
        candidates: list[Path] = []
        if mode == "incremental":
            candidates.append(logs_dir / f"incremental_sync_{today}.log")
        else:
            candidates.append(logs_dir / f"full_sync_{today}.log")
        # Cross-mode fallback in case script naming/config differs.
        candidates.append(logs_dir / f"incremental_sync_{today}.log")
        candidates.append(logs_dir / f"full_sync_{today}.log")

        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Failed to read SAP disk log fallback: %s", e)

    return ""

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

    # Matches examples:
    # 2026-04-15 10:33:23,174 - INFO - [2/23] Syncing Chart Of Account...
    # [2/23] Syncing Chart Of Account...
    module_start_re = re.compile(r"\[\d+/\d+\]\s+Syncing\s+(.+?)(?:\.\.\.)?$", re.IGNORECASE)
    fallback_module_start_re = re.compile(r"\[\d+/\d+\]\s+(.+)$")
    # ✓ Purchase Order (INC): 46 updates in 77.4s
    module_complete_re = re.compile(r"✓\s+(.+?)\s+\((INC|FULL)\):\s*([\d,]+)\s+updates", re.IGNORECASE)
    # ⚠ No data found for Returns
    no_data_re = re.compile(r"No data found for\s+(.+)$", re.IGNORECASE)
    fetched_re = re.compile(r"Fetched:\s*([\d,]+)", re.IGNORECASE)
    total_fetched_re = re.compile(r"Total fetched:\s*([\d,]+)", re.IGNORECASE)
    mode_fallback_re = re.compile(r"Incremental filter failed for\s+(.+?)\.\s+Falling back to full fetch", re.IGNORECASE)
    fetch_error_re = re.compile(r"Fetch error at skip=\d+:\s*(.*)$", re.IGNORECASE)
    timestamp_prefix_re = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+)\s+-\s+\w+\s+-\s+")

    module_stats: dict[str, dict] = {}
    module_order: list[str] = []
    current_module: str | None = None

    def _to_aware(ts_text: str | None):
        if not ts_text:
            return None
        try:
            parsed = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S,%f")
            if timezone.is_naive(parsed):
                return timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed
        except Exception:
            return None

    def _ensure_module(module_name: str) -> None:
        if not module_name:
            return
        if module_name not in module_stats:
            module_stats[module_name] = {
                "rows_fetched": 0,
                "rows_inserted": 0,
                "completed": False,
                "no_data": False,
                "mode": "",
                "had_fallback": False,
                "errors": [],
                "started_at": None,
                "completed_at": None,
            }
            module_order.append(module_name)

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        ts_match = timestamp_prefix_re.match(line)
        line_ts = _to_aware(ts_match.group(1)) if ts_match else None
        # Strip script timestamp prefix so parsing works for both local logs and raw stdout.
        line = timestamp_prefix_re.sub("", line)

        module_match = module_start_re.search(line) or fallback_module_start_re.search(line)
        if module_match:
            current_module = module_match.group(1).strip().rstrip(".")
            _ensure_module(current_module)
            if line_ts and not module_stats[current_module]["started_at"]:
                module_stats[current_module]["started_at"] = line_ts
            continue

        complete_match = module_complete_re.search(line)
        if complete_match:
            module_name = complete_match.group(1).strip()
            mode = complete_match.group(2).upper()
            updates = int(complete_match.group(3).replace(",", ""))
            _ensure_module(module_name)
            module_stats[module_name]["mode"] = mode
            module_stats[module_name]["rows_inserted"] = max(module_stats[module_name]["rows_inserted"], updates)
            module_stats[module_name]["rows_fetched"] = max(module_stats[module_name]["rows_fetched"], updates)
            module_stats[module_name]["completed"] = True
            if line_ts:
                module_stats[module_name]["completed_at"] = line_ts
            current_module = None
            continue

        no_data_match = no_data_re.search(line)
        if no_data_match:
            module_name = no_data_match.group(1).strip()
            _ensure_module(module_name)
            module_stats[module_name]["no_data"] = True
            module_stats[module_name]["completed"] = True
            if line_ts:
                module_stats[module_name]["completed_at"] = line_ts
            current_module = None
            continue

        fallback_match = mode_fallback_re.search(line)
        if fallback_match:
            module_name = fallback_match.group(1).strip()
            _ensure_module(module_name)
            module_stats[module_name]["mode"] = "FULL"
            module_stats[module_name]["had_fallback"] = True
            continue

        if current_module:
            fetched_match = fetched_re.search(line) or total_fetched_re.search(line)
            if fetched_match:
                fetched_rows = int(fetched_match.group(1).replace(",", ""))
                module_stats[current_module]["rows_fetched"] = max(module_stats[current_module]["rows_fetched"], fetched_rows)
                continue

            error_match = fetch_error_re.search(line)
            if error_match:
                error_text = (error_match.group(1) or "").strip() or "Fetch error"
                module_stats[current_module]["errors"].append(error_text)
                if line_ts:
                    module_stats[current_module]["completed_at"] = line_ts
                continue

    # Replace existing telemetry for this execution to avoid duplicate dashboard rows.
    execution.logs.all().delete()

    completed_tables = 0
    total_rows = 0
    now = timezone.now()

    for module_name in module_order:
        if not module_name:
            continue

        stats = module_stats[module_name]
        rows_fetched = int(stats["rows_fetched"] or 0)
        rows_inserted = int(stats["rows_inserted"] or rows_fetched)
        is_completed = bool(stats["completed"])
        errors = stats["errors"]
        started_at = stats["started_at"] or execution.started_at
        completed_at = stats["completed_at"]

        if is_completed:
            status = "completed"
            completed_tables += 1
            total_rows += rows_inserted
            if not completed_at:
                completed_at = execution.completed_at or now
        elif errors:
            status = "failed"
            if not completed_at:
                completed_at = execution.completed_at or now
        else:
            status = "pending"

        notes = []
        if stats["mode"]:
            notes.append(f"Mode: {stats['mode']}")
        if stats["no_data"]:
            notes.append("No data found")
        if stats["had_fallback"]:
            notes.append("Incremental filter fallback to full fetch")
        if errors:
            notes.append(f"Fetch errors: {len(errors)}")

        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name="api",
            table_name=module_name,
            status=status,
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted if is_completed else 0,
            batch_number=1,
            started_at=started_at,
            completed_at=completed_at if status in {"completed", "failed"} else None,
            error_message="\n".join(errors[:5]) if errors and status == "failed" else None,
            verification_summary="; ".join(notes) if notes else None,
        )

    execution.completed_tables = completed_tables
    execution.total_tables = len(module_order)
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
                disk_text = _read_sap_disk_logs(project_root, mode_normalized)
                parse_source = (disk_text + "\n" + stdout).strip()
                _populate_execution_logs_from_stdout(execution, parse_source or stdout)
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
