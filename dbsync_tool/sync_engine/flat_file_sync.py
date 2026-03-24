"""
Flat-file sync runtime executor.
"""
import logging
from typing import Dict, List, Tuple

from django.utils import timezone

from connections.connectors.base import ColumnInfo
from connections.file_source_paths import resolve_safe_source_path
from sync_engine.flat_file_reader import read_csv_in_chunks
from sync_engine.full_sync import get_target_table_name
from sync_engine.exceptions import TableSyncError
from sync_jobs.models import SyncExecutionLog

logger = logging.getLogger(__name__)


class FlatFileSyncExecutor:
    """Execute full-sync style ingestion from CSV file to target database."""

    def __init__(self, job, execution, target_connector):
        self.job = job
        self.execution = execution
        self.target_connector = target_connector

    def _target_db_type(self) -> str:
        class_name = self.target_connector.__class__.__name__.lower()
        if "postgres" in class_name:
            return "postgres"
        if "mysql" in class_name:
            return "mysql"
        if "sqlserver" in class_name:
            return "sqlserver"
        if "clickhouse" in class_name:
            return "clickhouse"
        if "oracle" in class_name:
            return "oracle"
        return "unknown"

    def _target_schema(self, source_schema: str) -> str:
        dbt = self._target_db_type()
        if dbt == "mysql":
            return self.target_connector.database_name
        if dbt == "clickhouse":
            return getattr(self.target_connector, "database_name", None) or source_schema
        if dbt == "postgres":
            return "public"
        if dbt == "sqlserver":
            return "dbo"
        if dbt == "oracle":
            return (getattr(self.target_connector, "username", None) or "").strip().upper() or source_schema
        return source_schema

    def _target_type_for(self) -> str:
        dbt = self._target_db_type()
        if dbt == "oracle":
            return "VARCHAR2(4000)"
        if dbt == "sqlserver":
            return "NVARCHAR(4000)"
        return "TEXT"

    def _build_renamed_columns(self, source_headers: List[str], overrides: Dict[str, str]) -> List[str]:
        renamed = []
        seen = set()
        for src in source_headers:
            key = (src or "").lower()
            tgt = (overrides.get(key) or src or "").strip()
            if not tgt:
                raise TableSyncError(f"Target column mapping missing for source column '{src}'.")
            tgt_lower = tgt.lower()
            if tgt_lower in seen:
                raise TableSyncError(f"Duplicate target column mapping detected: '{tgt}'.")
            seen.add(tgt_lower)
            renamed.append(tgt)
        return renamed

    def execute(self):
        self.execution.status = "running"
        self.execution.started_at = timezone.now()
        self.execution.save()

        if not self.job.source_file_connection:
            raise TableSyncError("Flat-file source connection is missing.")
        if not self.job.source_file_connection.is_active:
            raise TableSyncError("Flat-file source connection is inactive.")

        tables = self.job.tables.filter(is_enabled=True)
        if not tables.exists():
            raise TableSyncError("No enabled tables configured for flat-file job.")
        job_table = tables.first()
        source_schema = job_table.schema_name
        source_table = job_table.table_name
        target_schema = self._target_schema(source_schema)
        target_table = get_target_table_name(self.job, source_table)

        log = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name=source_schema,
            table_name=source_table,
            status="running",
            started_at=timezone.now(),
        )

        total_rows = 0
        batch_number = 0
        try:
            file_source = self.job.source_file_connection
            logger.info("Flat-file sync source validation started for job %s", self.job.id)
            resolved_path = resolve_safe_source_path(file_source.relative_path)
            if not resolved_path.exists() or not resolved_path.is_file():
                raise TableSyncError("File not found under configured source root.")
            logger.info("Flat-file sync read start for job %s", self.job.id)

            headers, chunks, read_stats = read_csv_in_chunks(
                file_path=resolved_path,
                delimiter=file_source.delimiter,
                encoding=file_source.encoding,
                has_header=file_source.has_header,
                chunk_size=1000,
            )
            if not headers:
                raise TableSyncError("Empty file or no readable headers for flat-file sync.")
            if read_stats.get("single_column_warning"):
                logger.warning(
                    "Flat-file sync detected a single parsed column for job %s. "
                    "This can indicate delimiter mismatch (delimiter=%s).",
                    self.job.id,
                    file_source.delimiter,
                )

            self.target_connector.ensure_schema_exists(target_schema)
            overrides = job_table.column_name_overrides or {}
            header_keys = {h.lower() for h in headers}
            unknown_override_keys = [k for k in overrides.keys() if (k or "").lower() not in header_keys]
            if unknown_override_keys:
                raise TableSyncError(
                    "Mapping contract mismatch. Unknown source columns in overrides: "
                    + ", ".join(sorted({k.lower() for k in unknown_override_keys}))
                )
            protected_cols = {
                (c or "").strip().lower()
                for c in (getattr(job_table, "protected_columns", None) or [])
                if c
            }
            excluded_cols = {
                (c or "").strip().lower()
                for c in (getattr(job_table, "excluded_columns", None) or [])
                if c
            }
            effective_headers = [
                h for h in headers
                if h and (h.lower() not in (excluded_cols - protected_cols))
            ]
            if not effective_headers:
                raise TableSyncError("No migratable columns remain after exclusion rules.")

            renamed_columns = self._build_renamed_columns(effective_headers, overrides)
            create_columns = [
                ColumnInfo(name=col, data_type=self._target_type_for(), is_nullable=True)
                for col in renamed_columns
            ]

            try:
                if not self.target_connector.table_exists(target_schema, target_table):
                    self.target_connector.create_table(target_schema, target_table, create_columns)
            except Exception:
                # Defensive fallback: try to create and let connector error explain.
                self.target_connector.create_table(target_schema, target_table, create_columns)

            self.target_connector.truncate_table(target_schema, target_table)

            source_to_target = {src: overrides.get(src.lower(), src) for src in effective_headers}
            for chunk in chunks:
                batch_number += 1
                rows: List[Tuple] = []
                for row in chunk:
                    rows.append(tuple(row.get(src, "") for src in effective_headers))
                self.target_connector.bulk_insert(
                    schema=target_schema,
                    table=target_table,
                    columns=[source_to_target[src] for src in effective_headers],
                    rows=rows,
                )
                total_rows += len(rows)
                logger.info(
                    "Flat-file sync batch progress job=%s batch=%s rows_total=%s",
                    self.job.id,
                    batch_number,
                    total_rows,
                )
                log.batch_number = batch_number
                log.rows_fetched = total_rows
                log.rows_inserted = total_rows
                log.save()

            if total_rows == 0:
                raise TableSyncError("Flat-file contains no data rows to sync.")

            log.status = "completed"
            log.rows_fetched = total_rows
            log.rows_inserted = total_rows
            if read_stats.get("rows_padded") or read_stats.get("rows_truncated"):
                log.verification_summary = (
                    f"CSV row normalization: padded={read_stats.get('rows_padded', 0)}, "
                    f"truncated={read_stats.get('rows_truncated', 0)}"
                )
            excluded_count = len(excluded_cols - protected_cols)
            if excluded_count:
                suffix = f"; excluded_columns={excluded_count}, forced_protected={len(protected_cols & excluded_cols)}"
                log.verification_summary = (log.verification_summary or "Column filtering applied") + suffix
            log.completed_at = timezone.now()
            log.save()

            self.execution.total_rows_synced = total_rows
            self.execution.completed_tables = 1
            self.execution.status = "completed"
            self.execution.completed_at = timezone.now()
            self.execution.save()
            logger.info(
                "Flat-file sync completed job=%s rows=%s batches=%s",
                self.job.id,
                total_rows,
                batch_number,
            )
        except Exception as exc:
            logger.error("Flat-file sync failed for job %s: %s", self.job.id, exc, exc_info=True)
            log.status = "failed"
            log.error_message = str(exc)
            log.completed_at = timezone.now()
            log.save()
            raise

