"""
Flat-file sync runtime executor.
"""
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta, timezone as dt_timezone

import pandas as pd

from django.utils import timezone

from connections.connectors.base import ColumnInfo
from connections.file_source_paths import resolve_safe_source_path
from sync_engine.checkpoint_manager import CheckpointManager
from sync_engine.timezone_utils import TimezoneHandler
from sync_engine.file_parsers import iter_records
from sync_engine.flat_file_hashing import (
    compute_file_hash,
    compute_row_hash,
    normalize_hash_columns,
)
from sync_engine.full_sync import get_target_table_name
from sync_engine.exceptions import TableSyncError
from sync_engine.reliability import (
    DeadLetterCollector,
    DeadLetterRowError,
    RetryPolicy,
    classify_error,
    is_dead_letter,
    with_policy,
)
from sync_jobs.models import FlatFileIngestionControl, SyncExecutionLog

logger = logging.getLogger(__name__)


class FlatFileSyncExecutor:
    """Execute flat-file ingestion for full and incremental modes."""

    def __init__(self, job, execution, target_connector):
        self.job = job
        self.execution = execution
        self.target_connector = target_connector
        self._dq_pre_pack_by_table = {}

    def _dq_flat_run_pre(
        self,
        job_table,
        *,
        source_schema: str,
        source_table: str,
        pk_columns,
        incremental_column: Optional[str],
    ) -> None:
        try:
            from sync_engine.dq import compute_pre_pack, persist_dq_packs

            pre = compute_pre_pack(
                execution=self.execution,
                job=self.job,
                job_table=job_table,
                source_connector=self.target_connector,
                source_schema=source_schema,
                source_table=source_table,
                sync_mode="flat_file",
                schema_drift_added_columns=None,
                incremental_column=incremental_column,
                pk_columns=pk_columns or [],
                flat_file_skip_source_metrics=True,
                flat_file_skip_reason="flat_file_pre_scan_disabled",
            )
            self._dq_pre_pack_by_table[(source_schema, source_table)] = pre
            persist_dq_packs(
                execution=self.execution,
                job=self.job,
                job_table=job_table,
                source_schema=source_schema,
                source_table=source_table,
                pre_pack=pre,
                post_pack=None,
                parity_result=None,
            )
        except Exception:
            logger.exception(
                "DQ pre-pack wiring failed for flat-file %s.%s",
                source_schema,
                source_table,
            )

    def _dq_flat_run_post(
        self,
        job_table,
        *,
        source_schema: str,
        source_table: str,
        target_schema: str,
        target_table: str,
        dl_collector,
        log,
        tgt_pk_columns,
        sync_mode_ff: str,
    ) -> None:
        try:
            from sync_engine.dq import compute_post_pack, persist_dq_packs

            pre = self._dq_pre_pack_by_table.get((source_schema, source_table))
            post = compute_post_pack(
                execution=self.execution,
                job=self.job,
                job_table=job_table,
                source_connector=self.target_connector,
                target_connector=self.target_connector,
                source_schema=source_schema,
                source_table=source_table,
                target_schema=target_schema,
                target_table=target_table,
                sync_mode=sync_mode_ff,
                parity_result=None,
                dead_letter_count=dl_collector.stats.dead_letter_count,
                attempts=getattr(log, "attempts", 0) or 0,
                last_error_code=getattr(log, "last_error_code", None),
                pk_columns=tgt_pk_columns or [],
                numeric_columns=None,
                schema_drift_added_columns=None,
                no_delete_propagation=getattr(self.job, "no_delete_propagation", True),
                flat_file=True,
            )
            persist_dq_packs(
                execution=self.execution,
                job=self.job,
                job_table=job_table,
                source_schema=source_schema,
                source_table=source_table,
                pre_pack=pre,
                post_pack=post,
                parity_result=None,
            )
        except Exception:
            logger.exception(
                "DQ post-pack wiring failed for flat-file %s.%s",
                source_schema,
                source_table,
            )

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

    def _resolve_effective_key_columns(self, job_table, effective_headers: List[str]) -> List[str]:
        """Resolve source-side key columns with precedence: incremental_key_columns -> protected_columns."""
        configured = getattr(job_table, "incremental_key_columns", None) or []
        protected = getattr(job_table, "protected_columns", None) or []
        if not isinstance(configured, (list, tuple)):
            configured = []
        if not isinstance(protected, (list, tuple)):
            protected = []

        preferred = configured if configured else protected
        normalized = [str(k).strip() for k in preferred if str(k).strip()]
        if not normalized:
            raise TableSyncError(
                "Flat-file incremental requires at least one stable upsert key column "
                "(incremental_key_columns or protected columns)."
            )

        header_by_lower = {h.lower(): h for h in effective_headers if h}
        resolved = []
        for k in normalized:
            hl = header_by_lower.get(k.lower())
            if hl:
                resolved.append(hl)

        if not resolved:
            raise TableSyncError(
                "Flat-file incremental key columns do not match available CSV headers after exclusion rules."
            )
        return resolved

    def _get_file_mtime_utc(self, resolved_path) -> datetime:
        ts = resolved_path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=dt_timezone.utc)

    def _parse_checkpoint_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        parsed = TimezoneHandler.parse_checkpoint_value(value, "timestamp")
        if isinstance(parsed, datetime):
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt_timezone.utc)
            return parsed.astimezone(dt_timezone.utc)
        if isinstance(parsed, str):
            try:
                normalized = TimezoneHandler.normalize_to_utc(parsed)
                return normalized.astimezone(dt_timezone.utc)
            except Exception:
                return None
        return None

    def _quote_ident(self, name: str) -> str:
        dbt = self._target_db_type()
        if dbt in {"postgres", "oracle"}:
            return f'"{name}"'
        if dbt in {"mysql", "clickhouse"}:
            return f"`{name}`"
        if dbt == "sqlserver":
            return f"[{name}]"
        return name

    def _table_ref(self, schema: str, table: str) -> str:
        dbt = self._target_db_type()
        if dbt == "sqlserver":
            return f"[{schema}].[{table}]"
        if dbt in {"mysql", "clickhouse"}:
            return f"`{schema}`.`{table}`"
        if dbt in {"postgres", "oracle"}:
            return f'"{schema}"."{table}"'
        return f"{schema}.{table}"

    def _fetch_all_rows(self, query: str) -> List[Tuple]:
        rows: List[Tuple] = []
        offset = 0
        batch_size = 5000
        while True:
            batch = self.target_connector.fetch_batch(query=query, batch_size=batch_size, offset=offset)
            if not batch:
                break
            rows.extend(batch)
            offset += len(batch)
            if len(batch) < batch_size:
                break
        return rows

    def _fetch_existing_hash_by_key(
        self,
        *,
        schema: str,
        table: str,
        key_column: str,
        row_hash_column: str,
        key_values: List,
    ) -> Dict[str, str]:
        if not key_values:
            return {}
        out: Dict[str, str] = {}
        chunk_size = 1000
        key_id = self._quote_ident(key_column)
        hash_id = self._quote_ident(row_hash_column)
        table_ref = self._table_ref(schema, table)

        for i in range(0, len(key_values), chunk_size):
            chunk = key_values[i : i + chunk_size]
            literals: List[str] = []
            for value in chunk:
                if value is None:
                    continue
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    literals.append(str(value))
                else:
                    sval = str(value).replace("'", "''")
                    literals.append(f"'{sval}'")
            if not literals:
                continue
            query = f"SELECT {key_id}, {hash_id} FROM {table_ref} WHERE {key_id} IN ({', '.join(literals)})"
            for row in self._fetch_all_rows(query):
                if len(row) < 2:
                    continue
                out[str(row[0])] = str(row[1] or "")
        return out

    def _fetch_existing_hash_set(
        self,
        *,
        schema: str,
        table: str,
        row_hash_column: str,
        hash_values: List[str],
    ) -> set:
        if not hash_values:
            return set()
        existing = set()
        chunk_size = 1000
        hash_id = self._quote_ident(row_hash_column)
        table_ref = self._table_ref(schema, table)
        for i in range(0, len(hash_values), chunk_size):
            chunk = [h for h in hash_values[i : i + chunk_size] if h]
            if not chunk:
                continue
            literals = []
            for h in chunk:
                escaped = str(h).replace("'", "''")
                literals.append(f"'{escaped}'")
            query = f"SELECT {hash_id} FROM {table_ref} WHERE {hash_id} IN ({', '.join(literals)})"
            for row in self._fetch_all_rows(query):
                if not row:
                    continue
                existing.add(str(row[0]))
        return existing

    def _upsert_control_record(
        self,
        *,
        job_table,
        file_name: str,
        file_hash: str,
        file_size_bytes: int,
        file_mtime_utc: datetime,
        rows_read: int,
        rows_inserted: int,
        rows_updated: int,
        rows_skipped: int,
        status: str,
        error_message: Optional[str] = None,
    ):
        FlatFileIngestionControl.objects.update_or_create(
            job=self.job,
            schema_name=job_table.schema_name,
            table_name=job_table.table_name,
            file_name=file_name,
            file_hash=file_hash,
            defaults={
                "file_size_bytes": int(file_size_bytes or 0),
                "file_mtime_utc": file_mtime_utc,
                "rows_read": int(rows_read or 0),
                "rows_inserted": int(rows_inserted or 0),
                "rows_updated": int(rows_updated or 0),
                "rows_skipped": int(rows_skipped or 0),
                "status": status,
                "error_message": (error_message or "")[:5000] if error_message else None,
            },
        )

    def execute(self) -> None:
        """Public entry point - runs the table body under the RetryPolicy.

        Day-3: a flat-file job processes a single enabled table per
        execution. We source the policy from ``tables.first().retry_policy``
        and wrap :meth:`_execute_table_body` with :func:`with_policy`.
        Transient I/O errors against a flaky source share trigger up to
        ``policy.max_retries`` retries with bounded exponential backoff.

        Existing callers (``SyncExecutor``) keep using
        ``executor.execute()`` and observe no API change. On terminal
        failure the last error code is recorded on the ``SyncExecutionLog``
        row created inside ``_execute_table_body``.
        """
        try:
            job_table = self.job.tables.filter(is_enabled=True).first()
        except Exception:
            job_table = None

        policy = (
            RetryPolicy.from_job_table(job_table)
            if job_table is not None
            else RetryPolicy.default()
        )

        schema_name = getattr(job_table, "schema_name", None)
        table_name = getattr(job_table, "table_name", None)

        def _on_attempt(attempt_number: int, last_error_code: Optional[str]) -> None:
            if attempt_number < 2 or not (schema_name and table_name):
                return
            try:
                SyncExecutionLog.objects.filter(
                    execution=self.execution,
                    schema_name=schema_name,
                    table_name=table_name,
                ).update(
                    attempts=attempt_number - 1,
                    last_error_code=last_error_code,
                )
            except Exception:
                logger.exception(
                    "Failed to bump SyncExecutionLog.attempts for flat-file %s.%s",
                    schema_name,
                    table_name,
                )

        try:
            with_policy(self._execute_table_body, policy, on_attempt=_on_attempt)
        except Exception as exc:
            if schema_name and table_name:
                try:
                    _, code = classify_error(exc)
                    SyncExecutionLog.objects.filter(
                        execution=self.execution,
                        schema_name=schema_name,
                        table_name=table_name,
                    ).update(last_error_code=code)
                except Exception:
                    logger.exception(
                        "Failed to record terminal last_error_code for flat-file %s.%s",
                        schema_name,
                        table_name,
                    )
            raise

    def _execute_table_body(self):
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

        # Day-3 reliability: with_policy may retry the table body. Reuse
        # the existing log row across retries instead of creating a
        # duplicate per attempt.
        log, _log_created = SyncExecutionLog.objects.get_or_create(
            execution=self.execution,
            schema_name=source_schema,
            table_name=source_table,
            defaults={
                "status": "running",
                "started_at": timezone.now(),
            },
        )

        total_rows = 0
        rows_changed = 0
        rows_updated = 0
        rows_skipped = 0
        batch_number = 0
        control_meta = None
        mode = "legacy_mtime"
        is_incremental = False
        try:
            file_source = self.job.source_file_connection
            logger.info("Flat-file sync source validation started for job %s", self.job.id)
            resolved_path = resolve_safe_source_path(file_source.relative_path)
            if not resolved_path.exists() or not resolved_path.is_file():
                raise TableSyncError("File not found under configured source root.")
            logger.info("Flat-file sync read start for job %s", self.job.id)

            is_incremental = (getattr(self.job, "sync_type", "full") == "incremental")
            mode = (
                (getattr(job_table, "flat_file_incremental_mode", None) or "legacy_mtime")
                if is_incremental
                else "legacy_mtime"
            )
            is_hybrid_mode = (mode == "hybrid_hash_control")
            hash_algorithm = (getattr(job_table, "flat_file_hash_algorithm", None) or "sha256").strip().lower()
            allow_hash_only_without_key = False
            file_mtime_dt = self._get_file_mtime_utc(resolved_path)
            file_name = str(file_source.relative_path or resolved_path.name)
            file_hash = None
            if is_hybrid_mode:
                try:
                    file_hash = compute_file_hash(resolved_path, algorithm=hash_algorithm)
                except Exception as exc:
                    raise TableSyncError(f"Failed to compute file hash for hybrid mode: {exc}") from exc
                control_meta = {
                    "file_name": file_name,
                    "file_hash": file_hash,
                    "file_size_bytes": int(resolved_path.stat().st_size),
                    "file_mtime_utc": file_mtime_dt,
                }
                if FlatFileIngestionControl.objects.filter(
                    job=self.job,
                    schema_name=source_schema,
                    table_name=source_table,
                    file_name=file_name,
                    file_hash=file_hash,
                    status="success",
                ).exists():
                    checkpoint_decision = (
                        "Flat-file hybrid incremental skipped by control table "
                        f"(file_name={file_name}, file_hash={file_hash})"
                    )
                    logger.info(checkpoint_decision)
                    log.status = "completed"
                    log.rows_fetched = 0
                    log.rows_inserted = 0
                    log.verification_summary = checkpoint_decision
                    log.completed_at = timezone.now()
                    log.save()
                    self.execution.total_rows_synced = 0
                    self.execution.completed_tables = 1
                    self.execution.status = "completed"
                    self.execution.completed_at = timezone.now()
                    self.execution.save()
                    return

            headers, chunks, read_stats = iter_records(
                file_source,
                chunk_size=1000,
                encoding=file_source.encoding,
            )
            if not headers:
                raise TableSyncError("Empty file or no readable headers for flat-file sync.")
            if read_stats.get("single_column_warning"):
                logger.warning(
                    "Flat-file sync detected a single parsed column for job %s. "
                    "This can indicate parser configuration mismatch (format=%s, delimiter=%s).",
                    self.job.id,
                    getattr(file_source, "file_format", "csv"),
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

            source_to_target = {src: overrides.get(src.lower(), src) for src in effective_headers}
            checkpoint_manager = CheckpointManager(self.job)
            checkpoint_decision = None
            hash_columns = normalize_hash_columns(
                effective_headers,
                getattr(job_table, "flat_file_hash_columns", None),
            )
            if is_hybrid_mode and not hash_columns:
                raise TableSyncError(
                    "Flat-file hybrid incremental hash_columns resolved to empty set."
                )
            row_hash_col = "row_hash"

            pk_ff_src: List[str] = []
            if is_incremental:
                pk_ff_src = self._resolve_effective_key_columns(job_table, effective_headers)

            self._dq_flat_run_pre(
                job_table,
                source_schema=source_schema,
                source_table=source_table,
                pk_columns=pk_ff_src,
                incremental_column=getattr(job_table, "incremental_column", None),
            )

            connector_key_target = None

            if not is_incremental:
                # Preserve full-sync behavior exactly: replace table contents.
                self.target_connector.truncate_table(target_schema, target_table)
            else:
                # Incremental mode contract for flat-file: no delete propagation.
                if not getattr(self.job, "no_delete_propagation", True):
                    raise TableSyncError(
                        "Flat-file incremental requires no-delete propagation policy to be enabled."
                    )

                effective_keys = pk_ff_src
                connector_key_source = effective_keys[0] if effective_keys else None
                connector_key_target = (
                    source_to_target.get(connector_key_source, connector_key_source)
                    if connector_key_source
                    else None
                )

                prev_raw = checkpoint_manager.get_checkpoint_value(source_schema, source_table)
                prev_dt = self._parse_checkpoint_datetime(prev_raw)
                overlap_seconds = int(getattr(self.job, "incremental_overlap_seconds", 120) or 0)
                lower_bound = None
                if prev_dt is not None and overlap_seconds > 0:
                    lower_bound = prev_dt - timedelta(seconds=overlap_seconds)

                if lower_bound is not None and file_mtime_dt <= lower_bound:
                    checkpoint_decision = (
                        f"Flat-file incremental skipped by file watermark; file_mtime={file_mtime_dt.isoformat()}; "
                        f"prev_checkpoint={prev_dt.isoformat()}; lower_bound={lower_bound.isoformat()}"
                    )
                    logger.info(checkpoint_decision)
                    log.status = "completed"
                    log.rows_fetched = 0
                    log.rows_inserted = 0
                    log.verification_summary = checkpoint_decision
                    log.completed_at = timezone.now()
                    log.save()

                    self.execution.total_rows_synced = 0
                    self.execution.completed_tables = 1
                    self.execution.status = "completed"
                    self.execution.completed_at = timezone.now()
                    self.execution.save()
                    return

            # Day-4 reliability: per-table dead-letter capture for the
            # flat-file path. Row-scope parse / write errors raised as
            # ``DeadLetterRowError`` (or tagged with ``dead_letter=True``)
            # are isolated and bounded by the
            # ``SyncJobTable.dead_letter_max_pct`` budget. Structural
            # file errors (missing file, unreadable, bad header) still
            # raise as fatal because they have no row context.
            dl_collector = DeadLetterCollector(
                execution=self.execution,
                job=self.job,
                job_table=job_table,
            )

            for chunk in chunks:
                batch_number += 1
                rows: List[Tuple] = []
                sample_chunk_row = chunk[0] if chunk else None
                for row in chunk:
                    rows.append(tuple(row.get(src, "") for src in effective_headers))
                # Day-4: account for every row the parser yielded into
                # this chunk before attempting the target write.
                dl_collector.mark_seen(len(rows))
                target_columns = [source_to_target[src] for src in effective_headers]
                # Day-4: wrap target writes so a row-scope failure
                # (DeadLetterRowError or any tagged exception) is
                # captured into the dead-letter buffer and the budget
                # decides whether to continue or fail the table.
                try:
                    if is_incremental:
                        df = pd.DataFrame(rows, columns=target_columns)
                        if is_hybrid_mode:
                            source_df = pd.DataFrame(rows, columns=effective_headers)
                            source_df[row_hash_col] = source_df.apply(
                                lambda r: compute_row_hash(
                                    r.to_dict(),
                                    columns=hash_columns,
                                    algorithm=hash_algorithm,
                                ),
                                axis=1,
                            )
                            df[row_hash_col] = source_df[row_hash_col]
                            if callable(getattr(self.target_connector, "add_missing_columns", None)):
                                self.target_connector.add_missing_columns(
                                    target_schema,
                                    target_table,
                                    df[[row_hash_col]],
                                )

                            if connector_key_target:
                                if connector_key_target not in df.columns:
                                    raise TableSyncError(
                                        f"Flat-file incremental key column '{connector_key_target}' not present in batch."
                                    )
                                if df[connector_key_target].isna().any():
                                    raise TableSyncError(
                                        f"Flat-file incremental key column '{connector_key_target}' contains NULL/NaN values."
                                    )
                                existing_by_key = self._fetch_existing_hash_by_key(
                                    schema=target_schema,
                                    table=target_table,
                                    key_column=connector_key_target,
                                    row_hash_column=row_hash_col,
                                    key_values=df[connector_key_target].tolist(),
                                )
                                changed_mask = []
                                for _, row in df.iterrows():
                                    k = str(row.get(connector_key_target))
                                    new_hash = str(row.get(row_hash_col) or "")
                                    old_hash = existing_by_key.get(k)
                                    if old_hash is None:
                                        changed_mask.append(True)
                                    elif old_hash != new_hash:
                                        changed_mask.append(True)
                                        rows_updated += 1
                                    else:
                                        changed_mask.append(False)
                                        rows_skipped += 1
                                changed_df = df[changed_mask]
                                if not changed_df.empty:
                                    self.target_connector.upsert_dataframe(
                                        schema=target_schema,
                                        table=target_table,
                                        df=changed_df,
                                        key_column=connector_key_target,
                                    )
                                    rows_changed += len(changed_df)
                            else:
                                raise TableSyncError(
                                    "Flat-file hybrid incremental requires key columns (mark at least one Protected column)."
                                )
                        else:
                            if connector_key_target not in df.columns:
                                raise TableSyncError(
                                    f"Flat-file incremental key column '{connector_key_target}' not present in batch."
                                )
                            if df[connector_key_target].isna().any():
                                raise TableSyncError(
                                    f"Flat-file incremental key column '{connector_key_target}' contains NULL/NaN values."
                                )
                            self.target_connector.upsert_dataframe(
                                schema=target_schema,
                                table=target_table,
                                df=df,
                                key_column=connector_key_target,
                            )
                            rows_changed += len(df)
                    else:
                        self.target_connector.bulk_insert(
                            schema=target_schema,
                            table=target_table,
                            columns=target_columns,
                            rows=rows,
                        )
                except Exception as chunk_err:
                    if is_dead_letter(chunk_err):
                        dl_collector.record(
                            row=getattr(chunk_err, "row", None) or sample_chunk_row,
                            error=chunk_err,
                            batch_number=batch_number,
                        )
                        dl_collector.flush()
                        dl_collector.update_log_counters()
                        if dl_collector.should_fail():
                            dl_collector.raise_if_budget_exceeded()
                        continue
                    raise
                total_rows += len(rows)
                logger.info(
                    "Flat-file sync batch progress job=%s batch=%s rows_total=%s",
                    self.job.id,
                    batch_number,
                    total_rows,
                )
                log.batch_number = batch_number
                log.rows_fetched = total_rows
                log.rows_inserted = rows_changed if is_incremental else total_rows
                log.save()

            if total_rows == 0 and not is_incremental:
                raise TableSyncError("Flat-file contains no data rows to sync.")

            tgt_pk_ff: List[str] = []
            if is_incremental and connector_key_target:
                tgt_pk_ff = [connector_key_target]
            elif renamed_columns:
                tgt_pk_ff = [renamed_columns[0]]

            self._dq_flat_run_post(
                job_table,
                source_schema=source_schema,
                source_table=source_table,
                target_schema=target_schema,
                target_table=target_table,
                dl_collector=dl_collector,
                log=log,
                tgt_pk_columns=tgt_pk_ff,
                sync_mode_ff="flat_file",
            )

            if is_incremental:
                prev_raw = checkpoint_manager.get_checkpoint_value(source_schema, source_table)
                prev_dt = self._parse_checkpoint_datetime(prev_raw)
                candidate = self._get_file_mtime_utc(resolved_path)
                did_advance = prev_dt is None or candidate > prev_dt
                checkpoint_manager.maybe_advance_checkpoint(
                    schema_name=source_schema,
                    table_name=source_table,
                    did_advance=did_advance,
                    value=candidate,
                )
                checkpoint_decision = (
                    f"Flat-file incremental watermark candidate={candidate.isoformat()}; "
                    f"previous={prev_dt.isoformat() if prev_dt else 'none'}; "
                    f"decision={'advance' if did_advance else 'skip_not_greater'}"
                )

            # Day-4: persist any buffered dead-letter rows + sync the
            # ``dead_letter_count`` on the log row so it matches the
            # number of ``SyncDeadLetterRow`` records for this table.
            try:
                dl_collector.flush()
                dl_collector.update_log_counters()
            except Exception:
                logger.exception(
                    "Dead-letter flush failed for flat-file %s.%s.",
                    source_schema,
                    source_table,
                )

            log.status = "completed"
            log.rows_fetched = total_rows
            log.rows_inserted = rows_changed if is_incremental else total_rows
            log.dead_letter_count = dl_collector.stats.dead_letter_count
            if read_stats.get("rows_padded") or read_stats.get("rows_truncated"):
                log.verification_summary = (
                    f"CSV row normalization: padded={read_stats.get('rows_padded', 0)}, "
                    f"truncated={read_stats.get('rows_truncated', 0)}"
                )
            excluded_count = len(excluded_cols - protected_cols)
            if excluded_count:
                suffix = f"; excluded_columns={excluded_count}, forced_protected={len(protected_cols & excluded_cols)}"
                log.verification_summary = (log.verification_summary or "Column filtering applied") + suffix
            if checkpoint_decision:
                log.verification_summary = (
                    f"{log.verification_summary}; {checkpoint_decision}"
                    if log.verification_summary
                    else checkpoint_decision
                )
            if is_hybrid_mode:
                hybrid_summary = (
                    f"Hybrid mode={mode}, hash_algorithm={hash_algorithm}, "
                    f"rows_changed={rows_changed}, rows_updated={rows_updated}, rows_skipped={rows_skipped}"
                )
                log.verification_summary = (
                    f"{log.verification_summary}; {hybrid_summary}"
                    if log.verification_summary
                    else hybrid_summary
                )
            log.completed_at = timezone.now()
            log.save()

            self.execution.total_rows_synced = rows_changed if is_incremental else total_rows
            self.execution.completed_tables = 1
            self.execution.status = "completed"
            self.execution.completed_at = timezone.now()
            self.execution.save()
            if is_hybrid_mode and control_meta:
                self._upsert_control_record(
                    job_table=job_table,
                    file_name=control_meta["file_name"],
                    file_hash=control_meta["file_hash"],
                    file_size_bytes=control_meta["file_size_bytes"],
                    file_mtime_utc=control_meta["file_mtime_utc"],
                    rows_read=total_rows,
                    rows_inserted=rows_changed,
                    rows_updated=rows_updated,
                    rows_skipped=rows_skipped,
                    status="success",
                )
            logger.info(
                "Flat-file sync completed job=%s rows=%s batches=%s",
                self.job.id,
                total_rows,
                batch_number,
            )
        except Exception as exc:
            logger.error("Flat-file sync failed for job %s: %s", self.job.id, exc, exc_info=True)
            # Day-4: drain dead-letter buffer + counters in error path.
            try:
                if "dl_collector" in locals():
                    dl_collector.flush()
                    dl_collector.update_log_counters()
            except Exception:
                logger.exception(
                    "Dead-letter flush failed in error path for flat-file %s.%s.",
                    source_schema,
                    source_table,
                )
            log.status = "failed"
            log.error_message = str(exc)
            log.completed_at = timezone.now()
            if "dl_collector" in locals():
                log.dead_letter_count = dl_collector.stats.dead_letter_count
                try:
                    _, _code = classify_error(exc)
                    log.last_error_code = _code
                except Exception:
                    pass
            log.save()
            try:
                if control_meta and is_incremental and mode == "hybrid_hash_control":
                    self._upsert_control_record(
                        job_table=job_table,
                        file_name=control_meta["file_name"],
                        file_hash=control_meta["file_hash"],
                        file_size_bytes=control_meta["file_size_bytes"],
                        file_mtime_utc=control_meta["file_mtime_utc"],
                        rows_read=total_rows,
                        rows_inserted=rows_changed,
                        rows_updated=rows_updated,
                        rows_skipped=rows_skipped,
                        status="failed",
                        error_message=str(exc),
                    )
            except Exception:
                logger.debug("Failed to persist flat-file control failure record", exc_info=True)
            raise

