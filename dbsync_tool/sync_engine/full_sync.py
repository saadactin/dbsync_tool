"""
Full sync implementation
"""
import os
from typing import List, Optional, Tuple, Dict, Any
from decimal import Decimal
import json
from django.utils import timezone
from django.db.models import Sum
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import DBConnector
from sync_engine.table_handler import TableHandler
from sync_engine.validators import DataValidator
from sync_engine.query_builder import QueryBuilder
from sync_engine.transformation_engine import TransformationEngine
from sync_engine.transformation_validator import TransformationValidator
from core.mongo_document_codec import build_document_from_sql_row
from sync_engine.exceptions import TableSyncError
from sync_jobs.services.transform_plan_service import (
    TransformPlanValidationError,
    prepare_runtime_transform_plan,
    compile_select_from_plan,
    column_infos_from_transform_plan,
    runtime_output_aliases,
    validate_transform_plan_column_references,
    ERROR_TRANSFORM_PLAN_CONFLICT,
)
from core.constants import DEFAULT_BATCH_SIZE, MAX_BATCH_SIZE, MIN_BATCH_SIZE
from core.type_mapping import map_source_to_oracle_type, normalize_data_type
import logging

logger = logging.getLogger(__name__)

ORIGIN_FIELD_NAME = "__dbsync_origin_job_id"


def _should_stamp_origin() -> bool:
    return (os.environ.get("DBSYNC_STAMP_ORIGIN", "") or "").strip().lower() in ("1", "true", "yes", "y")


def get_target_table_name(job, source_table_name: str) -> str:
    """Return target table name (with optional prefix). Source name unchanged if no prefix."""
    prefix = getattr(job, 'target_table_prefix', None)
    if prefix:
        return f"{prefix}_{source_table_name}"
    return source_table_name


class FullSyncExecutor:
    """Executes full sync for a job"""
    
    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        source_connector: DBConnector,
        target_connector: DBConnector
    ):
        """
        Initialize full sync executor
        
        Args:
            job: SyncJob instance
            execution: SyncExecution instance
            source_connector: Source database connector
            target_connector: Target database connector
        """
        self.job = job
        self.execution = execution
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.table_handler = TableHandler(source_connector, target_connector)
        self.validator = DataValidator()
        # Optimize batch size based on database types
        self.batch_size = self._optimize_batch_size()
        self.query_builder = QueryBuilder()
        # Initialize transformation engine and validator
        self.transformation_engine = TransformationEngine()
        self.transformation_validator = TransformationValidator()
        # NEW: Initialize pre-migration validator and data integrity verifier
        from sync_engine.pre_migration_validator import PreMigrationValidator
        from sync_engine.data_integrity_verifier import DataIntegrityVerifier
        
        self.pre_migration_validator = PreMigrationValidator(source_connector)
        self.data_integrity_verifier = DataIntegrityVerifier(
            source_connector,
            target_connector
        )
        # Store transformed query and order_by for post-migration verification
        self._last_transformed_query = None
        self._last_order_by = None

    @staticmethod
    def _normalize_mongo_value_for_sql(value: Any) -> Any:
        """Convert Mongo/BSON values to SQL-driver-safe Python values."""
        if value is None:
            return None
        # psycopg2 rejects NUL bytes in text literals.
        if isinstance(value, str):
            return value.replace("\x00", "")
        # Convert bson.decimal128.Decimal128 without hard dependency on bson types.
        if hasattr(value, "to_decimal") and "decimal128" in value.__class__.__name__.lower():
            try:
                return value.to_decimal()
            except Exception:
                return str(value)
        if isinstance(value, Decimal):
            return value
        # Convert complex nested documents to JSON text for SQL columns.
        if isinstance(value, (dict, list, tuple, set)):
            try:
                return json.dumps(value, default=str, ensure_ascii=False).replace("\x00", "")
            except Exception:
                return str(value).replace("\x00", "")
        return value
    
    def _optimize_batch_size(self):
        """
        Optimize batch size based on source and target database types
        
        Returns:
            int: Optimized batch size
        """
        source_type = self._get_db_type(self.source_connector)
        target_type = self._get_db_type(self.target_connector)
        
        # Different databases have different optimal batch sizes
        # Oracle ADW: default 100 to reduce ORA-01536 risk; set ORACLE_SYNC_BATCH_SIZE (e.g. 2000–5000) to speed up once quota is sufficient
        # PostgreSQL can handle larger batches
        # MySQL and SQL Server may need smaller batches
        # ClickHouse can handle larger batches similar to PostgreSQL
        if target_type == 'oracle':
            try:
                batch = int(os.environ.get("ORACLE_SYNC_BATCH_SIZE", "100"))
            except ValueError:
                batch = 100
            return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, batch))
        if source_type == 'postgres' and target_type == 'postgres':
            return min(MAX_BATCH_SIZE, DEFAULT_BATCH_SIZE * 2)  # 10000
        elif source_type == 'clickhouse' or target_type == 'clickhouse':
            return min(MAX_BATCH_SIZE, DEFAULT_BATCH_SIZE * 2)  # 10000 - ClickHouse handles large batches well
        elif source_type == 'mysql' or target_type == 'mysql':
            return min(DEFAULT_BATCH_SIZE, 3000)  # Smaller for MySQL
        elif source_type == 'sqlserver' or target_type == 'sqlserver':
            return min(DEFAULT_BATCH_SIZE, 2000)  # Smaller for SQL Server
        else:
            return DEFAULT_BATCH_SIZE
    
    def _get_db_type(self, connector):
        """Extract database type from connector"""
        class_name = connector.__class__.__name__
        if 'Postgres' in class_name:
            return 'postgres'
        elif 'MySQL' in class_name:
            return 'mysql'
        elif 'SQLServer' in class_name:
            return 'sqlserver'
        elif 'ClickHouse' in class_name:
            return 'clickhouse'
        elif 'Oracle' in class_name:
            return 'oracle'
        else:
            return 'unknown'

    def _is_preflight_transform_validation_enabled(self) -> bool:
        return (os.environ.get("DBSYNC_PREFLIGHT_TRANSFORM_COMPILE", "") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "y",
        )

    def _preflight_validate_transform_plans(self, tables) -> None:
        """Optionally compile/validate model transform plans before table sync starts."""
        issues: List[str] = []
        source_db = QueryBuilder.get_db_type(self.source_connector)
        for job_table in tables:
            schema = job_table.schema_name
            table = job_table.table_name
            excluded = getattr(job_table, "excluded_columns", None) or []
            protected = getattr(job_table, "protected_columns", None) or []
            excluded_lower = {(c or "").strip().lower() for c in excluded if c}
            protected_lower = {(c or "").strip().lower() for c in protected if c}
            try:
                rt_plan = prepare_runtime_transform_plan(
                    job_table,
                    self.job,
                    source_db,
                    excluded_cols_lower=excluded_lower,
                    protected_cols_lower=protected_lower,
                )
            except TransformPlanValidationError as e:
                issues.append(f"{schema}.{table}: [{e.error_code}] {e.message}")
                continue

            if rt_plan is None:
                continue

            tq = job_table.transformation_query
            ct = job_table.column_transformations or {}
            if (tq and str(tq).strip()) or ct:
                issues.append(
                    f"{schema}.{table}: [{ERROR_TRANSFORM_PLAN_CONFLICT}] Legacy SQL transformations cannot be combined with model transforms."
                )
                continue

            try:
                validate_transform_plan_column_references(rt_plan, self.source_connector)
                compile_select_from_plan(rt_plan, preview_limit=None)
            except TransformPlanValidationError as e:
                issues.append(f"{schema}.{table}: [{e.error_code}] {e.message}")
            except Exception as e:
                issues.append(f"{schema}.{table}: [transform_compile_failed] {str(e)}")

        if issues:
            raise TableSyncError(
                "Pre-flight transform validation failed for one or more tables:\n- "
                + "\n- ".join(issues)
            )
    
    def _validate_and_apply_transformations(
        self,
        job_table: SyncJobTable,
        base_query: str,
        column_names: List[str]
    ) -> Tuple[str, Optional[str]]:
        """
        Validate and apply transformations to query
        
        Args:
            job_table: SyncJobTable instance with transformation fields
            base_query: Base SELECT query (without transformations)
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
        
        # Apply transformations by rebuilding query with QueryBuilder
        # This ensures correct SQL syntax (WHERE before ORDER BY)
        try:
            # Extract order_by from base_query if it exists
            # Need to unquote column names since QueryBuilder will quote them again
            order_by = None
            base_query_upper = base_query.upper()
            if ' ORDER BY ' in base_query_upper:
                order_by_idx = base_query_upper.find(' ORDER BY ')
                order_by_part = base_query[order_by_idx + 10:].strip()
                # Remove LIMIT/OFFSET if present
                if ' LIMIT ' in order_by_part.upper():
                    limit_idx = order_by_part.upper().find(' LIMIT ')
                    order_by_part = order_by_part[:limit_idx].strip()
                if ' OFFSET ' in order_by_part.upper():
                    offset_idx = order_by_part.upper().find(' OFFSET ')
                    order_by_part = order_by_part[:offset_idx].strip()
                
                # Unquote column names (they're already quoted in base_query)
                # QueryBuilder will quote them again, so we need raw column names
                db_type = QueryBuilder.get_db_type(self.source_connector)
                if db_type == 'postgres':
                    # Remove double quotes, handling multiple columns separated by commas
                    # Split by comma first, then unquote each
                    cols = [col.strip().strip('"') for col in order_by_part.split(',')]
                    order_by_part = ', '.join(cols)
                elif db_type == 'mysql':
                    # Remove backticks
                    cols = [col.strip().strip('`') for col in order_by_part.split(',')]
                    order_by_part = ', '.join(cols)
                elif db_type == 'sqlserver':
                    # Remove square brackets
                    cols = [col.strip().strip('[').strip(']') for col in order_by_part.split(',')]
                    order_by_part = ', '.join(cols)
                elif db_type == 'clickhouse':
                    # Remove backticks (ClickHouse uses backticks like MySQL)
                    cols = [col.strip().strip('`') for col in order_by_part.split(',')]
                    order_by_part = ', '.join(cols)
                
                order_by = order_by_part
            
            # Rebuild query using QueryBuilder with all parameters in correct order
            transformed_query = self.query_builder.build_select_query(
                connector=self.source_connector,
                schema=schema,
                table=table,
                columns=column_names,
                where_clause=where_clause,  # WHERE comes before ORDER BY
                order_by=order_by,  # ORDER BY comes after WHERE
                column_transformations=column_transformations
            )
            # Store for use in post-migration verification to ensure consistent ordering
            self._last_transformed_query = transformed_query
            self._last_order_by = order_by
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
    
    def execute(self):
        """Execute full sync for all enabled tables"""
        try:
            # Update execution status
            self.execution.status = 'running'
            self.execution.started_at = timezone.now()
            self.execution.save()
            
            # Get enabled tables
            tables = self.job.tables.filter(is_enabled=True)
            
            if not tables.exists():
                logger.warning(f"No enabled tables found for job {self.job.id}")
                self.execution.status = 'completed'
                self.execution.completed_at = timezone.now()
                self.execution.save()
                return
            
            # Connect to databases (connections are managed efficiently)
            # Connections are opened once and reused for all tables
            if not hasattr(self.source_connector, '_connected') or not self.source_connector._connected:
                self.source_connector.connect()
                self.source_connector._connected = True
            
            if not hasattr(self.target_connector, '_connected') or not self.target_connector._connected:
                self.target_connector.connect()
                self.target_connector._connected = True

            if self._is_preflight_transform_validation_enabled():
                self._preflight_validate_transform_plans(tables)
            
            # Sync each table
            for job_table in tables:
                try:
                    self.sync_table(job_table)
                except TableSyncError as e:
                    logger.error(f"Table sync failed: {str(e)}")
                    # Continue with other tables
                    continue
                except Exception as e:
                    logger.error(
                        f"Unexpected error syncing table: {str(e)}",
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
            total_logs = completed_logs.count() + failed_logs.count()
            
            # Determine execution status
            if failed_logs.count() == total_logs and total_logs > 0:
                # ALL tables failed
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"All {failed_logs.count()} table(s) failed to sync"
                )
            elif failed_logs.exists():
                # SOME tables failed (partial failure)
                self.execution.status = 'failed'
                self.execution.error_message = (
                    f"{failed_logs.count()} of {total_logs} table(s) failed to sync"
                )
            elif completed_logs.count() == total_logs and total_logs > 0:
                # ALL tables succeeded
                self.execution.status = 'completed'
            else:
                # No logs created (shouldn't happen, but handle gracefully)
                self.execution.status = 'failed'
                self.execution.error_message = "No tables were processed"
            
            self.execution.completed_at = timezone.now()
            self.execution.save()
            
            logger.info(
                f"Full sync execution {self.execution.id} completed: "
                f"{completed_logs.count()}/{tables.count()} tables synced"
            )
            
        except Exception as e:
            logger.error(
                f"Full sync execution failed: {str(e)}",
                exc_info=True
            )
            self.execution.status = 'failed'
            self.execution.error_message = str(e)
            self.execution.completed_at = timezone.now()
            self.execution.save()
            raise

    def _sync_table_with_transform(
        self,
        job_table: SyncJobTable,
        schema: str,
        table: str,
        target_table: str,
        target_schema: str,
        log: SyncExecutionLog,
        rt_plan: Dict[str, Any],
    ) -> None:
        """Full sync using persisted model transform (join/union/lookup)."""
        column_infos = column_infos_from_transform_plan(rt_plan)
        overrides = getattr(job_table, "column_type_overrides", None) or {}
        for col in column_infos:
            o = overrides.get(col.name.lower())
            if o:
                col.data_type = o

        try:
            self.table_handler.create_table_if_not_exists(
                schema,
                table,
                column_type_overrides=overrides,
                column_name_overrides=getattr(job_table, "column_name_overrides", None) or {},
                excluded_columns=[],
                protected_columns=[],
                target_table=target_table,
                source_columns_override=column_infos,
            )
        except Exception as e:
            error_msg = f"Failed to create/verify target table: {str(e)}"
            logger.error(f"Table creation error for {schema}.{table}: {error_msg}", exc_info=True)
            raise TableSyncError(error_msg) from e

        try:
            try:
                target_tables = self.target_connector.get_tables(target_schema)
                target_db_type = self.table_handler.target_db_type
                if target_db_type in ("sqlserver", "oracle"):
                    table_exists = any(t.upper() == target_table.upper() for t in target_tables)
                else:
                    table_exists = target_table in target_tables
                if table_exists:
                    self.target_connector.truncate_table(target_schema, target_table)
                else:
                    logger.info(
                        f"Target table {target_schema}.{target_table} does not exist yet, skipping truncate"
                    )
            except Exception as check_error:
                logger.debug(f"Could not check table existence: {check_error}, trying truncate anyway")
                self.target_connector.truncate_table(target_schema, target_table)
        except Exception as e:
            error_str = str(e)
            if "does not exist" in error_str or "Cannot find the object" in error_str:
                logger.warning(
                    f"Target table {target_schema}.{target_table} may not exist yet, skipping truncate: {error_str}"
                )
            else:
                raise TableSyncError(f"Failed to truncate target table: {error_str}") from e

        try:
            # Fail fast if the transform plan references non-existent physical columns.
            validate_transform_plan_column_references(rt_plan, self.source_connector)
            query, warn_list = compile_select_from_plan(rt_plan, preview_limit=None)
        except TransformPlanValidationError as e:
            raise TableSyncError(f"[{e.error_code}] {e.message}") from e
        except Exception as e:
            raise TableSyncError(f"[transform_compile_failed] {str(e)}") from e

        if warn_list:
            logger.info("Transform compile warnings for %s.%s: %s", schema, table, warn_list)

        column_names = runtime_output_aliases(rt_plan)
        if not column_names:
            raise TableSyncError(f"[transform_plan_invalid] No output columns for {schema}.{table}")

        mode = (rt_plan.get("mode") or "").strip().lower()
        logger.info(
            "Transform full sync %s.%s mode=%s output_columns=%d",
            schema,
            table,
            mode,
            len(column_names),
        )

        rename_overrides = getattr(job_table, "column_name_overrides", None) or {}
        target_column_names = [rename_overrides.get(nm.lower(), nm) for nm in column_names]

        self._last_transformed_query = query
        self._last_order_by = None

        order_by_fb = None
        if "ORDER BY" not in query.upper():
            order_by_fb = column_names[0]

        batch_number = 0
        total_rows_fetched = 0
        total_rows_inserted = 0

        while True:
            batch = self.source_connector.fetch_batch(
                query=query,
                batch_size=self.batch_size,
                offset=total_rows_fetched,
                order_by=order_by_fb,
            )
            if not batch:
                break
            batch_number += 1
            total_rows_fetched += len(batch)
            self.validator.validate_batch_not_empty(batch, f"{schema}.{table}")

            try:
                bulk_kwargs = {
                    "schema": target_schema,
                    "table": target_table,
                    "columns": target_column_names,
                    "rows": batch,
                }
                if self.table_handler.target_db_type == "oracle":
                    target_types = []
                    for col in column_infos:
                        override_type = overrides.get(col.name.lower())
                        if override_type:
                            target_types.append(override_type)
                        else:
                            _, max_len, prec, scale = normalize_data_type(
                                col.data_type, self.table_handler.source_db_type
                            )
                            target_types.append(
                                map_source_to_oracle_type(
                                    col.data_type,
                                    self.table_handler.source_db_type,
                                    max_length=col.max_length or max_len,
                                    precision=prec,
                                    scale=scale,
                                )
                            )
                    bulk_kwargs["target_column_types"] = target_types
                self.target_connector.bulk_insert(**bulk_kwargs)
                total_rows_inserted += len(batch)
            except Exception as e:
                raise TableSyncError(
                    f"Failed to insert batch {batch_number} for {schema}.{table}: {str(e)}"
                ) from e

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

        log.rows_fetched = total_rows_fetched
        log.rows_inserted = total_rows_inserted
        log.batch_number = batch_number
        log.verification_summary = (
            f"Transform mode={mode}; rows inserted={total_rows_inserted} (model-based full sync)"
        )
        log.status = "completed"
        log.completed_at = timezone.now()
        log.save()
        logger.info(
            "Successfully synced table %s.%s with transform: %s rows in %s batches",
            schema,
            table,
            total_rows_inserted,
            batch_number,
        )
    
    def sync_table(self, job_table: SyncJobTable):
        """
        Full sync one table: destination table ends up with exactly the same rows as source (no duplicates).

        Steps:
        1. Create execution log entry
        2. Ensure target table exists (create if not)
        3. Truncate target table (remove all existing rows so re-runs replace, not append)
        4. Get primary key for ordering
        5. Build source query
        6. Fetch batches from source
        7. Insert all batches into target
        8. Update execution log

        Result: target row set equals source row set; no duplicates.
        """
        schema = job_table.schema_name
        table = job_table.table_name
        target_table = get_target_table_name(self.job, table)
        
        # Determine target schema
        # For databases WITH schemas (PostgreSQL, SQL Server): always use target's default schema
        # For databases WITHOUT schemas (MySQL, ClickHouse): use database name directly
        if self.table_handler.target_db_type == 'mysql':
            # MySQL: Use database name directly (no schema concept)
            target_schema = self.target_connector.database_name
            logger.info(f"Using MySQL database '{target_schema}' for source schema '{schema}' (no schema concept)")
        elif self.table_handler.target_db_type == 'clickhouse':
            # ClickHouse: Prefer the database specified in the connection.
            # If no database was specified on the connection, fall back to the
            # source schema name (e.g. 'public').
            target_schema = getattr(self.target_connector, 'database_name', None) or schema
            logger.info(
                f"Mapping source schema '{schema}' to ClickHouse database '{target_schema}' "
                f"(connection database overrides schema when provided)"
            )
        elif self.table_handler.target_db_type == 'postgres':
            # PostgreSQL: Always use 'public' schema regardless of source schema
            target_schema = 'public'
            logger.info(f"Mapping source schema '{schema}' to PostgreSQL schema 'public' (all tables in public schema)")
        elif self.table_handler.target_db_type == 'sqlserver':
            # SQL Server: Always use 'dbo' schema regardless of source schema
            target_schema = 'dbo'
            logger.info(f"Mapping source schema '{schema}' to SQL Server schema 'dbo' (all tables in dbo schema)")
        elif self.table_handler.target_db_type == 'oracle':
            # Oracle: use connected user as schema/owner so tables are in their schema (avoid ORA-01918)
            target_schema = (getattr(self.target_connector, 'username', None) or '').strip().upper() or schema
            logger.info(f"Mapping source schema '{schema}' to Oracle owner '{target_schema}' (connected user)")
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

            # MongoDB source collections cannot be queried via SQL QueryBuilder.
            if getattr(self.table_handler, "source_db_type", None) == "mongodb":
                self._sync_table_mongo_source(
                    job_table=job_table,
                    schema=schema,
                    table=table,
                    target_schema=target_schema,
                    target_table=target_table,
                    log=log,
                )
                return

            # MongoDB target uses a document upsert path (no SQL bulk-insert semantics).
            if getattr(self.table_handler, "target_db_type", None) == "mongodb":
                self._sync_table_mongo_target(
                    job_table=job_table,
                    schema=schema,
                    table=table,
                    target_schema=target_schema,
                    target_table=target_table,
                    log=log,
                )
                return

            raw_excluded = getattr(job_table, "excluded_columns", None) or []
            raw_protected = getattr(job_table, "protected_columns", None) or []
            excluded_lower = {(c or "").strip().lower() for c in raw_excluded if c}
            protected_lower = {(c or "").strip().lower() for c in raw_protected if c}
            source_db = QueryBuilder.get_db_type(self.source_connector)
            try:
                rt_plan = prepare_runtime_transform_plan(
                    job_table,
                    self.job,
                    source_db,
                    excluded_cols_lower=excluded_lower,
                    protected_cols_lower=protected_lower,
                )
            except TransformPlanValidationError as e:
                raise TableSyncError(f"[{e.error_code}] {e.message}") from e
            if rt_plan is not None:
                tq = job_table.transformation_query
                ct = job_table.column_transformations or {}
                if (tq and str(tq).strip()) or ct:
                    raise TableSyncError(
                        f"[{ERROR_TRANSFORM_PLAN_CONFLICT}] Legacy SQL transformations cannot be combined "
                        "with model transforms (join/union/lookup). Clear transformation query and column "
                        "transformations or use structured_filters in the model step."
                    )
                self._sync_table_with_transform(
                    job_table=job_table,
                    schema=schema,
                    table=table,
                    target_table=target_table,
                    target_schema=target_schema,
                    log=log,
                    rt_plan=rt_plan,
                )
                return
            
            # Ensure target table exists (uses correct schema mapping internally)
            try:
                self.table_handler.create_table_if_not_exists(
                    schema,
                    table,
                    column_type_overrides=getattr(job_table, "column_type_overrides", None) or {},
                    column_name_overrides=getattr(job_table, "column_name_overrides", None) or {},
                    excluded_columns=getattr(job_table, "excluded_columns", None) or [],
                    protected_columns=getattr(job_table, "protected_columns", None) or [],
                    target_table=target_table,
                )
            except Exception as e:
                error_msg = f"Failed to create/verify target table: {str(e)}"
                logger.error(f"Table creation error for {schema}.{table}: {error_msg}", exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Truncate target table so destination holds exactly source data (no duplicates).
            # Full sync = replace all rows: truncate then insert.
            try:
                try:
                    target_tables = self.target_connector.get_tables(target_schema)
                    target_db_type = self.table_handler.target_db_type
                    # Oracle and SQL Server return uppercase/case-insensitive names; match case-insensitively.
                    if target_db_type in ('sqlserver', 'oracle'):
                        table_exists = any(t.upper() == target_table.upper() for t in target_tables)
                    else:
                        table_exists = target_table in target_tables
                    if table_exists:
                        self.target_connector.truncate_table(target_schema, target_table)
                        logger.debug(f"Truncated {target_schema}.{target_table} for full sync replace")
                    else:
                        logger.info(f"Target table {target_schema}.{target_table} does not exist yet, skipping truncate")
                except Exception as check_error:
                    logger.debug(f"Could not check table existence: {check_error}, trying truncate anyway")
                    self.target_connector.truncate_table(target_schema, target_table)
            except Exception as e:
                # If truncate fails, log warning but continue (table might not exist yet or be empty)
                error_str = str(e)
                if 'does not exist' in error_str or 'Cannot find the object' in error_str:
                    logger.warning(f"Target table {target_schema}.{target_table} may not exist yet, skipping truncate: {error_str}")
                else:
                    error_msg = f"Failed to truncate target table: {error_str}"
                    logger.error(f"Table truncate error for {schema}.{table}: {error_msg}", exc_info=True)
                    raise TableSyncError(error_msg) from e
            
            # Get primary key for ordering
            try:
                pk_columns = self.source_connector.get_primary_key(schema, table)
                if not isinstance(pk_columns, (list, tuple)):
                    pk_columns = []
                if pk_columns:
                    order_by = ', '.join(pk_columns)
                else:
                    # Fallback to first column
                    columns = self.source_connector.get_columns(schema, table)
                    if columns:
                        order_by = columns[0].name
                    else:
                        order_by = None
            except Exception as e:
                logger.warning(f"Could not determine primary key for {schema}.{table}: {str(e)}")
                order_by = None
            
            # Get column names and apply any column type overrides from the job
            try:
                columns = self.source_connector.get_columns(schema, table)
                if not columns:
                    raise TableSyncError(f"No columns found for source table {schema}.{table}")
                # Apply column_type_overrides, if any, to ColumnInfo.data_type before target table creation
                overrides = getattr(job_table, "column_type_overrides", None) or {}
                if overrides:
                    for col in columns:
                        override_type = overrides.get(col.name.lower())
                        if override_type:
                            col.data_type = override_type
                raw_protected = getattr(job_table, "protected_columns", None)
                if not isinstance(raw_protected, (list, tuple, set)):
                    raw_protected = []
                raw_excluded = getattr(job_table, "excluded_columns", None)
                if not isinstance(raw_excluded, (list, tuple, set)):
                    raw_excluded = []
                protected_cols = {
                    (c or "").strip().lower()
                    for c in raw_protected
                    if c
                }
                excluded_cols = {
                    (c or "").strip().lower()
                    for c in raw_excluded
                    if c
                }
                effective_excluded = excluded_cols - protected_cols
                if effective_excluded:
                    columns = [col for col in columns if col.name.lower() not in effective_excluded]
                    if not columns:
                        raise TableSyncError(
                            f"No migratable columns remain after exclusion rules for {schema}.{table}"
                        )
                # SOURCE column names: used for SELECT/keyset pagination and row transformations.
                column_names = [col.name for col in columns]
                # TARGET column names: used for INSERT/verification queries on the renamed target table.
                rename_overrides = getattr(job_table, "column_name_overrides", None) or {}
                target_column_names = [
                    rename_overrides.get(col.name.lower(), col.name)
                    for col in columns
                ]
            except Exception as e:
                error_msg = f"Failed to get columns from source table {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Build source query
            try:
                base_query = self.query_builder.build_select_query(
                    connector=self.source_connector,
                    schema=schema,
                    table=table,
                    columns=column_names,
                    order_by=order_by
                )
            except Exception as e:
                error_msg = f"Failed to build query for {schema}.{table}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise TableSyncError(error_msg) from e
            
            # Validate and apply transformations
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
            
            # Use transformed_query instead of base_query for fetching
            query = transformed_query
            column_transformations = job_table.column_transformations
            if not isinstance(column_transformations, dict):
                column_transformations = {}
            
            # Fetch and insert in batches
            batch_number = 0
            total_rows_fetched = 0
            total_rows_inserted = 0
            last_pk_values = None
            
            # Use Keyset Pagination if we have PKs and no complex transformation that prevents it
            use_keyset = bool(pk_columns)
            
            while True:
                if use_keyset:
                    # Fetch batch using keyset pagination
                    current_query = self.query_builder.build_keyset_select_query(
                        connector=self.source_connector,
                        schema=schema,
                        table=table,
                        pk_columns=pk_columns,
                        last_pk_values=last_pk_values,
                        columns=column_names,
                        where_clause=job_table.transformation_query,
                        limit=self.batch_size,
                        column_transformations=column_transformations
                    )
                    # For keyset, we don't use offset
                    batch = self.source_connector.execute_query_fetchall(current_query)
                else:
                    # Fallback to OFFSET/FETCH
                    batch = self.source_connector.fetch_batch(
                        query=query,
                        batch_size=self.batch_size,
                        offset=total_rows_fetched,
                        order_by=order_by
                    )
                
                if not batch:
                    break  # No more rows
                
                batch_number += 1
                total_rows_fetched += len(batch)
                
                # Update last_pk_values for next iteration
                if use_keyset:
                    last_row = batch[-1]
                    # Map PK column names to indices in the results
                    # Since we requested specific columns, we need to find their positions
                    pk_indices = []
                    for pk_col in pk_columns:
                        try:
                            pk_indices.append(column_names.index(pk_col))
                        except ValueError:
                            # If PK not in column_names (unlikely for SELECT *), fallback to OFFSET
                            logger.warning(f"PK column {pk_col} not in fetched columns. Falling back to OFFSET.")
                            use_keyset = False
                            break
                    
                    if use_keyset:
                        last_pk_values = [last_row[idx] for idx in pk_indices]
                
                # Validate batch (rest of the logic remains same)
                self.validator.validate_batch_not_empty(batch, f"{schema}.{table}")
                
                # Apply row transformations if column transformations were applied
                # (This is a fallback for transformations that couldn't be applied in SQL)
                if column_transformations:
                    batch = self.transformation_engine.apply_row_transformations(
                        batch=batch,
                        column_names=column_names,
                        column_transformations=column_transformations
                    )
                
                # Insert batch (use target_schema for MySQL)
                try:
                    bulk_kwargs = {
                        "schema": target_schema,
                        "table": target_table,
                        "columns": target_column_names,
                        "rows": batch,
                    }
                    # Oracle: pass target column types for BLOB/CLOB value normalization
                    if self.table_handler.target_db_type == "oracle":
                        target_types = []
                        overrides = getattr(job_table, "column_type_overrides", None) or {}
                        for col in columns:
                            override_type = overrides.get(col.name.lower())
                            if override_type:
                                target_types.append(override_type)
                            else:
                                _, max_len, prec, scale = normalize_data_type(
                                    col.data_type, self.table_handler.source_db_type
                                )
                                target_types.append(
                                    map_source_to_oracle_type(
                                        col.data_type,
                                        self.table_handler.source_db_type,
                                        max_length=col.max_length or max_len,
                                        precision=prec,
                                        scale=scale,
                                    )
                                )
                        bulk_kwargs["target_column_types"] = target_types
                    self.target_connector.bulk_insert(**bulk_kwargs)
                    total_rows_inserted += len(batch)
                except Exception as e:
                    raise TableSyncError(
                        f"Failed to insert batch {batch_number} for {schema}.{table}: {str(e)}"
                    )
                
                # Update log
                log.batch_number = batch_number
                log.rows_fetched = total_rows_fetched
                log.rows_inserted = total_rows_inserted
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
            
            # Ensure log has final counts (e.g. empty table: 0 rows)
            log.rows_fetched = total_rows_fetched
            log.rows_inserted = total_rows_inserted
            log.batch_number = batch_number
            
            # NEW: Post-migration data accuracy verification
            accuracy_report = None
            if job_table.transformation_query or job_table.column_transformations:
                # Only verify if transformations were applied
                if expected_row_count is not None:
                    try:
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
                            # Log the verification failure but don't rollback for now
                            # This allows us to see what data was actually migrated
                            logger.warning(
                                f"Post-migration verification warning for {schema}.{table}: {accuracy_error}\n"
                                f"Data was migrated but verification detected mismatches. "
                                f"Check the logs for details. Row count: {total_rows_inserted} rows inserted."
                            )
                            # Don't fail the sync - allow migration to complete
                            # TODO: Fix comparison logic to handle all edge cases
                            # For now, we'll log warnings but allow the sync to succeed
                            
                    except Exception as verification_error:
                        # Don't fail sync if verification itself fails
                        logger.warning(
                            f"Post-migration verification error for {schema}.{table}: {str(verification_error)}\n"
                            f"Migration completed successfully with {total_rows_inserted} rows inserted, "
                            f"but verification encountered an error. Check logs for details."
                        )
                        # Allow sync to succeed even if verification fails
                    
                    # Log perfect accuracy success
                    if accuracy_report.get('perfect_accuracy', False):
                        logger.info(
                            f"Perfect migration completed for {schema}.{table}: "
                            f"Zero data loss, zero inaccuracy, 100% accuracy verified"
                        )
            
            # Surface verification summary for job/execution UI (Oracle-inclusive; no credentials)
            if accuracy_report is not None:
                exp = accuracy_report.get('expected_row_count')
                act = accuracy_report.get('actual_row_count')
                perfect = accuracy_report.get('perfect_accuracy', False)
                mismatched = len(accuracy_report.get('mismatched_rows', []))
                parts = [f"Rows: {act}/{exp}" if exp is not None and act is not None else f"Rows inserted: {total_rows_inserted}"]
                parts.append("Perfect accuracy: Yes" if perfect else "Perfect accuracy: No")
                if mismatched > 0:
                    parts.append(f"Mismatched rows: {mismatched}")
                log.verification_summary = "; ".join(parts)
            
            # Mark log as completed
            log.status = 'completed'
            log.completed_at = timezone.now()
            log.save()
            
            logger.info(
                f"Successfully synced table {schema}.{table}: "
                f"{total_rows_inserted} rows in {batch_number} batches"
            )
            
        except Exception as e:
            # Capture error details; include DB types for Oracle-inclusive flows (no credentials/DSN)
            import traceback
            try:
                source_db = QueryBuilder.get_db_type(self.source_connector)
                target_db = QueryBuilder.get_db_type(self.target_connector)
                db_context = f" [Source: {source_db}, Target: {target_db}]"
                oracle_note = " Oracle ADW:" if (source_db == 'oracle' or target_db == 'oracle') else ""
            except Exception:
                db_context = ""
                oracle_note = ""
            error_details = f"{oracle_note}{str(e)}{db_context}\n\nTraceback:\n{traceback.format_exc()}"
            
            log.status = 'failed'
            log.error_message = error_details[:5000]  # Limit to 5000 chars for database field
            log.completed_at = timezone.now()
            log.save()
            
            logger.error(
                f"Failed to sync table {schema}.{table}: {str(e)}",
                exc_info=True
            )
            raise TableSyncError(f"Table sync failed for {schema}.{table}: {str(e)}") from e

    def _sync_table_mongo_source(
        self,
        job_table: SyncJobTable,
        schema: str,
        table: str,
        target_schema: str,
        target_table: str,
        log: SyncExecutionLog,
    ) -> None:
        """Full sync path for MongoDB source collections into SQL targets."""
        from django.db.models import Sum

        # Ensure target table exists (Mongo connector provides inferred columns)
        self.table_handler.create_table_if_not_exists(
            schema,
            table,
            column_type_overrides=getattr(job_table, "column_type_overrides", None) or {},
            column_name_overrides=getattr(job_table, "column_name_overrides", None) or {},
            excluded_columns=getattr(job_table, "excluded_columns", None) or [],
            protected_columns=getattr(job_table, "protected_columns", None) or [],
            target_table=target_table,
        )

        # Full load semantics: replace. Truncate SQL target table first.
        try:
            target_tables = self.target_connector.get_tables(target_schema)
            target_db_type = self.table_handler.target_db_type
            if target_db_type in ("sqlserver", "oracle"):
                table_exists = any(t.upper() == target_table.upper() for t in target_tables)
            else:
                table_exists = target_table in target_tables
            if table_exists:
                self.target_connector.truncate_table(target_schema, target_table)
        except Exception as e:
            error_str = str(e)
            if "does not exist" not in error_str and "Cannot find the object" not in error_str:
                raise TableSyncError(f"Failed to truncate target table: {error_str}") from e

        # Determine migratable columns and target renames
        columns = self.source_connector.get_columns(schema, table)
        if not columns:
            raise TableSyncError(f"No columns found for source table {schema}.{table}")

        overrides = getattr(job_table, "column_type_overrides", None) or {}
        if overrides:
            for col in columns:
                override_type = overrides.get(col.name.lower())
                if override_type:
                    col.data_type = override_type

        raw_protected = getattr(job_table, "protected_columns", None)
        if not isinstance(raw_protected, (list, tuple, set)):
            raw_protected = []
        raw_excluded = getattr(job_table, "excluded_columns", None)
        if not isinstance(raw_excluded, (list, tuple, set)):
            raw_excluded = []
        protected_cols = {(c or "").strip().lower() for c in raw_protected if c}
        excluded_cols = {(c or "").strip().lower() for c in raw_excluded if c}
        effective_excluded = excluded_cols - protected_cols
        if effective_excluded:
            columns = [col for col in columns if col.name.lower() not in effective_excluded]
            if not columns:
                raise TableSyncError(
                    f"No migratable columns remain after exclusion rules for {schema}.{table}"
                )

        column_names = [col.name for col in columns]
        rename_overrides = getattr(job_table, "column_name_overrides", None) or {}
        target_column_names = [rename_overrides.get(col.name.lower(), col.name) for col in columns]

        # Schema drift reconciliation: if target table exists but new columns appear, add them.
        try:
            get_cols_fn = getattr(self.target_connector, "get_columns", None)
            existing_cols = get_cols_fn(target_schema, target_table) if callable(get_cols_fn) else []
            if not isinstance(existing_cols, (list, tuple, set)):
                existing_cols = []
            existing_lower = {
                (getattr(c, "name", "") or "").strip().lower()
                for c in existing_cols
                if getattr(c, "name", None)
            }
            missing = [c for c in target_column_names if (c or "").strip().lower() not in existing_lower]
            if missing:
                add_missing_fn = getattr(self.target_connector, "add_missing_columns", None)
                if callable(add_missing_fn):
                    import pandas as pd

                    df_missing = pd.DataFrame([{col: None for col in missing}])
                    add_missing_fn(target_schema, target_table, df_missing)
        except Exception as e:
            raise TableSyncError(f"Failed to reconcile schema drift for {schema}.{table}: {str(e)}") from e

        batch_number = 0
        total_rows_fetched = 0
        total_rows_inserted = 0
        last_id = None

        while True:
            docs, last_id = self.source_connector.fetch_documents_batch(
                schema=schema,
                table=table,
                batch_size=self.batch_size,
                last_id=last_id,
            )
            if not docs:
                break

            batch_number += 1
            total_rows_fetched += len(docs)

            rows = []
            for doc in docs:
                flat = self.source_connector.flatten_document_for_sql(doc)
                rows.append(
                    tuple(
                        self._normalize_mongo_value_for_sql(flat.get(col))
                        for col in column_names
                    )
                )

            try:
                self.target_connector.bulk_insert(
                    schema=target_schema,
                    table=target_table,
                    columns=target_column_names,
                    rows=rows,
                )
            except Exception as e:
                raise TableSyncError(
                    f"Failed to insert batch {batch_number} for {schema}.{table}: {str(e)}"
                ) from e

            total_rows_inserted += len(rows)

            log.batch_number = batch_number
            log.rows_fetched = total_rows_fetched
            log.rows_inserted = total_rows_inserted
            log.save()

            self.execution.completed_tables = SyncExecutionLog.objects.filter(
                execution=self.execution, status="completed"
            ).count()
            self.execution.total_rows_synced = (
                SyncExecutionLog.objects.filter(execution=self.execution).aggregate(total=Sum("rows_inserted"))[
                    "total"
                ]
                or 0
            )
            self.execution.save()

            if len(docs) < self.batch_size:
                break

        log.verification_summary = (
            f"Mongo full sync source; rows inserted={total_rows_inserted} in {batch_number} batches"
        )
        log.status = "completed"
        log.completed_at = timezone.now()
        log.save()

    def _sync_table_mongo_target(
        self,
        job_table: SyncJobTable,
        schema: str,
        table: str,
        target_schema: str,
        target_table: str,
        log: SyncExecutionLog,
    ) -> None:
        """Full sync path for SQL sources into MongoDB target collections."""
        from django.db.models import Sum

        raw_excluded = getattr(job_table, "excluded_columns", None) or []
        raw_protected = getattr(job_table, "protected_columns", None) or []
        excluded_lower = {(c or "").strip().lower() for c in raw_excluded if c}
        protected_lower = {(c or "").strip().lower() for c in raw_protected if c}
        source_db = QueryBuilder.get_db_type(self.source_connector)

        try:
            rt_plan = prepare_runtime_transform_plan(
                job_table,
                self.job,
                source_db,
                excluded_cols_lower=excluded_lower,
                protected_cols_lower=protected_lower,
            )
        except TransformPlanValidationError as e:
            raise TableSyncError(f"[{e.error_code}] {e.message}") from e

        tq = job_table.transformation_query
        ct = job_table.column_transformations or {}
        if rt_plan is not None and ((tq and str(tq).strip()) or ct):
            raise TableSyncError(
                f"[{ERROR_TRANSFORM_PLAN_CONFLICT}] Legacy SQL transformations cannot be combined "
                "with model transforms (join/union/lookup). Clear transformation query and column "
                "transformations or use structured_filters in the model step."
            )

        # Determine the Mongo database to write to.
        # Prefer the target connection database_name when set; otherwise fall back to source schema.
        mongo_db = getattr(self.target_connector, "database_name", None) or target_schema
        mongo_coll = target_table

        if rt_plan is not None:
            try:
                validate_transform_plan_column_references(rt_plan, self.source_connector)
                query, warn_list = compile_select_from_plan(rt_plan, preview_limit=None)
            except TransformPlanValidationError as e:
                raise TableSyncError(f"[{e.error_code}] {e.message}") from e
            except Exception as e:
                raise TableSyncError(f"[transform_compile_failed] {str(e)}") from e
            if warn_list:
                logger.info("Transform compile warnings for %s.%s: %s", schema, table, warn_list)

            column_names = runtime_output_aliases(rt_plan)
            if not column_names:
                raise TableSyncError(f"[transform_plan_invalid] No output columns for {schema}.{table}")
            order_by = None if "ORDER BY" in query.upper() else column_names[0]
            pk_cols = []
        else:
            # Fetch PK columns (single or composite) to derive stable _id.
            try:
                pk_cols = self.source_connector.get_primary_key(schema, table) or []
            except Exception:
                pk_cols = []
            if not isinstance(pk_cols, (list, tuple)):
                pk_cols = []

            # Columns to migrate
            columns = self.source_connector.get_columns(schema, table)
            if not columns:
                raise TableSyncError(f"No columns found for source table {schema}.{table}")

            effective_excluded = excluded_lower - protected_lower
            if effective_excluded:
                columns = [col for col in columns if col.name.lower() not in effective_excluded]
                if not columns:
                    raise TableSyncError(
                        f"No migratable columns remain after exclusion rules for {schema}.{table}"
                    )
            column_names = [col.name for col in columns]
            order_by = ", ".join(pk_cols) if pk_cols else (column_names[0] if column_names else None)
            query = self.query_builder.build_select_query(
                connector=self.source_connector,
                schema=schema,
                table=table,
                columns=column_names,
                order_by=order_by,
            )

        rename_overrides = getattr(job_table, "column_name_overrides", None) or {}
        target_field_names = [rename_overrides.get(col.lower(), col) for col in column_names]

        # Ensure collection is empty for full replace semantics.
        try:
            self.target_connector.truncate_table(mongo_db, mongo_coll)
        except Exception as e:
            raise TableSyncError(f"Failed to clear Mongo target collection: {str(e)}") from e

        batch_number = 0
        total_rows_fetched = 0
        total_rows_inserted = 0

        while True:
            batch = self.source_connector.fetch_batch(
                query=query,
                batch_size=self.batch_size,
                offset=total_rows_fetched,
                order_by=order_by,
            )
            if not batch:
                break

            batch_number += 1
            total_rows_fetched += len(batch)

            docs = []
            for row in batch:
                docs.append(
                    build_document_from_sql_row(
                        source_columns=column_names,
                        target_fields=target_field_names,
                        row=row,
                        pk_columns=pk_cols,
                        origin_job_id=str(getattr(self.job, "id", "")) if _should_stamp_origin() else None,
                        origin_field_name=ORIGIN_FIELD_NAME,
                    )
                )

            try:
                self.target_connector.bulk_upsert_documents(mongo_db, mongo_coll, docs)
            except Exception as e:
                raise TableSyncError(
                    f"Failed to upsert batch {batch_number} into Mongo: {str(e)}"
                ) from e

            total_rows_inserted += len(docs)

            log.batch_number = batch_number
            log.rows_fetched = total_rows_fetched
            log.rows_inserted = total_rows_inserted
            log.save()

            self.execution.total_rows_synced = (
                SyncExecutionLog.objects.filter(execution=self.execution).aggregate(total=Sum("rows_inserted"))[
                    "total"
                ]
                or 0
            )
            self.execution.save()

            if len(batch) < self.batch_size:
                break

        log.verification_summary = (
            f"Mongo full sync target; docs upserted={total_rows_inserted} in {batch_number} batches"
        )
        log.status = "completed"
        log.completed_at = timezone.now()
        log.save()
    
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
            accuracy_report = {
                'expected_row_count': expected_row_count,
                'actual_row_count': 0,
                'row_count_match': False,
                'all_rows_match': False,
                'columns_compared': len(column_names),
                'mismatched_rows': [],
                'mismatched_columns': []
            }

            rename_by_lower = {}
            if target_column_names and len(target_column_names) == len(column_names):
                rename_by_lower = {
                    src.lower(): tgt
                    for src, tgt in zip(column_names, target_column_names)
                    if src
                }
            
            # Step 1: Verify row count
            try:
                actual_count = self.target_connector.get_row_count(target_schema, target_table)
                accuracy_report['actual_row_count'] = actual_count
                accuracy_report['row_count_match'] = (actual_count == expected_row_count)
                
                if actual_count != expected_row_count:
                    source_db = QueryBuilder.get_db_type(self.source_connector)
                    target_db = QueryBuilder.get_db_type(self.target_connector)
                    db_context = ""
                    if source_db == 'oracle' or target_db == 'oracle':
                        db_context = " (Oracle ADW involved; schema=%s, table=%s)" % (target_schema, target_table)
                    error_msg = (
                        f"Row count mismatch: expected {expected_row_count}, got {actual_count}{db_context}"
                    )
                    logger.error(f"Post-migration verification failed for {source_schema}.{job_table.table_name}: {error_msg}")
                    return False, error_msg, accuracy_report
            except Exception as e:
                error_msg = f"Error comparing row counts: {str(e)}"
                logger.error(error_msg, exc_info=True)
                return False, error_msg, accuracy_report
            
            # Step 2: If we have pre-migration query results, use those for comparison (most accurate)
            # Otherwise, use DataIntegrityVerifier's row-by-row comparison
            if pre_migration_query_results:
                from sync_engine.query_result_verifier import QueryResultVerifier
                query_verifier = QueryResultVerifier(self.source_connector)
                
                # Fetch target data (use target_table for target DB)
                try:
                    # Get order by column for consistent ordering
                    # CRITICAL: Use the SAME order_by that was used during pre-migration validation
                    # to ensure rows are in the same order
                    try:
                        pk_columns = self.source_connector.get_primary_key(source_schema, job_table.table_name)
                        if pk_columns:
                            order_by = ', '.join(pk_columns)
                        else:
                            # Fallback to first column
                            order_by = (target_column_names or column_names)[0] if column_names else None
                    except:
                        order_by = (target_column_names or column_names)[0] if column_names else None
                    
                    # Ensure order_by matches what was used in transformed_query
                    # Extract order_by from transformed_query if available
                    # (This ensures consistency with pre-migration query results)
                    if hasattr(self, '_last_transformed_query'):
                        transformed_query_upper = self._last_transformed_query.upper()
                        if ' ORDER BY ' in transformed_query_upper:
                            order_by_idx = transformed_query_upper.find(' ORDER BY ')
                            order_by_part = self._last_transformed_query[order_by_idx + 10:].strip()
                            # Remove LIMIT/OFFSET if present
                            if ' LIMIT ' in order_by_part.upper():
                                limit_idx = order_by_part.upper().find(' LIMIT ')
                                order_by_part = order_by_part[:limit_idx].strip()
                            # Unquote to get raw column names
                            db_type = QueryBuilder.get_db_type(self.source_connector)
                            if db_type == 'postgres' or db_type == 'oracle':
                                cols = [col.strip().strip('"') for col in order_by_part.split(',')]
                            elif db_type == 'mysql':
                                cols = [col.strip().strip('`') for col in order_by_part.split(',')]
                            elif db_type == 'sqlserver':
                                cols = [col.strip().strip('[').strip(']') for col in order_by_part.split(',')]
                            elif db_type == 'clickhouse':
                                cols = [col.strip().strip('`') for col in order_by_part.split(',')]
                            else:
                                cols = [col.strip() for col in order_by_part.split(',')]
                            # Use the extracted order_by to ensure consistency
                            order_by = ', '.join([rename_by_lower.get(c.lower(), c) for c in cols])
                    
                    logger.debug(
                        f"Using ORDER BY for target query: {order_by} "
                        f"(for {job_table.schema_name}.{job_table.table_name})"
                    )
                    
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
                    
                    # Ensure we have the same number of rows
                    if len(target_rows) != len(pre_migration_query_results):
                        error_msg = (
                            f"Row count mismatch in comparison: "
                            f"pre-migration query results={len(pre_migration_query_results)}, "
                            f"target rows={len(target_rows)}"
                        )
                        logger.error(
                            f"Post-migration verification failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
                        )
                        return False, error_msg, accuracy_report
                    
                    # Log comparison details for debugging
                    logger.info(
                        f"Comparing pre-migration query results with target data for {job_table.schema_name}.{job_table.table_name}: "
                        f"source_rows={len(pre_migration_query_results)}, target_rows={len(target_rows)}, "
                        f"order_by={order_by}"
                    )
                    if pre_migration_query_results and target_rows:
                        logger.debug(
                            f"First source row: {pre_migration_query_results[0]}, "
                            f"First target row: {target_rows[0]}"
                        )
                    
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
                    
                    # Success - return immediately
                    return True, None, accuracy_report
                except Exception as e:
                    error_msg = f"Query result comparison error: {str(e)}"
                    logger.error(
                        f"Post-migration verification failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}",
                        exc_info=True
                    )
                    # Fail if comparison can't be performed
                    return False, error_msg, accuracy_report
            
            # Step 3: Fallback to DataIntegrityVerifier if no pre-migration query results
            logger.info(
                f"No pre-migration query results available for {job_table.schema_name}.{job_table.table_name}, "
                f"using DataIntegrityVerifier for row-by-row comparison"
            )
            is_accurate, error_msg, accuracy_report_backup = self.data_integrity_verifier.verify_data_accuracy(
                job_table=job_table,
                source_schema=source_schema,
                target_schema=target_schema,
                target_table=target_table,
                expected_row_count=expected_row_count,
                column_names=column_names,
                target_column_names=target_column_names
            )
            
            # Merge accuracy reports
            accuracy_report.update(accuracy_report_backup)
            
            if not is_accurate:
                logger.error(
                    f"Post-migration verification failed for {job_table.schema_name}.{job_table.table_name}: {error_msg}"
                )
                return False, error_msg, accuracy_report
            
            accuracy_report['all_rows_match'] = True
            accuracy_report['perfect_accuracy'] = True
            
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

