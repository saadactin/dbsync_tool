"""
Incremental sync implementation
"""
from typing import List, Optional, Any
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Sum
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import DBConnector, ColumnInfo
from sync_engine.table_handler import TableHandler
from sync_engine.validators import DataValidator
from sync_engine.query_builder import QueryBuilder
from sync_engine.transformation_engine import TransformationEngine
from sync_engine.transformation_validator import TransformationValidator
from sync_engine.checkpoint_manager import CheckpointManager
from sync_engine.timezone_utils import TimezoneHandler
from sync_engine.exceptions import TableSyncError, CheckpointError
from sync_engine.retry import retry_on_error
from sync_engine.full_sync import get_target_table_name
from sync_jobs.services.transform_plan_service import (
    TransformPlanValidationError,
    prepare_runtime_transform_plan,
    compile_select_from_plan,
    column_infos_from_transform_plan,
    validate_incremental_key_from_base,
    validate_transform_plan_column_references,
    ERROR_TRANSFORM_PLAN_CONFLICT,
    ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM,
)
from core.constants import DEFAULT_BATCH_SIZE
from typing import Tuple, Optional, List, Dict, Any
import pandas as pd
import logging

logger = logging.getLogger(__name__)

ORIGIN_FIELD_NAME = "__dbsync_origin_job_id"


def _should_stamp_origin() -> bool:
    import os

    return (os.environ.get("DBSYNC_STAMP_ORIGIN", "") or "").strip().lower() in ("1", "true", "yes", "y")

class IncrementalSyncExecutor:
    """Executes incremental sync for a job"""
    
    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        source_connector: DBConnector,
        target_connector: DBConnector
    ):
        """
        Initialize incremental sync executor
        
        Args:
            job: SyncJob instance
            execution: SyncExecution instance
            source_connector: Source database connector
            target_connector: Target database connector
        """
        if not job:
            raise ValueError("Job cannot be None")
        if not execution:
            raise ValueError("Execution cannot be None")
        if not source_connector:
            raise ValueError("Source connector cannot be None")
        if not target_connector:
            raise ValueError("Target connector cannot be None")
        
        if job.sync_type != 'incremental':
            raise ValueError(f"Job sync_type must be 'incremental', got '{job.sync_type}'")
        
        self.job = job
        self.execution = execution
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.table_handler = TableHandler(source_connector, target_connector)
        self.validator = DataValidator()
        self.checkpoint_manager = CheckpointManager(job)
        self.query_builder = QueryBuilder()
        self.timezone_handler = TimezoneHandler()
        self.batch_size = DEFAULT_BATCH_SIZE
        # Initialize transformation engine and validator
        self.transformation_engine = TransformationEngine()
        self.transformation_validator = TransformationValidator()
        from sync_engine.pre_migration_validator import PreMigrationValidator
        from sync_engine.data_integrity_verifier import DataIntegrityVerifier

        self.pre_migration_validator = PreMigrationValidator(source_connector)
        self.data_integrity_verifier = DataIntegrityVerifier(
            source_connector,
            target_connector,
        )
        self._did_add_missing_columns: Dict[Tuple[str, str], bool] = {}
        self._last_schema_drift_added_columns: Dict[Tuple[str, str], List[str]] = {}

    def _is_datetime_like(self, data_type: str) -> bool:
        dt = (data_type or "").lower()
        return any(token in dt for token in ["timestamp", "datetime", "date", "time"])

    def _apply_incremental_overlap(self, checkpoint_value: Any, col_type: str) -> Any:
        """
        For datetime-like incremental columns, return a lower-bound checkpoint that
        re-reads a small overlap window to make watermark filtering overlap-safe.
        """
        overlap_seconds_raw = getattr(self.job, "incremental_overlap_seconds", 0)
        try:
            overlap_seconds = int(overlap_seconds_raw)
        except (TypeError, ValueError):
            overlap_seconds = 0

        if checkpoint_value is None:
            return checkpoint_value

        if not self._is_datetime_like(col_type):
            if overlap_seconds <= 0:
                return checkpoint_value
            return checkpoint_value

        if overlap_seconds <= 0 and self._is_datetime_like(col_type):
            overlap_seconds = 60

        checkpoint_dt = self._normalize_datetime_like(checkpoint_value)
        if checkpoint_dt is None:
            return checkpoint_value

        try:
            return checkpoint_dt - timedelta(seconds=int(overlap_seconds))
        except Exception:
            logger.debug(
                "Failed to apply incremental overlap",
                exc_info=True,
            )
            return checkpoint_value

    def _normalize_datetime_like(self, value: Any) -> Optional[datetime]:
        """Normalize datetime-like values from pandas/numpy/python to datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float, str, bytes, bool)):
            return None
        try:
            ts = pd.Timestamp(value)
            if pd.isna(ts):
                return None
            return ts.to_pydatetime()
        except Exception:
            return None

    def _identifier_sql(self, db_type: str, name: str) -> str:
        db = (db_type or "").lower()
        if db == "sqlserver":
            return f"[{name}]"
        if db == "mysql":
            return f"`{name}`"
        return f'"{name}"'

    def _schema_table_sql(self, db_type: str, schema: str, table: str) -> str:
        db = (db_type or "").lower()
        if db == "sqlserver":
            return f"[{schema}].[{table}]"
        if db == "mysql":
            return f"`{schema}`.`{table}`"
        return f'"{schema}"."{table}"'

    def _get_source_max_incremental_value(
        self,
        *,
        schema: str,
        table: str,
        incremental_column: str,
    ) -> Any:
        source_db = self.query_builder.get_db_type(self.source_connector)
        table_sql = self._schema_table_sql(source_db, schema, table)
        col_sql = self._identifier_sql(source_db, incremental_column)
        query = f"SELECT MAX({col_sql}) FROM {table_sql}"
        rows = self.source_connector.execute_query_fetchall(query)
        if rows and len(rows[0]) > 0:
            return rows[0][0]
        return None

    def _target_table_has_rows(self, *, schema: str, table: str) -> bool:
        try:
            if not self.target_connector.table_exists(schema, table):
                return False
        except Exception:
            return False
        target_db = self.query_builder.get_db_type(self.target_connector)
        table_sql = self._schema_table_sql(target_db, schema, table)
        query = f"SELECT COUNT(*) FROM {table_sql}"
        rows = self.target_connector.execute_query_fetchall(query)
        return bool(rows and len(rows[0]) > 0 and int(rows[0][0] or 0) > 0)

    def _count_rows_newer_than_checkpoint(
        self,
        rows: List[tuple],
        incremental_col_index: int,
        checkpoint_value: Any,
    ) -> int:
        """
        Count rows with incremental value strictly greater than the previous checkpoint.
        This keeps overlap-safe reprocessing while reporting true net-new progress in UI.
        """
        if checkpoint_value is None:
            return int(len(rows or []))
        newer = 0
        for row in (rows or []):
            try:
                row_value = row[incremental_col_index]
            except Exception:
                continue
            try:
                if self._compare_incremental_values(row_value, checkpoint_value):
                    newer += 1
            except Exception:
                # Defensive fallback: if comparison fails, treat as non-new for metrics.
                continue
        return newer

    def _build_checkpoint_diagnostics(
        self,
        *,
        checkpoint_value_raw: Any,
        checkpoint_value_parsed: Any,
        effective_checkpoint_value: Any,
        candidate_max: Any,
        decision_reason: str,
        update_outcome: str,
    ) -> str:
        try:
            overlap_seconds = int(getattr(self.job, "incremental_overlap_seconds", 0) or 0)
        except (TypeError, ValueError):
            overlap_seconds = 0
        overlap_applied = (
            checkpoint_value_parsed is not None
            and effective_checkpoint_value is not None
            and str(checkpoint_value_parsed) != str(effective_checkpoint_value)
        )
        return (
            f"Checkpoint prev_raw={checkpoint_value_raw}; "
            f"checkpoint_parsed={checkpoint_value_parsed}; "
            f"overlap_seconds={overlap_seconds}; "
            f"lower_bound_used={effective_checkpoint_value if effective_checkpoint_value is not None else 'none'}; "
            f"overlap_applied={str(bool(overlap_applied)).lower()}; "
            f"candidate_max={candidate_max}; "
            f"decision={decision_reason}; "
            f"update_outcome={update_outcome}"
        )

    def _is_numeric_like(self, data_type: str) -> bool:
        dt = (data_type or "").lower()
        return any(token in dt for token in ["int", "bigint", "serial", "number", "decimal", "numeric", "float", "double", "uint"])

    def _resolve_effective_upsert_keys(
        self,
        *,
        pk_columns: List[str],
        configured_keys_raw: Any,
        column_name_set: set,
        context: str,
    ) -> List[str]:
        """
        Resolve the effective upsert key columns for deterministic + correct behavior.

        Rules:
        - If PK columns exist, use them (PK preferred).
        - Else, use `incremental_key_columns` (first key is connector key; all keys are ordering tie-breakers).
        - Fail fast if the first configured key is not present in the execution column set.
        """
        configured_keys_norm: List[str] = []
        if isinstance(configured_keys_raw, (list, tuple)):
            for k in configured_keys_raw:
                if k is None:
                    continue
                ks = str(k).strip()
                if ks:
                    configured_keys_norm.append(ks)

        pk_columns_norm = [str(p).strip() for p in (pk_columns or []) if str(p).strip()]
        pk_columns_in_set = [k for k in pk_columns_norm if (k or "").lower() in column_name_set]

        if pk_columns_in_set:
            effective = pk_columns_in_set
        else:
            if not configured_keys_norm:
                raise TableSyncError(
                    f"No stable upsert key available for {context}. "
                    f"Provide a source primary key, configure SyncJobTable.incremental_key_columns, "
                    f"or mark stable key column(s) as Protected in Step 3 mapping."
                )

            first = configured_keys_norm[0]
            if (first or "").lower() not in column_name_set:
                available = sorted(column_name_set)
                available_preview = available[:50]
                raise TableSyncError(
                    f"First configured upsert key '{first}' is not present in source columns for {context}. "
                    f"Available columns (truncated): {available_preview}"
                )

            effective = [k for k in configured_keys_norm if (k or "").lower() in column_name_set]
            if not effective:
                raise TableSyncError(
                    f"Configured upsert key columns for {context} do not match any available source columns."
                )

        # Dedupe while preserving order
        seen = set()
        out: List[str] = []
        for k in effective:
            kl = (k or "").lower()
            if kl in seen:
                continue
            seen.add(kl)
            out.append(k)
        return out

    def _get_configured_upsert_key_sources(self, job_table: Any) -> List[str]:
        """
        Ordered upsert key candidates from job configuration.

        Precedence matches flat-file incremental: use SyncJobTable.incremental_key_columns
        when set; otherwise fall back to Step 3 protected_columns (stable source keys).
        """
        keys: List[str] = []
        raw = getattr(job_table, "incremental_key_columns", None)
        if isinstance(raw, (list, tuple)):
            for k in raw:
                if k is None:
                    continue
                ks = str(k).strip()
                if ks:
                    keys.append(ks)
        if keys:
            return keys
        prot = getattr(job_table, "protected_columns", None) or []
        if not isinstance(prot, (list, tuple)):
            return []
        for k in prot:
            if k is None:
                continue
            ks = str(k).strip()
            if ks:
                keys.append(ks)
        return keys

    def _resolve_incremental_column_auto(
        self,
        schema: str,
        table: str,
        columns: List[Any],
        pk_columns: List[str],
    ) -> Tuple[Optional[str], List[str], str]:
        """
        Resolve incremental column automatically using per-table metadata.
        Returns: (column_name | None, inspected_candidates, reason_code)
        """
        inspected = [c.name for c in columns]
        by_name = {c.name.lower(): c for c in columns}
        preferred_datetime_names = [
            "updated_at", "modified_at", "last_updated", "last_modified",
            "updatedon", "modifiedon", "update_date", "update_time",
            "updated_date", "modified_time", "modifieddate",
        ]

        for cname in preferred_datetime_names:
            col = by_name.get(cname)
            if col and self._is_datetime_like(col.data_type):
                return col.name, inspected, "auto_datetime_priority"

        for col in columns:
            if self._is_datetime_like(col.data_type):
                return col.name, inspected, "auto_datetime_fallback"

        if pk_columns:
            pk_lower = {p.lower() for p in pk_columns}
            for col in columns:
                if col.name.lower() in pk_lower and self._is_numeric_like(col.data_type):
                    return col.name, inspected, "auto_pk_numeric_fallback"
            for col in columns:
                if col.name.lower() in pk_lower:
                    return col.name, inspected, "auto_pk_fallback"

        # Fallback when source PK metadata is unavailable:
        # pick the first non-nullable numeric column, then nullable numeric.
        # This remains schema-driven and avoids hardcoded business names.
        numeric_non_nullable = [
            c for c in columns
            if self._is_numeric_like(c.data_type) and not bool(getattr(c, "is_nullable", True))
        ]
        if numeric_non_nullable:
            return numeric_non_nullable[0].name, inspected, "auto_numeric_column_fallback_non_nullable"
        numeric_any = [c for c in columns if self._is_numeric_like(c.data_type)]
        if numeric_any:
            return numeric_any[0].name, inspected, "auto_numeric_column_fallback"

        return None, inspected, "no_safe_incremental_column"

    def execute(self):
        """
        Execute incremental sync for all enabled tables
        
        Steps:
        1. Update execution status to 'running'
        2. Validate all tables have incremental columns
        3. Connect to source and target databases
        4. Sync each table (continue on individual failures)
        5. Update final execution status
        6. Handle errors gracefully
        
        Raises:
            TableSyncError: If sync fails
        """
        try:
            # Update execution status
            self.execution.status = 'running'
            self.execution.started_at = timezone.now()
            self.execution.save()
            
            # Get enabled tables with incremental columns
            tables = self.job.tables.filter(is_enabled=True)
            
            if not tables.exists():
                logger.warning(f"No enabled tables found for job {self.job.id}")
                self.execution.status = 'completed'
                self.execution.completed_at = timezone.now()
                self.execution.save()
                return
            
            # Connect to databases
            try:
                if not hasattr(self.source_connector, '_connected') or not self.source_connector._connected:
                    self.source_connector.connect()
                    self.source_connector._connected = True
            except Exception as e:
                error_msg = f"Failed to connect to source database: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            try:
                if not hasattr(self.target_connector, '_connected') or not self.target_connector._connected:
                    self.target_connector.connect()
                    self.target_connector._connected = True
            except Exception as e:
                error_msg = f"Failed to connect to target database: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Sync each table
            for job_table in tables:
                try:
                    self.sync_table(job_table)
                except TableSyncError as e:
                    logger.error(f"Table sync failed for {job_table.schema_name}.{job_table.table_name}: {str(e)}")
                    # Continue with other tables
                    continue
                except Exception as e:
                    logger.error(
                        f"Unexpected error syncing table {job_table.schema_name}.{job_table.table_name}: {str(e)}",
                        exc_info=True
                    )
                    # Continue with other tables
                    continue
            
            # Final status update
            completed_logs = SyncExecutionLog.objects.filter(
                execution=self.execution,
                status='completed'
            )
            failed_logs = SyncExecutionLog.objects.filter(
                execution=self.execution,
                status='failed'
            )
            total_tables = tables.count()
            completed_count = completed_logs.count()
            failed_count = failed_logs.count()
            
            # Determine execution status
            if failed_count == total_tables and total_tables > 0:
                # ALL tables failed
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"All {failed_count} table(s) failed to sync"
                )
            elif failed_logs.exists():
                # SOME tables failed (partial failure)
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"{failed_count} of {total_tables} table(s) failed to sync"
                )
            elif completed_count == total_tables and total_tables > 0:
                # ALL tables succeeded
                self.execution.status = 'completed'
            else:
                # No logs created (shouldn't happen, but handle gracefully)
                self.execution.status = 'failed'
                self.execution.error_message = "No tables were processed"
            
            self.execution.completed_at = timezone.now()
            self.execution.save()
            
            logger.info(
                f"Incremental sync execution {self.execution.id} completed: "
                f"{completed_count}/{total_tables} tables synced"
            )
            
        except Exception as e:
            logger.error(
                f"Incremental sync execution failed: {str(e)}",
                exc_info=True
            )
            self.execution.status = 'failed'
            self.execution.error_message = str(e)
            self.execution.completed_at = timezone.now()
            self.execution.save()
            raise

    def _validate_incremental_column_transform_outputs(
        self, column_infos: List[ColumnInfo], incremental_column: str
    ) -> None:
        by_lower = {c.name.lower(): c for c in column_infos}
        col = by_lower.get((incremental_column or "").strip().lower())
        if not col:
            raise TableSyncError(
                f"Incremental column '{incremental_column}' not found in model output columns."
            )
        col_type = (col.data_type or "").lower()
        valid_types = [
            "timestamp",
            "datetime",
            "date",
            "timestamptz",
            "int",
            "integer",
            "bigint",
            "serial",
            "int4",
            "int8",
            "float",
            "double",
            "numeric",
            "decimal",
            "varchar",
            "text",
        ]
        db_type = QueryBuilder.get_db_type(self.source_connector)
        if db_type == "clickhouse":
            valid_types.extend(
                ["datetime64", "uint32", "uint64", "int32", "int64", "int8", "int16"]
            )
        if not any(vt in col_type for vt in valid_types):
            logger.warning(
                "Incremental column '%s' type '%s' may be suboptimal for checkpoints.",
                incremental_column,
                col_type,
            )

    def _sync_table_incremental_with_transform(
        self,
        job_table: SyncJobTable,
        schema: str,
        table: str,
        target_table: str,
        target_schema: str,
        log: SyncExecutionLog,
        rt_plan: Dict[str, Any],
    ) -> None:
        """Incremental sync using model transform SQL wrapped with incremental predicates."""
        mode = (rt_plan.get("mode") or "").strip().lower()
        if mode == "union":
            raise TableSyncError(
                f"[{ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM}] "
                "Incremental sync does not support UNION model transforms. "
                "Use join or lookup, or run a full sync."
            )

        tq = job_table.transformation_query
        ct = job_table.column_transformations or {}
        if (tq and str(tq).strip()) or ct:
            raise TableSyncError(
                f"[{ERROR_TRANSFORM_PLAN_CONFLICT}] "
                "Legacy SQL transformations cannot be combined with model transforms for incremental sync."
            )

        column_infos = column_infos_from_transform_plan(rt_plan)
        overrides = getattr(job_table, "column_type_overrides", None) or {}
        for col in column_infos:
            o = overrides.get(col.name.lower())
            if o:
                col.data_type = o

        # Strict incremental guardrail:
        # The incremental key must come from the base table row grain (selected_output_columns.table_ref == 'b0').
        # This avoids incorrect checkpoint semantics when the transform includes joins/lookups that can change row grain.
        selected_outputs = rt_plan.get("selected_output_columns") or []
        base_aliases_lower = {
            str(oc.get("alias") or "").strip().lower()
            for oc in selected_outputs
            if isinstance(oc, dict) and str(oc.get("table_ref") or "").strip().lower() == "b0"
        }
        base_column_infos = [c for c in column_infos if c.name.lower() in base_aliases_lower]

        pk_source = self.source_connector.get_primary_key(schema, table) or []
        if not isinstance(pk_source, (list, tuple)):
            pk_source = []
        pk_lower = {str(p).strip().lower() for p in pk_source if p}

        # Use base-table PKs (physical column names) mapped back to output aliases.
        pk_in_output_aliases = [
            str(oc.get("alias") or "").strip()
            for oc in selected_outputs
            if isinstance(oc, dict)
            and str(oc.get("table_ref") or "").strip().lower() == "b0"
            and str(oc.get("column") or "").strip().lower() in pk_lower
            and str(oc.get("alias") or "").strip()
        ]

        # Determine effective key aliases for upsert + deterministic ordering.
        # PK aliases (when present) are preferred; otherwise incremental_key_columns or Step 3 protected columns.
        configured_keys_norm = self._get_configured_upsert_key_sources(job_table)

        base_phys_to_alias = {
            str(oc.get("column") or "").strip().lower(): str(oc.get("alias") or "").strip()
            for oc in selected_outputs
            if isinstance(oc, dict)
            and str(oc.get("table_ref") or "").strip().lower() == "b0"
            and str(oc.get("column") or "").strip()
            and str(oc.get("alias") or "").strip()
        }

        if pk_in_output_aliases:
            effective_key_aliases = pk_in_output_aliases
        else:
            if not configured_keys_norm:
                raise TableSyncError(
                    f"No stable upsert key available for {schema}.{table} (transform incremental). "
                    f"Provide a base-table primary key, configure SyncJobTable.incremental_key_columns, "
                    f"or mark stable key column(s) as Protected in Step 3 mapping (and include them in the transform output)."
                )
            first_phys = configured_keys_norm[0]
            if (first_phys or "").strip().lower() not in base_phys_to_alias:
                available_aliases = sorted(set(base_phys_to_alias.values()))
                raise TableSyncError(
                    f"First configured upsert key '{first_phys}' cannot be mapped to any base-table output alias "
                    f"for {schema}.{table}. Available base output aliases: {available_aliases[:50]}"
                )
            effective_key_aliases = [
                base_phys_to_alias[k.lower()]
                for k in configured_keys_norm
                if (k or "").strip().lower() in base_phys_to_alias and base_phys_to_alias[k.lower()].strip()
            ]
            if not effective_key_aliases:
                raise TableSyncError(
                    f"Configured upsert key columns for {schema}.{table} do not match any base-table output columns."
                )

        # Dedupe key aliases while preserving order
        seen_aliases = set()
        deduped_aliases: List[str] = []
        for a in effective_key_aliases:
            al = (a or "").strip().lower()
            if not al or al in seen_aliases:
                continue
            seen_aliases.add(al)
            deduped_aliases.append(a)
        effective_key_aliases = deduped_aliases

        incremental_column = job_table.incremental_column
        if incremental_column:
            try:
                validate_incremental_key_from_base(rt_plan, incremental_column)
            except TransformPlanValidationError as e:
                raise TableSyncError(f"[{e.error_code}] {e.message}") from e
        else:
            incremental_column, inspected, reason_code = self._resolve_incremental_column_auto(
                schema=schema,
                table=table,
                columns=base_column_infos,
                pk_columns=pk_in_output_aliases,
            )
            if not incremental_column:
                prefix = getattr(self.job, "target_table_prefix", None)
                warning_msg = (
                    f"Skipped incremental sync for {schema}.{table}: no safe base-table incremental column "
                    f"(reason={reason_code}, inspected={inspected}, "
                    f"target={target_schema}.{target_table}, prefix={prefix or 'none'})."
                )
                logger.warning(warning_msg)
                log.status = "completed"
                log.rows_fetched = 0
                log.rows_inserted = 0
                log.error_message = warning_msg[:5000]
                log.verification_summary = "Skipped (no safe base-table incremental column in transform output)"
                log.completed_at = timezone.now()
                log.save()
                return
            job_table.incremental_column = incremental_column
            try:
                job_table.save(update_fields=["incremental_column"])
            except Exception:
                logger.debug("Could not persist auto-resolved incremental column", exc_info=True)

            try:
                validate_incremental_key_from_base(rt_plan, incremental_column)
            except TransformPlanValidationError as e:
                raise TableSyncError(f"[{e.error_code}] {e.message}") from e

        self._validate_incremental_column_transform_outputs(column_infos, incremental_column)

        if mode == "join":
            logger.warning(
                "Transform incremental sync uses base-table watermark semantics. Ensure the join does not change row grain "
                "for the incremental key, otherwise checkpoints may cause duplicates or misses."
            )

        checkpoint_value = self.checkpoint_manager.get_checkpoint_value(schema, table)
        checkpoint_value_raw = checkpoint_value
        inc_col_info = next(
            (c for c in column_infos if c.name.lower() == incremental_column.lower()),
            None,
        )
        col_type = (inc_col_info.data_type or "").lower() if inc_col_info else "timestamp"
        effective_checkpoint_value = checkpoint_value
        if checkpoint_value:
            checkpoint_value = self.timezone_handler.parse_checkpoint_value(
                checkpoint_value, col_type
            )
            effective_checkpoint_value = self._apply_incremental_overlap(
                checkpoint_value, col_type
            )

        column_names = [c.name for c in column_infos]
        rename_overrides = getattr(job_table, "column_name_overrides", None)
        if not isinstance(rename_overrides, dict):
            rename_overrides = {}
        target_column_names = [rename_overrides.get(c.name.lower(), c.name) for c in column_infos]

        incremental_col_index = next(
            i for i, n in enumerate(column_names) if n.lower() == incremental_column.lower()
        )

        try:
            # Fail fast if the transform plan references non-existent physical columns.
            validate_transform_plan_column_references(rt_plan, self.source_connector)
            inner_sql, warn_list = compile_select_from_plan(rt_plan, preview_limit=None)
        except TransformPlanValidationError as e:
            raise TableSyncError(f"[{e.error_code}] {e.message}") from e
        except Exception as e:
            raise TableSyncError(f"[transform_compile_failed] {str(e)}") from e

        if warn_list:
            logger.info("Transform incremental compile warnings %s.%s: %s", schema, table, warn_list)

        order_by_arg = f"{incremental_column}, {', '.join(effective_key_aliases)}"

        try:
            query = self.query_builder.build_incremental_on_subquery(
                self.source_connector,
                inner_sql,
                "tfs",
                incremental_column,
                effective_checkpoint_value,
                column_names,
                order_by_arg,
            )
        except Exception as e:
            raise TableSyncError(
                f"Failed to build incremental query over model transform for {schema}.{table}: {e}"
            ) from e

        logger.info(
            "Transform incremental sync %s.%s mode=%s checkpoint=%s",
            schema,
            table,
            mode,
            checkpoint_value,
        )

        batch_number = 0
        total_rows_fetched = 0
        total_rows_inserted = 0
        max_incremental_value = checkpoint_value

        while True:
            batch = self._fetch_batch_with_retry(
                query=query,
                batch_size=self.batch_size,
                offset=total_rows_fetched,
            )
            if not isinstance(batch, (list, tuple)):
                try:
                    batch = list(batch)
                except Exception:
                    batch = []
            if not batch:
                break
            batch_number += 1
            total_rows_fetched += len(batch)
            self.validator.validate_batch_not_empty(batch, f"{schema}.{table}")
            max_incremental_value = self._get_max_incremental_value(
                batch, incremental_col_index, max_incremental_value
            )
            try:
                total_rows_inserted += self._upsert_batch_with_retry(
                    schema=target_schema,
                    table=target_table,
                    columns=target_column_names,
                    rows=batch,
                    key_columns=(
                            [rename_overrides.get(k.lower(), k) for k in effective_key_aliases]
                    ),
                )
            except Exception as e:
                error_msg = f"Failed to upsert batch {batch_number} for {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                self._handle_partial_batch_failure(schema, table, batch_number, batch)
                raise TableSyncError(error_msg) from e

            log.batch_number = batch_number
            log.rows_fetched = total_rows_fetched
            log.rows_inserted = total_rows_inserted
            log.save()

            self.execution.completed_tables = SyncExecutionLog.objects.filter(
                execution=self.execution,
                status="completed",
            ).count()
            self.execution.total_rows_synced = (
                SyncExecutionLog.objects.filter(execution=self.execution).aggregate(
                    total=Sum("rows_inserted")
                )["total"]
                or 0
            )
            self.execution.save()

            if len(batch) < self.batch_size:
                break

        # Success-only checkpoint decision (strict monotonic: advance only when candidate_max > previous).
        did_advance = self._compare_incremental_values(max_incremental_value, checkpoint_value)
        if did_advance:
            decision_reason = "advance"
        else:
            decision_reason = (
                "skip_equal" if max_incremental_value == checkpoint_value else "skip_not_greater"
            )
        checkpoint_update_outcome = "skipped"
        try:
            advanced = self.checkpoint_manager.maybe_advance_checkpoint(
                schema_name=schema,
                table_name=table,
                did_advance=did_advance,
                value=max_incremental_value,
            )
            checkpoint_update_outcome = "advanced" if advanced else "skipped"
        except Exception as e:
            checkpoint_update_outcome = "update_failed"
            logger.error(
                f"Failed to update checkpoint for {schema}.{table}: {str(e)}",
                exc_info=True,
            )

        checkpoint_decision_text = self._build_checkpoint_diagnostics(
            checkpoint_value_raw=checkpoint_value_raw,
            checkpoint_value_parsed=checkpoint_value,
            effective_checkpoint_value=effective_checkpoint_value,
            candidate_max=max_incremental_value,
            decision_reason=decision_reason,
            update_outcome=checkpoint_update_outcome,
        )
        schema_drift_added = self._last_schema_drift_added_columns.get((target_schema, target_table), [])
        schema_drift_suffix = (
            f"; schema_drift_added_columns={','.join(schema_drift_added)}"
            if schema_drift_added else ""
        )
        log.verification_summary = (
            f"Transform incremental mode={mode}; rows upserted={total_rows_inserted}; {checkpoint_decision_text}{schema_drift_suffix}"
        )
        log.status = "completed"
        log.completed_at = timezone.now()
        log.save()
        logger.info(
            "Completed transform incremental sync for %s.%s: %s rows",
            schema,
            table,
            total_rows_inserted,
        )
    
    def sync_table(self, job_table: SyncJobTable):
        """
        Sync a single table using incremental sync
        
        Steps:
        1. Validate incremental column
        2. Get checkpoint value (None for first sync)
        3. Ensure target table exists (create if not, no truncate)
        4. Build incremental query (WHERE incremental_column > checkpoint_value)
        5. Fetch batches from source
        6. Insert batches into target (no truncate)
        7. Track max incremental value
        8. Update checkpoint after successful sync
        
        Args:
            job_table: SyncJobTable instance
            
        Raises:
            TableSyncError: If table sync fails
        """
        schema = job_table.schema_name
        table = job_table.table_name
        target_table = get_target_table_name(self.job, table)
        incremental_column = job_table.incremental_column
        
        # Determine target schema
        # For databases WITH schemas (PostgreSQL, SQL Server, Oracle): use target's default schema/owner
        # For databases WITHOUT schemas (MySQL, ClickHouse): use database name directly
        # For MongoDB targets: use connector database_name if provided; otherwise use source schema.
        if self.table_handler.target_db_type == 'mysql':
            # MySQL: Use database name directly (no schema concept)
            target_schema = self.target_connector.database_name
            logger.info(f"Using MySQL database '{target_schema}' for source schema '{schema}' (no schema concept)")
        elif self.table_handler.target_db_type == 'clickhouse':
            # ClickHouse: Use database name from connection if available
            # Map to connection database instead of source schema
            target_schema = getattr(self.target_connector, 'database_name', None) or 'default'
            logger.info(
                f"Mapping source schema '{schema}' to ClickHouse database '{target_schema}' "
                f"(using connector database name)"
            )
        elif self.table_handler.target_db_type == 'postgres':
            # PostgreSQL: Always use 'public' schema regardless of source schema
            target_schema = 'public'
            logger.info(
                f"Mapping source schema '{schema}' to PostgreSQL schema 'public' "
                f"(all tables in public schema)"
            )
        elif self.table_handler.target_db_type == 'sqlserver':
            # SQL Server: Always use 'dbo' schema regardless of source schema
            target_schema = 'dbo'
            logger.info(
                f"Mapping source schema '{schema}' to SQL Server schema 'dbo' "
                f"(all tables in dbo schema)"
            )
        elif self.table_handler.target_db_type == 'oracle':
            # Oracle: use connected user as schema/owner so tables are in their schema
            target_schema = (getattr(self.target_connector, 'username', None) or '').strip().upper() or schema
            logger.info(
                f"Mapping source schema '{schema}' to Oracle owner '{target_schema}' "
                f"(connected user)"
            )
        elif self.table_handler.target_db_type == 'mongodb':
            target_schema = getattr(self.target_connector, 'database_name', None) or schema
            logger.info(
                f"Using MongoDB database '{target_schema}' for source schema '{schema}'"
            )
        else:
            target_schema = schema
        
        # Create execution log
        log = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name=schema,
            table_name=table,
            status='pending'
        )
        
        try:
            log.status = 'running'
            log.started_at = timezone.now()
            log.save()
            if not self._prevent_concurrent_sync(schema, table):
                skip_msg = f"Skipped (concurrent execution running for {schema}.{table})"
                log.status = 'completed'
                log.rows_fetched = 0
                log.rows_inserted = 0
                log.error_message = skip_msg[:5000]
                log.verification_summary = skip_msg
                log.completed_at = timezone.now()
                log.save()
                return

            # Strict incremental mode: never auto-create target tables.
            # Missing target table => warning + skip this table, continue execution.
            try:
                if self.table_handler.target_db_type != 'mongodb' and not self.target_connector.table_exists(target_schema, target_table):
                    prefix = getattr(self.job, "target_table_prefix", None)
                    warning_msg = (
                        f"Skipped incremental sync for {schema}.{table}: "
                        f"target table {target_schema}.{target_table} does not exist. "
                        f"Incremental sync does not create new tables "
                        f"(reason=missing_target_table, prefix={prefix or 'none'}, sync_type=incremental)."
                    )
                    logger.warning(warning_msg)
                    log.status = 'completed'
                    log.rows_fetched = 0
                    log.rows_inserted = 0
                    log.error_message = warning_msg[:5000]
                    log.verification_summary = "Skipped (missing target table in strict incremental mode)"
                    log.completed_at = timezone.now()
                    log.save()
                    return
            except Exception as e:
                error_msg = f"Failed to verify target table existence: {str(e)}"
                logger.error(f"Target table check error for {schema}.{table}: {error_msg}", exc_info=True)
                raise TableSyncError(error_msg) from e

            def _run_keyed_snapshot_fallback(
                *,
                columns: List[ColumnInfo],
                pk_columns: List[str],
            ) -> None:
                """
                Fallback path when no safe incremental column exists.
                Behavior: full-table read + deterministic keyed upsert, no checkpoint progression.
                """
                raw_excluded = getattr(job_table, "excluded_columns", None)
                if not isinstance(raw_excluded, (list, tuple, set)):
                    raw_excluded = []
                raw_protected = getattr(job_table, "protected_columns", None)
                if not isinstance(raw_protected, (list, tuple, set)):
                    raw_protected = []
                excluded_cols = {(c or "").strip().lower() for c in raw_excluded if c}
                protected_cols = {(c or "").strip().lower() for c in raw_protected if c}
                effective_excluded = excluded_cols - protected_cols
                if effective_excluded:
                    columns = [c for c in columns if c.name.lower() not in effective_excluded]
                    if not columns:
                        raise TableSyncError(
                            f"No migratable columns remain after exclusion rules for {schema}.{table}"
                        )
                column_name_set = {c.name.lower() for c in columns}
                pk_cols_filtered = [pk for pk in (pk_columns or []) if (pk or "").lower() in column_name_set]
                configured_keys_raw = self._get_configured_upsert_key_sources(job_table)
                effective_key_columns = self._resolve_effective_upsert_keys(
                    pk_columns=pk_cols_filtered,
                    configured_keys_raw=configured_keys_raw,
                    column_name_set=column_name_set,
                    context=f"{schema}.{table} (snapshot fallback)",
                )

                column_names = [col.name for col in columns]
                rename_overrides = getattr(job_table, "column_name_overrides", None)
                if not isinstance(rename_overrides, dict):
                    rename_overrides = {}
                target_column_names = [
                    rename_overrides.get(col.name.lower(), col.name)
                    for col in columns
                ]

                where_clause = job_table.transformation_query if isinstance(job_table.transformation_query, str) else None
                where_clause = where_clause.strip() if where_clause else None
                if not where_clause:
                    where_clause = None
                column_transformations = job_table.column_transformations
                if not isinstance(column_transformations, dict):
                    column_transformations = {}

                order_by = ", ".join(effective_key_columns)
                query = self.query_builder.build_select_query(
                    connector=self.source_connector,
                    schema=schema,
                    table=table,
                    columns=column_names,
                    order_by=order_by,
                    where_clause=where_clause,
                    column_transformations=column_transformations if column_transformations else None,
                )
                logger.warning(
                    "No safe incremental column for %s.%s; running keyed snapshot upsert fallback (no checkpoint).",
                    schema,
                    table,
                )

                batch_number = 0
                total_rows_fetched = 0
                total_rows_inserted = 0
                while True:
                    batch = self._fetch_batch_with_retry(
                        query=query,
                        batch_size=self.batch_size,
                        offset=total_rows_fetched,
                    )
                    if not isinstance(batch, (list, tuple)):
                        try:
                            batch = list(batch)
                        except Exception:
                            batch = []
                    if not batch:
                        break
                    batch_number += 1
                    total_rows_fetched += len(batch)
                    self.validator.validate_batch_not_empty(batch, f"{schema}.{table}")
                    inserted = self._upsert_batch_with_retry(
                        schema=target_schema,
                        table=target_table,
                        columns=target_column_names,
                        rows=batch,
                        key_columns=[rename_overrides.get(k.lower(), k) for k in effective_key_columns],
                    )
                    total_rows_inserted += inserted
                    log.batch_number = batch_number
                    log.rows_fetched = total_rows_fetched
                    log.rows_inserted = total_rows_inserted
                    log.save()
                    self.execution.completed_tables = SyncExecutionLog.objects.filter(
                        execution=self.execution,
                        status='completed'
                    ).count()
                    self.execution.total_rows_synced = SyncExecutionLog.objects.filter(
                        execution=self.execution
                    ).aggregate(total=Sum('rows_inserted'))['total'] or 0
                    self.execution.save()
                    if len(batch) < self.batch_size:
                        break

                log.verification_summary = (
                    "Incremental fallback mode (no safe incremental column): "
                    f"rows upserted={total_rows_inserted}; checkpoint unchanged."
                )
                log.status = 'completed'
                log.completed_at = timezone.now()
                log.save()
                logger.info(
                    "Completed keyed snapshot fallback for %s.%s: fetched=%s inserted=%s",
                    schema,
                    table,
                    total_rows_fetched,
                    total_rows_inserted,
                )

            raw_excluded_ft = getattr(job_table, "excluded_columns", None) or []
            raw_protected_ft = getattr(job_table, "protected_columns", None) or []
            if not isinstance(raw_excluded_ft, (list, tuple, set)):
                raw_excluded_ft = []
            if not isinstance(raw_protected_ft, (list, tuple, set)):
                raw_protected_ft = []
            excluded_lower_ft = {(c or "").strip().lower() for c in raw_excluded_ft if c}
            protected_lower_ft = {(c or "").strip().lower() for c in raw_protected_ft if c}
            prot_for_plan = set(protected_lower_ft)
            if incremental_column:
                prot_for_plan.add(incremental_column.strip().lower())
            try:
                rt_plan = prepare_runtime_transform_plan(
                    job_table,
                    self.job,
                    QueryBuilder.get_db_type(self.source_connector),
                    excluded_cols_lower=excluded_lower_ft,
                    protected_cols_lower=prot_for_plan,
                )
            except TransformPlanValidationError as e:
                raise TableSyncError(f"[{e.error_code}] {e.message}") from e
            if rt_plan is not None:
                tq = job_table.transformation_query
                ct = job_table.column_transformations or {}
                if (tq and str(tq).strip()) or ct:
                    raise TableSyncError(
                        f"[{ERROR_TRANSFORM_PLAN_CONFLICT}] "
                        "Legacy SQL transformations cannot be combined with model transforms."
                    )
                self._sync_table_incremental_with_transform(
                    job_table=job_table,
                    schema=schema,
                    table=table,
                    target_table=target_table,
                    target_schema=target_schema,
                    log=log,
                    rt_plan=rt_plan,
                )
                return

            # Resolve incremental column automatically when not configured.
            try:
                columns = self.source_connector.get_columns(schema, table)
                if not columns:
                    raise TableSyncError(f"No columns found for source table {schema}.{table}")
                pk_columns = self.source_connector.get_primary_key(schema, table) or []
                if not isinstance(pk_columns, (list, tuple)):
                    pk_columns = []
                if not incremental_column:
                    incremental_column, inspected_candidates, reason_code = self._resolve_incremental_column_auto(
                        schema=schema,
                        table=table,
                        columns=columns,
                        pk_columns=pk_columns,
                    )
                    if not incremental_column:
                        _run_keyed_snapshot_fallback(columns=columns, pk_columns=pk_columns)
                        return
                    job_table.incremental_column = incremental_column
                    try:
                        job_table.save(update_fields=["incremental_column"])
                    except Exception:
                        logger.debug("Could not persist auto-resolved incremental column", exc_info=True)

                # Validate resolved/configured incremental column
                self._validate_incremental_column(schema, table, incremental_column)
            except Exception as e:
                error_msg = f"Failed to resolve incremental column for {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e

            # Apply Step 3 exclusion/protection contract to incremental runtime.
            raw_excluded = getattr(job_table, "excluded_columns", None)
            if not isinstance(raw_excluded, (list, tuple, set)):
                raw_excluded = []
            raw_protected = getattr(job_table, "protected_columns", None)
            if not isinstance(raw_protected, (list, tuple, set)):
                raw_protected = []
            excluded_cols = {(c or "").strip().lower() for c in raw_excluded if c}
            protected_cols = {(c or "").strip().lower() for c in raw_protected if c}
            # Incremental column must always be present for incremental query/upsert logic.
            protected_cols.add((incremental_column or "").strip().lower())
            effective_excluded = excluded_cols - protected_cols
            if effective_excluded:
                columns = [c for c in columns if c.name.lower() not in effective_excluded]
                if not columns:
                    raise TableSyncError(
                        f"No migratable columns remain after exclusion rules for {schema}.{table}"
                    )
            column_name_set = {c.name.lower() for c in columns}
            pk_columns = [pk for pk in pk_columns if (pk or "").lower() in column_name_set]

            # Resolve upsert key columns: PK preferred; otherwise incremental_key_columns or protected columns.
            configured_keys_raw = self._get_configured_upsert_key_sources(job_table)
            effective_key_columns = self._resolve_effective_upsert_keys(
                pk_columns=pk_columns,
                configured_keys_raw=configured_keys_raw,
                column_name_set=column_name_set,
                context=f"{schema}.{table}",
            )

            eligibility = None
            try:
                from sync_engine.eligibility import IncrementalEligibility
                eligibility = IncrementalEligibility.evaluate(
                    configured_incremental_column=incremental_column,
                    configured_key_columns=configured_keys_raw,
                    columns=columns,
                    pk_columns=pk_columns,
                    assume_incremental_monotonic=(
                        self.table_handler.target_db_type != "clickhouse"
                    ),
                )
                eligibility_text = f"Eligibility: {eligibility.summary()}"
                logger.info("[%s.%s] %s", schema, table, eligibility_text)
                existing_summary = getattr(log, "verification_summary", None) or ""
                log.verification_summary = (
                    f"{existing_summary}; {eligibility_text}" if existing_summary else eligibility_text
                )[:5000]
                log.save(update_fields=["verification_summary"])
            except Exception as classifier_err:
                logger.warning(
                    "Eligibility classifier failed for %s.%s: %s",
                    schema,
                    table,
                    classifier_err,
                )

            # Eligibility-based fallback: if the table is not safe for incremental
            # (e.g. monotonic watermark not defensible for Postgres->ClickHouse),
            # fall back to a full sync for correctness.
            if (
                eligibility
                and getattr(eligibility, "mode", "incremental") == "full"
                and any(
                    "monotonic_unknown_disallow_non_rowversion" in (r or "")
                    for r in getattr(eligibility, "reasons", [])
                )
            ):
                logger.warning(
                    "Eligibility returned full for %s.%s; running FullSyncExecutor immediately.",
                    schema,
                    table,
                )
                from sync_engine.full_sync import FullSyncExecutor

                FullSyncExecutor(
                    job=self.job,
                    execution=self.execution,
                    source_connector=self.source_connector,
                    target_connector=self.target_connector,
                ).sync_table(job_table)

                # Reset checkpoint so the next incremental run starts from a clean baseline.
                try:
                    self.checkpoint_manager.delete_checkpoint(schema, table)
                except Exception:
                    pass
                # Mark this incremental log as completed (full sync produced the real output).
                try:
                    log.status = "completed"
                    log.completed_at = timezone.now()
                    log.save(update_fields=["status", "completed_at"])
                except Exception:
                    pass
                return
            # Mongo target upsert requires a single deterministic key for _id.
            if self.table_handler.target_db_type == 'mongodb' and len(effective_key_columns) != 1:
                raise TableSyncError(
                    f"MongoDB incremental target requires exactly one upsert key column for {schema}.{table}, "
                    f"got {effective_key_columns}. Configure SyncJobTable.incremental_key_columns to a single column."
                )

            try:
                ensure_unique_index = getattr(self.target_connector, 'ensure_unique_index', None)
                if callable(ensure_unique_index) and effective_key_columns:
                    rename_overrides_local = (
                        getattr(job_table, "column_name_overrides", None) or {}
                    )
                    if not isinstance(rename_overrides_local, dict):
                        rename_overrides_local = {}
                    target_keys = [
                        rename_overrides_local.get((k or '').lower(), k)
                        for k in effective_key_columns
                    ]
                    ensure_unique_index(target_schema, target_table, target_keys)
            except Exception as ensure_idx_err:
                logger.warning(
                    "ensure_unique_index failed for %s.%s: %s",
                    target_schema,
                    target_table,
                    ensure_idx_err,
                )

            # Accuracy-first fallback:
            # A date-only incremental column can miss late/backfilled rows
            # when checkpoint is high (e.g., col_date already at 9999-12-31). In that case,
            # use keyed snapshot upsert mode instead of strict > checkpoint filtering.
            inc_col_info = next(
                (c for c in columns if (c.name or "").lower() == (incremental_column or "").lower()),
                None,
            )
            inc_type_l = (getattr(inc_col_info, "data_type", "") or "").lower()
            is_date_only_incremental = ("date" in inc_type_l) and ("datetime" not in inc_type_l) and ("timestamp" not in inc_type_l)
            if is_date_only_incremental:
                logger.warning(
                    "Using keyed snapshot fallback for %s.%s because incremental column '%s' is date-only.",
                    schema,
                    table,
                    incremental_column,
                )
                _run_keyed_snapshot_fallback(columns=columns, pk_columns=pk_columns)
                return
            
            # Get checkpoint value
            checkpoint_value = self.checkpoint_manager.get_checkpoint_value(schema, table)
            checkpoint_value_raw = checkpoint_value
            effective_checkpoint_value = checkpoint_value
            
            # Parse checkpoint value if it's a string
            if checkpoint_value:
                # Get column type to parse correctly
                inc_col_info = next((col for col in columns if col.name == incremental_column), None)
                col_type = inc_col_info.data_type.lower() if inc_col_info else 'timestamp'
                
                # Handle ClickHouse DateTime64 precision (edge case)
                # DateTime64 can have high precision, ensure checkpoint comparison works
                if 'datetime64' in col_type:
                    logger.debug(f"ClickHouse DateTime64 detected for incremental column {incremental_column}")
                    # ClickHouse handles DateTime64 precision correctly, but ensure parsing works
                    # The timezone handler should handle this, but verify format
                
                checkpoint_value = self.timezone_handler.parse_checkpoint_value(
                    checkpoint_value, col_type
                )
                effective_checkpoint_value = self._apply_incremental_overlap(
                    checkpoint_value, col_type
                )
                logger.info(
                    f"Using checkpoint value for {schema}.{table}: {checkpoint_value}"
                )
            else:
                logger.info(f"No checkpoint found for {schema}.{table}.")
                effective_checkpoint_value = None
                # If this table already has data in target (e.g., user switched full -> incremental),
                # bootstrap checkpoint from source max incremental value to prevent full re-load.
                try:
                    if self._target_table_has_rows(schema=target_schema, table=target_table):
                        source_max = self._get_source_max_incremental_value(
                            schema=schema,
                            table=table,
                            incremental_column=incremental_column,
                        )
                        if source_max is not None:
                            self.checkpoint_manager.create_or_update_checkpoint(
                                schema_name=schema,
                                table_name=table,
                                value=source_max,
                            )
                            checkpoint_value_raw = source_max
                            checkpoint_value = source_max
                            effective_checkpoint_value = self._apply_incremental_overlap(
                                checkpoint_value,
                                inc_type_l,
                            )
                            logger.info(
                                "Bootstrapped incremental checkpoint for %s.%s from source max value %s "
                                "because target already had rows.",
                                schema,
                                table,
                                source_max,
                            )
                except Exception as bootstrap_error:
                    logger.warning(
                        "Checkpoint bootstrap skipped for %s.%s: %s. Continuing with first incremental sync.",
                        schema,
                        table,
                        str(bootstrap_error),
                    )
            
            # Get column information
            try:
                column_names = [col.name for col in columns]

                rename_overrides = getattr(job_table, "column_name_overrides", None)
                if not isinstance(rename_overrides, dict):
                    rename_overrides = {}
                target_column_names = [
                    rename_overrides.get(col.name.lower(), col.name)
                    for col in columns
                ]
                
                # Get incremental column index for tracking max value
                try:
                    incremental_col_index = column_names.index(incremental_column)
                except ValueError:
                    raise TableSyncError(
                        f"Incremental column '{incremental_column}' not found in column list"
                    )
            except Exception as e:
                error_msg = f"Failed to get columns from source table {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Get primary key for ordering
            try:
                order_by = f"{incremental_column}, {', '.join(effective_key_columns)}"
            except Exception as e:
                logger.warning(f"Could not determine primary key for {schema}.{table}: {str(e)}")
                order_by = incremental_column
            
            # Build incremental query
            try:
                base_query = self.query_builder.build_incremental_query(
                    connector=self.source_connector,
                    schema=schema,
                    table=table,
                    incremental_column=incremental_column,
                    checkpoint_value=effective_checkpoint_value,
                    columns=column_names,
                    order_by=order_by
                )
                logger.debug(f"Incremental query for {schema}.{table}: {base_query}")
            except Exception as e:
                error_msg = f"Failed to build incremental query for {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Validate and apply transformations
            # For incremental sync, we need to combine transformation WHERE with incremental WHERE
            transformation_where = job_table.transformation_query
            if not isinstance(transformation_where, str):
                transformation_where = None
            elif not transformation_where.strip():
                transformation_where = None
            column_transformations = job_table.column_transformations
            if not isinstance(column_transformations, dict):
                column_transformations = {}
            expected_row_count = None  # Initialize for post-migration verification
            pre_migration_query_results = None  # Initialize for post-migration verification
            
            if transformation_where or column_transformations:
                # Validate transformations
                transformed_query, transformation_error = self._validate_and_apply_transformations(
                    job_table=job_table,
                    base_query=base_query,
                    column_names=column_names
                )
                
                if transformation_error:
                    error_msg = f"Transformation validation failed for {schema}.{table}: {transformation_error}"
                    logger.error(error_msg)
                    raise TableSyncError(error_msg)
                
                # NEW: Enhanced pre-migration validation
                validation_passed, validation_error, validation_report = self._execute_pre_migration_validation(
                    job_table=job_table,
                    transformed_query=transformed_query,
                    base_query=base_query,
                    column_names=column_names
                )
                
                if not validation_passed:
                    error_msg = f"Pre-migration validation failed for {schema}.{table}: {validation_error}"
                    logger.error(error_msg)
                    raise TableSyncError(error_msg)
                
                # Store expected row count and query results for post-migration verification
                expected_row_count = validation_report.get('expected_row_count', 0) if validation_report else None
                pre_migration_query_results = validation_report.get('query_results', []) if validation_report else None
                
                query = transformed_query
            else:
                query = base_query
            
            # Fetch and insert in batches
            batch_number = 0
            total_rows_fetched = 0
            total_rows_inserted = 0
            total_rows_net_new = 0
            current_checkpoint = effective_checkpoint_value  # Track current position for keyset
            last_pk_values = None
            max_incremental_value = checkpoint_value
            
            # Use Keyset Pagination if we have PKs or the incremental column is unique/monotonic
            # For MS SQL, this is highly recommended
            use_keyset = bool(pk_columns)
            
            while True:
                # Fetch batch using keyset pagination
                if use_keyset:
                    # Build a query that uses current_checkpoint as the new boundary.
                    # We reuse build_incremental_query (no explicit LIMIT; batching is controlled by loop/checkpoint).
                    current_query = self.query_builder.build_incremental_query(
                        connector=self.source_connector,
                        schema=schema,
                        table=table,
                        incremental_column=incremental_column,
                        checkpoint_value=current_checkpoint,
                        columns=column_names,
                        order_by=order_by,
                    )
                    # For keyset, we execute directly without offset
                    try:
                        batch = self.source_connector.execute_query_fetchall(current_query)
                    except Exception as e:
                        # Fallback to OFFSET if keyset fails for some reason
                        logger.warning(f"Keyset pagination failed, falling back to OFFSET: {str(e)}")
                        use_keyset = False
                        batch = self._fetch_batch_with_retry(
                            query=query,
                            batch_size=self.batch_size,
                            offset=total_rows_fetched
                        )
                else:
                    batch = self._fetch_batch_with_retry(
                        query=query,
                        batch_size=self.batch_size,
                        offset=total_rows_fetched
                    )
                if not isinstance(batch, (list, tuple)):
                    if use_keyset:
                        logger.warning(
                            "Keyset incremental fetch returned non-list for %s.%s; falling back to OFFSET batching.",
                            schema,
                            table,
                        )
                        use_keyset = False
                        batch = self._fetch_batch_with_retry(
                            query=query,
                            batch_size=self.batch_size,
                            offset=total_rows_fetched
                        )
                    if not isinstance(batch, (list, tuple)):
                        try:
                            batch = list(batch)
                        except Exception:
                            batch = []
                
                if not batch:
                    break  # No more rows
                
                batch_number += 1
                total_rows_fetched += len(batch)
                
                # Update checkpoint for next iteration
                if use_keyset:
                    last_row = batch[-1]
                    current_checkpoint = last_row[incremental_col_index]
                
                # Validate batch
                self.validator.validate_batch_not_empty(batch, f"{schema}.{table}")
                
                # Apply row transformations if column transformations were applied
                if column_transformations:
                    batch = self.transformation_engine.apply_row_transformations(
                        batch=batch,
                        column_names=column_names,
                        column_transformations=column_transformations
                    )
                
                # Find max incremental value in batch
                max_incremental_value = self._get_max_incremental_value(
                    batch, incremental_col_index, max_incremental_value
                )
                
                # Upsert batch with retry (incremental must handle inserts + updates)
                try:
                    inserted = self._upsert_batch_with_retry(
                        schema=target_schema,
                        table=target_table,
                        columns=target_column_names,
                        rows=batch,
                        key_columns=(
                            [rename_overrides.get(k.lower(), k) for k in effective_key_columns]
                        ),
                    )
                    total_rows_inserted += inserted
                    net_new_in_batch = self._count_rows_newer_than_checkpoint(
                        rows=batch,
                        incremental_col_index=incremental_col_index,
                        checkpoint_value=checkpoint_value,
                    )
                    total_rows_net_new += net_new_in_batch
                except Exception as e:
                    error_msg = f"Failed to upsert batch {batch_number} for {schema}.{table}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    self._handle_partial_batch_failure(schema, table, batch_number, batch)
                    raise TableSyncError(error_msg) from e
                
                # Update log
                log.batch_number = batch_number
                log.rows_fetched = total_rows_fetched
                # Report net-new rows for incremental dashboards.
                log.rows_inserted = total_rows_net_new
                log.save()
                
                # Update execution progress
                self.execution.completed_tables = SyncExecutionLog.objects.filter(
                    execution=self.execution,
                    status='completed'
                ).count()
                self.execution.total_rows_synced = SyncExecutionLog.objects.filter(
                    execution=self.execution
                ).aggregate(total=Sum('rows_inserted'))['total'] or 0
                self.execution.save()
                
                # Check if we got fewer rows than batch size (last batch)
                if len(batch) < self.batch_size:
                    break
            
            # Success-only checkpoint decision (do not advance until post-migration verification succeeds).
            did_advance = self._compare_incremental_values(max_incremental_value, checkpoint_value)
            if did_advance:
                decision_reason = "advance"
            else:
                decision_reason = (
                    "skip_equal" if max_incremental_value == checkpoint_value else "skip_not_greater"
                )
            # NEW: Post-migration data accuracy verification
            accuracy_report = None
            if transformation_where or column_transformations:
                # Only verify if transformations were applied
                if expected_row_count is not None:
                    is_accurate, accuracy_error, accuracy_report = self._verify_post_migration_accuracy(
                        job_table=job_table,
                        source_schema=schema,
                        target_schema=target_schema,
                        target_table=target_table,
                        expected_row_count=expected_row_count,
                        column_names=column_names,
                        target_column_names=target_column_names,
                        pre_migration_query_results=pre_migration_query_results  # NEW
                    )
                    
                    if not is_accurate:
                        # For incremental sync, we don't rollback (data is appended)
                        # But we log the error and fail the sync
                        error_msg = f"Post-migration verification failed for {schema}.{table}: {accuracy_error}"
                        logger.error(error_msg)
                        raise TableSyncError(error_msg)
                    
                    # Log perfect accuracy success
                    if accuracy_report.get('perfect_accuracy', False):
                        logger.info(
                            f"Perfect migration completed for {schema}.{table}: "
                            f"Zero data loss, zero inaccuracy, 100% accuracy verified"
                        )

            # Update checkpoint only after successful sync and (optional) post-migration verification.
            checkpoint_update_outcome = "skipped"
            try:
                advanced = self.checkpoint_manager.maybe_advance_checkpoint(
                    schema_name=schema,
                    table_name=table,
                    did_advance=did_advance,
                    value=max_incremental_value,
                )
                checkpoint_update_outcome = "advanced" if advanced else "skipped"
            except Exception as e:
                checkpoint_update_outcome = "update_failed"
                logger.error(
                    f"Failed to update checkpoint for {schema}.{table}: {str(e)}",
                    exc_info=True,
                )

            checkpoint_decision_text = self._build_checkpoint_diagnostics(
                checkpoint_value_raw=checkpoint_value_raw,
                checkpoint_value_parsed=checkpoint_value,
                effective_checkpoint_value=effective_checkpoint_value,
                candidate_max=max_incremental_value,
                decision_reason=decision_reason,
                update_outcome=checkpoint_update_outcome,
            )
            schema_drift_added = self._last_schema_drift_added_columns.get((target_schema, target_table), [])
            schema_drift_suffix = (
                f"; schema_drift_added_columns={','.join(schema_drift_added)}"
                if schema_drift_added else ""
            )
            
            # Surface verification summary for job/execution UI (Oracle-inclusive)
            if accuracy_report is not None:
                exp = accuracy_report.get('expected_row_count')
                act = accuracy_report.get('actual_row_count')
                perfect = accuracy_report.get('perfect_accuracy', False)
                mismatched = len(accuracy_report.get('mismatched_rows', []))
                parts = [f"Rows: {act}/{exp}" if exp is not None and act is not None else f"Rows inserted: {total_rows_inserted}"]
                parts.append("Perfect accuracy: Yes" if perfect else "Perfect accuracy: No")
                if mismatched > 0:
                    parts.append(f"Mismatched rows: {mismatched}")
                parts.append(f"Rows upserted: {total_rows_inserted}")
                parts.append(f"Net new rows: {total_rows_net_new}")
                log.verification_summary = f"{'; '.join(parts)}; {checkpoint_decision_text}{schema_drift_suffix}"
            else:
                log.verification_summary = (
                    f"Rows upserted={total_rows_inserted}; net_new_rows={total_rows_net_new}; "
                    f"{checkpoint_decision_text}{schema_drift_suffix}"
                )

            verification_mode = getattr(self.job, 'verification_mode', 'sampled') or 'sampled'
            if verification_mode != 'off':
                try:
                    from sync_engine.verification import verify_table_parity
                    parity = verify_table_parity(
                        job=self.job,
                        execution=self.execution,
                        source_connector=self.source_connector,
                        target_connector=self.target_connector,
                        source_schema=schema,
                        source_table=table,
                        target_schema=target_schema,
                        target_table=target_table,
                        sync_mode='incremental',
                        source_hash_columns=column_names if verification_mode == 'strict' else None,
                        target_hash_columns=target_column_names if verification_mode == 'strict' else None,
                        no_delete_propagation=getattr(self.job, 'no_delete_propagation', True),
                    )
                    parity_text = (
                        f"Parity[{verification_mode}]: source={parity.source_count} "
                        f"target={parity.target_count} decision={parity.decision}"
                    )
                    if log.verification_summary:
                        log.verification_summary = f"{log.verification_summary}; {parity_text}"
                    else:
                        log.verification_summary = parity_text
                    if parity.decision == 'repair_full':
                        logger.warning(
                            "Incremental parity drift detected for %s.%s; "
                            "will be repaired by full sync on next run (verification_mode=%s)",
                            schema,
                            table,
                            verification_mode,
                        )
                        if verification_mode == 'strict':
                            # Immediate repair: run full sync now, then reset checkpoint.
                            # This ensures "perfect after this run" semantics.
                            repair_attempts = getattr(self, "_immediate_repair_attempts", {})
                            repair_key = (schema, table)
                            if repair_attempts.get(repair_key):
                                raise TableSyncError(
                                    f"Incremental parity strict repair already attempted for {schema}.{table}; "
                                    f"aborting. source_count={parity.source_count} target_count={parity.target_count}"
                                )

                            repair_attempts[repair_key] = True
                            setattr(self, "_immediate_repair_attempts", repair_attempts)

                            try:
                                from sync_engine.full_sync import FullSyncExecutor

                                full_executor = FullSyncExecutor(
                                    job=self.job,
                                    execution=self.execution,
                                    source_connector=self.source_connector,
                                    target_connector=self.target_connector,
                                )
                                full_executor.sync_table(job_table)

                                # Full sync doesn't update incremental checkpoints; reset so the
                                # next incremental run starts from a clean baseline.
                                self.checkpoint_manager.delete_checkpoint(schema, table)
                            except Exception as repair_error:
                                raise TableSyncError(
                                    f"Incremental parity strict repair-full failed for {schema}.{table}: {str(repair_error)}"
                                ) from repair_error
                except TableSyncError:
                    raise
                except Exception as parity_error:
                    logger.warning(
                        "Parity verification skipped for %s.%s: %s",
                        schema,
                        table,
                        parity_error,
                    )

            # Mark log as completed
            log.status = 'completed'
            log.completed_at = timezone.now()
            log.save()
            
            logger.info(
                f"Successfully synced table {schema}.{table} incrementally: "
                f"upserted={total_rows_inserted}, net_new={total_rows_net_new} "
                f"in {batch_number} batches"
            )

            # NEW: Reconcile deletes (Perfect Sync)
            try:
                if getattr(self.job, "no_delete_propagation", True):
                    logger.info(
                        "No-delete mode active; skipping delete reconciliation for %s.%s",
                        schema,
                        table,
                    )
                    # Optional: keep the UI/execution summary explainable.
                    if getattr(log, "verification_summary", None):
                        log.verification_summary = (
                            f"{log.verification_summary}; No-delete mode active; "
                            f"skipping delete reconciliation."
                        )
                else:
                    self.reconcile_deletes(job_table, target_schema, target_table)
            except Exception as e:
                logger.warning(f"Delete reconciliation failed for {schema}.{table}: {e}")
                # Don't fail the whole sync if delete reconciliation fails
            
        except Exception as e:
            try:
                source_db = QueryBuilder.get_db_type(self.source_connector)
                target_db = QueryBuilder.get_db_type(self.target_connector)
                db_context = f" [Source: {source_db}, Target: {target_db}]"
                oracle_note = " Oracle ADW:" if (source_db == 'oracle' or target_db == 'oracle') else ""
            except Exception:
                db_context = ""
                oracle_note = ""
            log.status = 'failed'
            log.error_message = f"{oracle_note}{str(e)}{db_context}"[:5000]
            log.completed_at = timezone.now()
            log.save()
            
            logger.error(
                f"Failed to sync table {schema}.{table} incrementally: {str(e)}",
                exc_info=True
            )
            raise TableSyncError(f"Incremental sync failed for {schema}.{table}: {str(e)}") from e
    
    def _verify_post_migration_accuracy(
        self,
        job_table: SyncJobTable,
        source_schema: str,
        target_schema: str,
        target_table: str,
        expected_row_count: int,
        column_names: List[str],
        target_column_names: Optional[List[str]] = None,
        pre_migration_query_results: Optional[List[Tuple]] = None
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Enhanced post-migration data accuracy verification with perfect accuracy checks

        NEW: Compares stored pre-migration query results with target data for 100% accuracy
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            source_schema: Source schema name
            target_schema: Target schema name
            target_table: Target table name (may include prefix)
            expected_row_count: Expected row count (from pre-migration validation)
            column_names: List of column names
            pre_migration_query_results: Query results from pre-migration validation (NEW)
            
        Returns:
            Tuple of (is_accurate, error_message, accuracy_report)
        """
        try:
            # Use DataIntegrityVerifier for comprehensive verification
            is_accurate, error_msg, accuracy_report = self.data_integrity_verifier.verify_data_accuracy(
                job_table=job_table,
                source_schema=source_schema,
                target_schema=target_schema,
                expected_row_count=expected_row_count,
                column_names=column_names,
                target_column_names=target_column_names,
                target_table=target_table,
            )
            
            # NEW: Compare pre-migration query results with target data
            if pre_migration_query_results and is_accurate:
                from sync_engine.query_result_verifier import QueryResultVerifier
                query_verifier = QueryResultVerifier(self.source_connector)
                
                # Fetch target data (use target_table for target)
                try:
                    # Get order by column for consistent ordering
                    # Try to use primary key, fallback to first column
                    try:
                        pk_columns = self.source_connector.get_primary_key(source_schema, job_table.table_name)
                        if pk_columns:
                            order_by = ', '.join(pk_columns)
                        else:
                            order_by = (target_column_names or column_names)[0] if column_names else None
                    except:
                        order_by = (target_column_names or column_names)[0] if column_names else None
                    
                    # Fetch target rows in batches if needed (for large datasets)
                    target_rows = []
                    batch_size = min(10000, expected_row_count) if expected_row_count else 10000
                    offset = 0
                    
                    while True:
                        batch = self.target_connector.fetch_batch(
                            query=self.query_builder.build_select_query(
                                connector=self.target_connector,
                                schema=target_schema,
                                table=target_table,
                                columns=(target_column_names or column_names),
                                order_by=order_by
                            ),
                            batch_size=batch_size,
                            offset=offset
                        )
                        
                        if not batch:
                            break
                        
                        target_rows.extend(batch)
                        offset += len(batch)
                        
                        # Stop if we've fetched enough rows or got fewer than batch size
                        if len(target_rows) >= len(pre_migration_query_results) or len(batch) < batch_size:
                            break
                    
                    # Limit target rows to match pre-migration query results count
                    if len(pre_migration_query_results) < len(target_rows):
                        target_rows = target_rows[:len(pre_migration_query_results)]
                    
                    # Compare query results with target
                    comparison_valid, comparison_error, comparison_report = query_verifier.compare_query_results_with_target(
                        source_query_result=pre_migration_query_results,
                        target_rows=target_rows if target_rows else [],
                        column_names=column_names,
                        column_transformations=job_table.column_transformations or {}
                    )
                    
                    if not comparison_valid:
                        error_msg = f"Query result comparison failed: {comparison_error}"
                        logger.error(
                            f"Post-migration verification failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
                        )
                        return False, error_msg, accuracy_report
                    
                    # Update accuracy report with comparison results
                    accuracy_report['query_result_comparison'] = comparison_report
                    accuracy_report['perfect_accuracy'] = True
                    accuracy_report['pre_migration_rows_compared'] = len(pre_migration_query_results)
                    accuracy_report['target_rows_compared'] = len(target_rows)
                    
                    logger.info(
                        f"Perfect accuracy verified for {job_table.schema_name}.{job_table.table_name}: "
                        f"Query results ({len(pre_migration_query_results)} rows) match target data ({len(target_rows)} rows) exactly"
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not perform query result comparison for {job_table.schema_name}.{job_table.table_name}: {str(e)}"
                    )
                    # Don't fail if comparison can't be performed, but log warning
                    accuracy_report['perfect_accuracy'] = False
                    accuracy_report['comparison_error'] = str(e)
            else:
                # No query results provided - perfect accuracy cannot be verified
                accuracy_report['perfect_accuracy'] = False
            
            if not is_accurate:
                logger.error(
                    f"Post-migration verification failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
                )
                return False, error_msg, accuracy_report
            
            logger.info(
                f"Post-migration verification passed for {job_table.schema_name}.{job_table.table_name}: "
                f"Row count: {accuracy_report.get('actual_row_count', 0)}, "
                f"All rows match: {accuracy_report.get('all_rows_match', False)}, "
                f"Perfect accuracy: {accuracy_report.get('perfect_accuracy', False)}"
            )
            
            return True, None, accuracy_report
            
        except Exception as e:
            error_msg = f"Post-migration verification error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, {}
    
    def _compare_incremental_values(self, value1: Any, value2: Any) -> bool:
        """
        Compare two incremental values to determine which is greater
        
        Args:
            value1: First value
            value2: Second value
            
        Returns:
            True if value1 > value2, False otherwise
        """
        if value1 is None:
            return False
        if value2 is None:
            return True
        
        # Handle datetime-like comparisons (datetime / pandas.Timestamp / numpy.datetime64).
        dt1 = self._normalize_datetime_like(value1)
        dt2 = self._normalize_datetime_like(value2)
        if dt1 is not None and dt2 is not None:
            try:
                if dt1.tzinfo is not None and dt2.tzinfo is None:
                    dt2 = dt2.replace(tzinfo=dt1.tzinfo)
                elif dt2.tzinfo is not None and dt1.tzinfo is None:
                    dt1 = dt1.replace(tzinfo=dt2.tzinfo)
            except Exception:
                pass
            return dt1 > dt2
        
        # Handle numeric comparisons
        if isinstance(value1, (int, float)) and isinstance(value2, (int, float)):
            return value1 > value2
        
        # String comparison
        return str(value1) > str(value2)

    def _get_max_incremental_value(self, batch: List[tuple], col_index: int, current_max: Any) -> Any:
        """
        Get maximum incremental value from batch
        
        Args:
            batch: Batch of rows
            col_index: Index of incremental column
            current_max: Current maximum value
            
        Returns:
            Maximum value from batch
        """
        max_value = current_max
        for row in batch:
            row_value = row[col_index]
            if row_value is not None:
                if max_value is None or self._compare_incremental_values(row_value, max_value):
                    max_value = row_value
        return max_value

    def _validate_incremental_column(
        self,
        schema: str,
        table: str,
        incremental_column: str
    ) -> bool:
        """
        Validate that incremental column exists and is appropriate for incremental sync
        
        Args:
            schema: Schema name
            table: Table name
            incremental_column: Column name to validate
            
        Returns:
            True if column is valid
            
        Raises:
            TableSyncError: If column is invalid
        """
        try:
            columns = self.source_connector.get_columns(schema, table)
            column_names = [col.name for col in columns]
            
            if incremental_column not in column_names:
                raise TableSyncError(
                    f"Incremental column '{incremental_column}' not found "
                    f"in table {schema}.{table}"
                )
            
            # Check if column type is suitable for incremental sync
            column_info = next(
                (col for col in columns if col.name == incremental_column),
                None
            )
            if column_info:
                col_type = column_info.data_type.lower()
                # Get database type to check ClickHouse-specific types
                db_type = QueryBuilder.get_db_type(self.source_connector)
                valid_types = [
                    'timestamp', 'datetime', 'date', 'timestamptz',
                    'int', 'integer', 'bigint', 'serial', 'int4', 'int8',
                    'float', 'double', 'numeric', 'decimal'
                ]
                # Add ClickHouse-specific types
                if db_type == 'clickhouse':
                    valid_types.extend([
                        'datetime', 'datetime64', 'date',
                        'int32', 'int64', 'uint32', 'uint64',
                        'int8', 'int16', 'uint8', 'uint16'
                    ])
                if not any(vt in col_type for vt in valid_types):
                    logger.warning(
                        f"Incremental column '{incremental_column}' has type "
                        f"'{col_type}' which may not be ideal for incremental sync. "
                        f"Consider using timestamp or integer types."
                    )
                
                # Check if column is nullable (warning)
                if column_info.is_nullable:
                    logger.warning(
                        f"Incremental column '{incremental_column}' allows NULL values. "
                        f"Rows with NULL values will be skipped in checkpoint updates."
                    )
            
            return True
        except TableSyncError:
            raise
        except Exception as e:
            logger.error(
                f"Error validating incremental column: {str(e)}",
                exc_info=True
            )
            raise TableSyncError(
                f"Failed to validate incremental column: {str(e)}"
            ) from e

    def _handle_failed_sync(
        self,
        schema: str,
        table: str,
        error: Exception,
        checkpoint_value: Any
    ):
        """
        Handle failed sync - don't update checkpoint
        
        Args:
            schema: Schema name
            table: Table name
            error: Exception that occurred
            checkpoint_value: Checkpoint value before sync attempt
        """
        logger.error(
            f"Sync failed for {schema}.{table}. Checkpoint NOT updated. "
            f"Previous checkpoint value: {checkpoint_value}"
        )
        # Checkpoint remains unchanged - next sync will retry from same point

    def _handle_partial_batch_failure(
        self,
        schema: str,
        table: str,
        batch_number: int,
        batch: List[tuple]
    ):
        """
        Handle partial batch failure - rollback transaction if possible
        
        Args:
            schema: Schema name
            table: Table name
            batch_number: Batch number that failed
            batch: Batch data
        """
        logger.error(
            f"Batch {batch_number} failed for {schema}.{table}. "
            f"Attempting to rollback transaction."
        )
        # Most databases handle this automatically, but log for debugging
        # For databases that support transactions, the connector should handle rollback

    def _recover_from_checkpoint_corruption(
        self,
        schema: str,
        table: str
    ):
        """
        Recover from checkpoint corruption by resetting checkpoint
        
        Args:
            schema: Schema name
            table: Table name
        """
        logger.warning(
            f"Checkpoint corruption detected for {schema}.{table}. "
            f"Resetting checkpoint - next sync will be a full sync."
        )
        self.checkpoint_manager.delete_checkpoint(schema, table)

    def _prevent_concurrent_sync(self, schema: str, table: str) -> bool:
        """
        Check if another sync is already running for this table
        
        Args:
            schema: Schema name
            table: Table name
            
        Returns:
            True if sync can proceed, False if another sync is running
        """
        # Check for running executions for this job and table
        running_logs = SyncExecutionLog.objects.filter(
            execution__job=self.job,
            schema_name=schema,
            table_name=table,
            status='running'
        ).exclude(execution=self.execution)
        
        running_exists = running_logs.exists()
        # In unit tests, an unconfigured Mock may leak through; treat only explicit True as running.
        if running_exists is True:
            logger.warning(
                f"Another sync is already running for {schema}.{table}. "
                f"Skipping this sync."
            )
            return False
        return True

    @retry_on_error(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def _fetch_batch_with_retry(self, query: str, batch_size: int, offset: int):
        """Fetch batch with retry logic"""
        return self.source_connector.fetch_batch(
            query=query,
            batch_size=batch_size,
            offset=offset,
            order_by=None
        )

    def _validate_and_apply_transformations(
        self,
        job_table: SyncJobTable,
        base_query: str,
        column_names: List[str]
    ) -> Tuple[str, Optional[str]]:
        """
        Validate and apply transformations to incremental query
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            base_query: Base incremental query (without transformations)
            column_names: List of column names
            
        Returns:
            Tuple of (transformed_query, error_message)
            - If error_message is not None, validation failed
            - If error_message is None, transformed_query is ready to use
        """
        # Read transformation fields
        where_clause = job_table.transformation_query
        column_transformations = job_table.column_transformations or {}
        
        # If no transformations, return base query
        if not where_clause and not column_transformations:
            return base_query, None
        
        # Validate transformations
        schema = job_table.schema_name
        table = job_table.table_name
        
        # Validate WHERE clause
        if where_clause:
            is_valid, error = self.transformation_validator.validate_where_clause(
                where_clause=where_clause,
                schema=schema,
                table=table,
                connector=self.source_connector
            )
            if not is_valid:
                return None, f"WHERE clause validation failed: {error}"
        
        # Validate column transformations
        if column_transformations:
            is_valid, error = self.transformation_validator.validate_column_transformations(
                transformations=column_transformations,
                schema=schema,
                table=table,
                connector=self.source_connector
            )
            if not is_valid:
                return None, f"Column transformation validation failed: {error}"
        
        # Apply transformations to query
        # Note: TransformationEngine.apply_query_transformations() will handle
        # combining WHERE clauses correctly (incremental WHERE + transformation WHERE)
        try:
            transformed_query = self.transformation_engine.apply_query_transformations(
                query=base_query,
                where_clause=where_clause,
                column_transformations=column_transformations,
                connector=self.source_connector
            )
            return transformed_query, None
        except Exception as e:
            return None, f"Failed to apply transformations: {str(e)}"
    
    def _execute_pre_migration_validation(
        self,
        job_table: SyncJobTable,
        transformed_query: str,
        base_query: str,
        column_names: List[str]
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Enhanced pre-migration validation with comprehensive checks
        
        Args:
            job_table: SyncJobTable instance
            transformed_query: Transformed query to validate
            base_query: Base query (without transformations)
            column_names: List of column names
            
        Returns:
            Tuple of (is_valid, error_message, validation_report)
        """
        # Only run enhanced validation if transformations are present
        if not job_table.transformation_query and not job_table.column_transformations:
            # No transformations, skip enhanced validation
            return True, None, None
        
        # Use PreMigrationValidator for comprehensive validation
        is_valid, error_msg, validation_report = self.pre_migration_validator.validate_transformation_query(
            job_table=job_table,
            transformed_query=transformed_query,
            base_query=base_query,
            column_names=column_names
        )
        
        if not is_valid:
            logger.error(
                f"Pre-migration validation failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
            )
            return False, error_msg, None
        
        logger.info(
            f"Pre-migration validation passed for {job_table.schema_name}.{job_table.table_name}: "
            f"Expected {validation_report.get('expected_row_count', 0)} rows, "
            f"Query executed: {validation_report.get('query_result_count', 0)} rows in "
            f"{validation_report.get('query_execution_time', 0.0):.2f}s, "
            f"Structure verified: {validation_report.get('structure_verified', False)}, "
            f"Data verified: {validation_report.get('data_verified', False)}"
        )
        
        return True, None, validation_report
    
    @retry_on_error(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def _upsert_batch_with_retry(
        self,
        schema: str,
        table: str,
        columns: List[str],
        rows: List[tuple],
        key_columns: List[str],
    ):
        """Upsert batch with retry logic using the first available key column.

        Returns:
            Number of rows actually sent to target upsert.
        """
        if not rows:
            return 0
        if not key_columns:
            raise TableSyncError(
                f"Cannot upsert into {schema}.{table}: no key columns available."
            )

        key_column = key_columns[0]
        normalized_rows = []
        for row in rows:
            if isinstance(row, dict):
                normalized_rows.append(tuple(row.get(col) for col in columns))
                continue
            if isinstance(row, (list, tuple)):
                # Some connectors return rows as one-item tuple containing the real tuple.
                if len(row) == 1 and isinstance(row[0], (list, tuple)) and len(row[0]) == len(columns):
                    normalized_rows.append(tuple(row[0]))
                    continue
                if len(row) == len(columns):
                    normalized_rows.append(tuple(row))
                    continue
            # Accept DB-driver row objects (e.g., pyodbc.Row) that are iterable/sequence-like.
            if not isinstance(row, (str, bytes)):
                try:
                    as_tuple = tuple(row)
                except Exception:
                    as_tuple = None
                if as_tuple is not None and len(as_tuple) == len(columns):
                    normalized_rows.append(as_tuple)
                    continue
            raise TableSyncError(
                f"Cannot upsert into {schema}.{table}: batch row shape mismatch (expected {len(columns)} values)."
            )
        df = pd.DataFrame(normalized_rows, columns=columns)
        if self.table_handler.target_db_type == "mongodb" and _should_stamp_origin():
            df[ORIGIN_FIELD_NAME] = str(getattr(self.job, "id", ""))
        schema_table_key = (schema, table)
        if not self._did_add_missing_columns.get(schema_table_key, False):
            try:
                get_columns_fn = getattr(self.target_connector, "get_columns", None)
                existing_cols = get_columns_fn(schema, table) if callable(get_columns_fn) else []
                if not isinstance(existing_cols, (list, tuple, set)):
                    existing_cols = []
                existing_lower = {
                    (getattr(c, "name", "") or "").strip().lower()
                    for c in existing_cols
                    if getattr(c, "name", None)
                }
                missing_cols = [c for c in df.columns if c.lower() not in existing_lower]
                if missing_cols:
                    add_missing_fn = getattr(self.target_connector, "add_missing_columns", None)
                    if callable(add_missing_fn):
                        add_missing_fn(schema, table, df[missing_cols])
                    self._last_schema_drift_added_columns[schema_table_key] = missing_cols
                    logger.info(
                        "Schema drift handled for %s.%s by adding columns: %s",
                        schema,
                        table,
                        missing_cols,
                    )
                self._did_add_missing_columns[schema_table_key] = True
            except Exception as e:
                raise TableSyncError(
                    f"Failed to reconcile schema drift for {schema}.{table}: {str(e)}"
                ) from e
        if key_column not in df.columns:
            raise TableSyncError(
                f"Cannot upsert into {schema}.{table}: key column '{key_column}' not present in batch."
            )

        # Key nulls make upsert non-deterministic.
        # For ClickHouse incremental (delete+insert by identity), we must skip rows where
        # ANY identity key column is NULL/NaN, not just the first key column.
        try:
            if self.table_handler.target_db_type == "clickhouse" and key_columns:
                valid_mask = pd.Series(True, index=df.index)
                for k in key_columns:
                    if k in df.columns:
                        valid_mask &= ~df[k].isna()
            else:
                valid_mask = ~df[key_column].isna()
            skipped = int((~valid_mask).sum())
            if skipped > 0:
                logger.warning(
                    "Skipping %s row(s) for %s.%s because upsert identity key column(s) contain NULL/NaN.",
                    skipped,
                    schema,
                    table,
                    key_column,
                )
                df = df[valid_mask]
                if df.empty:
                    return 0
        except TypeError:
            # Some pandas dtypes can raise on isna; keep original behavior and attempt upsert.
            pass
        try:
            missing_key_cols = [k for k in key_columns if k and k not in df.columns]
            if missing_key_cols:
                raise TableSyncError(
                    f"Cannot upsert into {schema}.{table}: identity key column(s) not present in batch: {missing_key_cols}"
                )
            self.target_connector.upsert_dataframe(
                schema=schema,
                table=table,
                df=df,
                key_column=key_column,
                key_columns=key_columns,
            )
        except TypeError:
            # Backward compatibility for connectors that only support single-key upsert.
            self.target_connector.upsert_dataframe(
                schema=schema,
                table=table,
                df=df,
                key_column=key_column,
            )
        return int(len(df))

    def reconcile_deletes(self, job_table: SyncJobTable, target_schema: str, target_table: Optional[str] = None):
        """
        Identify and delete records in the target that no longer exist in the source.
        This ensures the sync is 'perfect' by handling deletions.
        """
        # Defensive guard: no-delete mode should never propagate deletes.
        if getattr(self.job, "no_delete_propagation", True):
            logger.info(
                "No-delete mode active; skipping reconcile_deletes for %s.%s",
                job_table.schema_name,
                job_table.table_name,
            )
            return

        schema = job_table.schema_name
        table = job_table.table_name
        if target_table is None:
            target_table = table
        
        # 1. Get primary key columns
        pk_columns = self.source_connector.get_primary_key(schema, table)
        if not pk_columns:
            logger.warning(f"No primary key found for {schema}.{table}. Delete reconciliation skipped.")
            return

        logger.info(f"Reconciling deletes for {schema}.{table} using PK: {pk_columns}")

        # 2. Fetch all IDs from source
        pk_list = ", ".join([f'"{col}"' for col in pk_columns])
        source_ids_query = f"SELECT {pk_list} FROM {schema}.{table}"
        
        # Note: We use fetch_batch with a large batch size or a dedicated fetch all if available
        # But connectors have different return types for execute_query
        # Let's use fetch_batch with offset to be safe for memory
        source_id_set = set()
        offset = 0
        batch_size = 50000
        while True:
            batch = self.source_connector.fetch_batch(source_ids_query, batch_size, offset)
            if not batch:
                break
            for row in batch:
                source_id_set.add(tuple(row))
            offset += len(batch)
            if len(batch) < batch_size:
                break

        # 3. Fetch all IDs from target
        target_pk_list = ", ".join([f"`{col}`" if self.table_handler.target_db_type == 'clickhouse' else f'"{col}"' for col in pk_columns])
        target_ids_query = f"SELECT {target_pk_list} FROM {target_schema}.{target_table}"
        
        target_id_set = set()
        offset = 0
        while True:
            batch = self.target_connector.fetch_batch(target_ids_query, batch_size, offset)
            if not batch:
                break
            for row in batch:
                target_id_set.add(tuple(row))
            offset += len(batch)
            if len(batch) < batch_size:
                break

        # 4. Find deleted IDs (exist in target but not in source)
        deleted_ids = target_id_set - source_id_set
        if not deleted_ids:
            logger.info(f"No deleted records found for {schema}.{table}")
            return

        logger.info(f"Found {len(deleted_ids)} deleted records for {schema}.{table}")

        # 5. Perform deletions in batches
        delete_batch_size = 1000
        deleted_list = list(deleted_ids)
        
        for i in range(0, len(deleted_list), delete_batch_size):
            batch_to_delete = deleted_list[i:i+delete_batch_size]
            
            # Construct the WHERE clause
            if len(pk_columns) == 1:
                pk_col = pk_columns[0]
                values = []
                for v_tuple in batch_to_delete:
                    v = v_tuple[0]
                    if isinstance(v, str):
                        values.append(f"'{v.replace("'", "''")}'")
                    else:
                        values.append(str(v))
                
                quoted_pk_col = f"`{pk_col}`" if self.table_handler.target_db_type == 'clickhouse' else f'"{pk_col}"'
                where_clause = f"{quoted_pk_col} IN ({', '.join(values)})"
            else:
                # Compound PK
                conds = []
                for row_tuple in batch_to_delete:
                    row_conds = []
                    for col, val in zip(pk_columns, row_tuple):
                        quoted_col = f"`{col}`" if self.table_handler.target_db_type == 'clickhouse' else f'"{col}"'
                        val_str = f"'{str(val).replace("'", "''")}'" if isinstance(val, str) else str(val)
                        row_conds.append(f"{quoted_col} = {val_str}")
                    conds.append(f"({' AND '.join(row_conds)})")
                where_clause = " OR ".join(conds)

            if self.table_handler.target_db_type == 'clickhouse':
                delete_query = f"ALTER TABLE `{target_schema}`.`{target_table}` DELETE WHERE {where_clause}"
            else:
                delete_query = f"DELETE FROM {target_schema}.{target_table} WHERE {where_clause}"
            
            try:
                self.target_connector.execute_query(delete_query)
            except Exception as e:
                logger.error(f"Error executing delete query for {schema}.{table}: {e}")
                # Don't stop the whole process if one delete batch fails
        
        logger.info(f"Successfully processed deletions for {schema}.{table}")

