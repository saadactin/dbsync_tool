"""
Post-migration storage-footprint collector.

Runs AFTER a SyncExecution has reached `completed` status and measures:
- Whole source DB size (or flat-file size) -> SyncExecution.source_database_size_bytes
- Whole target DB size -> SyncExecution.target_database_size_bytes
- Per-table source / target size -> SyncExecutionLog.source_size_bytes / target_size_bytes
- Aggregates per-table sums -> SyncExecution.total_source_bytes / total_target_bytes
- Stamps SyncExecution.size_collected_at

Design contract:
- All failures are caught and logged; sizing must NEVER flip a successful sync to failed.
- Unsupported sources (API) leave source_* fields NULL; target is still measured.
- Works for any connector that implements get_database_size_bytes / get_table_size_bytes;
  for others the per-table / whole-DB numbers remain NULL.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.utils import timezone

from connections.connectors.factory import get_connector
from sync_jobs.models import SyncExecution, SyncExecutionLog, SyncJob

logger = logging.getLogger(__name__)


def _target_db_type_name(target_connector) -> str:
    name = target_connector.__class__.__name__.lower()
    if "postgres" in name:
        return "postgres"
    if "mysql" in name:
        return "mysql"
    if "sqlserver" in name:
        return "sqlserver"
    if "clickhouse" in name:
        return "clickhouse"
    if "oracle" in name:
        return "oracle"
    if "mongo" in name:
        return "mongodb"
    return "unknown"


def _candidate_target_schemas(target_connector, source_schema: str) -> list:
    """
    Produce a small ordered list of plausible target schemas to try when
    measuring per-table sizes. Mirrors the conventions used by
    FlatFileSyncExecutor and FullSyncExecutor.
    """
    candidates: list = []
    dbt = _target_db_type_name(target_connector)
    db_name = getattr(target_connector, "database_name", None)
    username = getattr(target_connector, "username", None)

    if dbt == "postgres":
        candidates += [source_schema, "public"]
    elif dbt == "sqlserver":
        candidates += [source_schema, "dbo"]
    elif dbt in ("mysql", "clickhouse"):
        if db_name:
            candidates.append(db_name)
        candidates.append(source_schema)
    elif dbt == "oracle":
        if username:
            candidates.append(username.upper())
        candidates.append(source_schema.upper() if source_schema else source_schema)
        candidates.append(source_schema)
    elif dbt == "mongodb":
        if db_name:
            candidates.append(db_name)
        candidates.append(source_schema)
    else:
        candidates.append(source_schema)

    # De-duplicate while preserving order; drop falsy.
    seen = set()
    out = []
    for c in candidates:
        if not c:
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _table_prefixed(job: SyncJob, table_name: str) -> str:
    prefix = getattr(job, "target_table_prefix", None)
    if prefix:
        return f"{prefix}_{table_name}"
    return table_name


def _measure_target_table_bytes(
    target_connector, job: SyncJob, source_schema: str, source_table: str
) -> Optional[int]:
    target_table = _table_prefixed(job, source_table)
    for candidate in _candidate_target_schemas(target_connector, source_schema):
        try:
            size = target_connector.get_table_size_bytes(candidate, target_table)
            # Treat zero as unresolved/empty probe and keep trying fallbacks.
            if size is not None and int(size) > 0:
                return int(size)
        except Exception as exc:
            logger.debug(
                "target get_table_size_bytes failed for %s.%s (%s): %s",
                candidate, target_table, target_connector.__class__.__name__, exc,
            )
    return None


def _measure_flat_file_source_bytes(job: SyncJob) -> Optional[int]:
    try:
        from connections.file_source_paths import resolve_safe_source_path
    except Exception as exc:
        logger.warning("resolve_safe_source_path import failed: %s", exc)
        return None
    file_source = getattr(job, "source_file_connection", None)
    if not file_source:
        return None
    try:
        resolved = resolve_safe_source_path(file_source.relative_path)
        if resolved.exists() and resolved.is_file():
            return int(resolved.stat().st_size)
    except Exception as exc:
        logger.warning("Flat-file source size probe failed: %s", exc)
    return None


def _is_api_source(job: SyncJob) -> bool:
    if hasattr(job, "is_api_source") and callable(job.is_api_source):
        try:
            return bool(job.is_api_source())
        except Exception:
            pass
    return getattr(job, "source_connection_type", "") == "api"


def _is_flat_file_source(job: SyncJob) -> bool:
    if hasattr(job, "is_flat_file_source") and callable(job.is_flat_file_source):
        try:
            return bool(job.is_flat_file_source())
        except Exception:
            pass
    return getattr(job, "source_connection_type", "") == "flat_file"


def collect_and_persist_sizes(job: SyncJob, execution: SyncExecution) -> None:
    """
    Measure source and target storage footprint for a completed execution and
    persist results into SyncExecution + its SyncExecutionLog rows.

    This function is intentionally exception-swallowing at the outermost layer:
    any failure is logged and leaves fields NULL so the UI can render a
    "not measured" state.
    """
    source_connector = None
    target_connector = None
    try:
        logs = list(
            SyncExecutionLog.objects.filter(execution=execution).only(
                "id", "schema_name", "table_name", "source_size_bytes", "target_size_bytes"
            )
        )

        # --- Target connector (always a DatabaseConnection) ---
        try:
            if job.target_connection:
                target_connector = get_connector(job.target_connection)
        except Exception as exc:
            logger.warning(
                "Size collector: unable to open target connector for job %s: %s",
                job.id, exc,
            )
            target_connector = None

        # --- Source connector (only for database sources) ---
        if not _is_api_source(job) and not _is_flat_file_source(job):
            try:
                if job.source_connection:
                    source_connector = get_connector(job.source_connection)
            except Exception as exc:
                logger.warning(
                    "Size collector: unable to open source connector for job %s: %s",
                    job.id, exc,
                )
                source_connector = None

        # --- Whole-database size: source ---
        source_db_bytes: Optional[int] = None
        if _is_api_source(job):
            source_db_bytes = None
        elif _is_flat_file_source(job):
            source_db_bytes = _measure_flat_file_source_bytes(job)
        elif source_connector is not None:
            try:
                source_db_bytes = source_connector.get_database_size_bytes()
            except Exception as exc:
                logger.warning("Source DB size probe failed: %s", exc)

        # --- Whole-database size: target ---
        target_db_bytes: Optional[int] = None
        if target_connector is not None:
            try:
                target_db_bytes = target_connector.get_database_size_bytes()
            except Exception as exc:
                logger.warning("Target DB size probe failed: %s", exc)

        # --- Per-table sizing ---
        total_source_per_table = 0
        total_target_per_table = 0
        any_source_measured = False
        any_target_measured = False

        # Cache resolved flat-file size per (schema, table) to avoid re-stat
        flat_file_bytes_cache: Optional[int] = None
        if _is_flat_file_source(job):
            flat_file_bytes_cache = _measure_flat_file_source_bytes(job)

        for log in logs:
            src_bytes: Optional[int] = None
            tgt_bytes: Optional[int] = None

            # Source per-table
            if _is_api_source(job):
                src_bytes = None
            elif _is_flat_file_source(job):
                # Each flat-file job currently maps to a single physical file.
                src_bytes = flat_file_bytes_cache
            elif source_connector is not None:
                try:
                    src_bytes = source_connector.get_table_size_bytes(
                        log.schema_name, log.table_name
                    )
                except Exception as exc:
                    logger.debug(
                        "Source table size probe failed for %s.%s: %s",
                        log.schema_name, log.table_name, exc,
                    )

            # Target per-table
            if target_connector is not None:
                tgt_bytes = _measure_target_table_bytes(
                    target_connector, job, log.schema_name, log.table_name
                )

            update_fields = []
            if src_bytes is not None:
                log.source_size_bytes = int(src_bytes)
                total_source_per_table += int(src_bytes)
                any_source_measured = True
                update_fields.append("source_size_bytes")
            if tgt_bytes is not None:
                log.target_size_bytes = int(tgt_bytes)
                total_target_per_table += int(tgt_bytes)
                any_target_measured = True
                update_fields.append("target_size_bytes")
            if update_fields:
                try:
                    log.save(update_fields=update_fields)
                except Exception as exc:
                    logger.warning(
                        "Failed to persist per-table size for log %s: %s",
                        log.id, exc,
                    )

        # --- Persist execution-level fields ---
        # Keep whole-db probes when available, but make table totals the source
        # of truth for this page's migration-footprint comparison.
        execution.source_database_size_bytes = source_db_bytes
        execution.target_database_size_bytes = target_db_bytes
        execution.total_source_bytes = total_source_per_table if any_source_measured else 0
        execution.total_target_bytes = total_target_per_table if any_target_measured else 0
        execution.size_collected_at = timezone.now()
        execution.save(update_fields=[
            "source_database_size_bytes",
            "target_database_size_bytes",
            "total_source_bytes",
            "total_target_bytes",
            "size_collected_at",
        ])
        logger.info(
            "Storage footprint captured for execution %s "
            "(source_db=%s, target_db=%s, per_table_src=%s, per_table_tgt=%s)",
            execution.id, source_db_bytes, target_db_bytes,
            total_source_per_table, total_target_per_table,
        )
    except Exception as exc:
        logger.warning(
            "collect_and_persist_sizes outer failure for execution %s: %s",
            getattr(execution, "id", None), exc,
        )
    finally:
        for conn in (source_connector, target_connector):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
