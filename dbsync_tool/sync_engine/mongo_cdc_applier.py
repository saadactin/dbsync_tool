"""
Apply MongoDB Change Stream events to SQL targets.

Day 4 scope: upsert/delete into SQL and advance resume token checkpoint only after success.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import pandas as pd

from sync_engine.table_handler import TableHandler
from sync_engine.full_sync import get_target_table_name
from sync_engine.mongo_cdc_runner import MongoCdcEvent
from sync_jobs.models import MongoCdcCheckpoint, SyncJob, SyncJobTable

logger = logging.getLogger(__name__)

ORIGIN_FIELD_NAME = "__dbsync_origin_job_id"


def _escape_sql_literal(value: str) -> str:
    return (value or "").replace("'", "''")


def _get_target_schema_for_sql(target_db_type: str, target_connector, source_schema: str) -> str:
    if target_db_type == "mysql":
        return getattr(target_connector, "database_name", None) or source_schema
    if target_db_type == "clickhouse":
        return getattr(target_connector, "database_name", None) or source_schema
    if target_db_type == "postgres":
        return "public"
    if target_db_type == "sqlserver":
        return "dbo"
    if target_db_type == "oracle":
        return (getattr(target_connector, "username", None) or "").strip().upper() or source_schema
    return source_schema


def _normalize_resume_token_for_compare(token: Any) -> str:
    """
    Normalize resume tokens into a stable string representation so we can safely
    compare "same token" even if serialization order differs.
    """
    try:
        return json.dumps(token, default=str, sort_keys=True)
    except Exception:
        return str(token)


def _load_job_table_mapping(job: SyncJob, schema: str, table: str) -> Dict[str, Any]:
    jt = (
        job.tables.filter(is_enabled=True, schema_name=schema, table_name=table).first()
        if hasattr(job, "tables")
        else None
    )
    if not jt:
        return {
            "column_name_overrides": {},
            "column_type_overrides": {},
            "excluded_columns": set(),
            "protected_columns": {"_id"},
        }

    rename_overrides = getattr(jt, "column_name_overrides", None) or {}
    type_overrides = getattr(jt, "column_type_overrides", None) or {}
    raw_excluded = getattr(jt, "excluded_columns", None) or []
    raw_protected = getattr(jt, "protected_columns", None) or []

    excluded = {(c or "").strip().lower() for c in raw_excluded if c}
    protected = {(c or "").strip().lower() for c in raw_protected if c}

    # Mongo `_id` must always be included as a key.
    protected.add("_id")

    return {
        "jt": jt,
        "column_name_overrides": {(k or "").strip().lower(): v for k, v in rename_overrides.items()},
        "column_type_overrides": {(k or "").strip().lower(): v for k, v in type_overrides.items()},
        "excluded_columns": excluded - protected,
        "protected_columns": protected,
    }


def _apply_step3_mapping_to_flat(
    flat: Dict[str, Any],
    *,
    excluded_columns: set,
    column_name_overrides: Dict[str, str],
) -> Dict[str, Any]:
    # Exclude first (unless protected already removed from excluded by caller).
    out: Dict[str, Any] = {}
    for k, v in (flat or {}).items():
        lk = (k or "").strip().lower()
        if not lk:
            continue
        if lk in excluded_columns:
            continue
        target_name = column_name_overrides.get(lk, k)
        out[target_name] = v
    return out


def apply_mongo_cdc_event_to_sql(
    *,
    job: SyncJob,
    event: MongoCdcEvent,
    source_connector,
    target_connector,
) -> None:
    """
    Apply one Mongo CDC event to an SQL target and checkpoint resume token after success.
    """
    schema = event.db
    table = event.coll
    if not schema or not table:
        raise ValueError("Mongo CDC event missing ns.db/ns.coll")

    target_table = get_target_table_name(job, table)
    handler = TableHandler(source_connector, target_connector)
    target_schema = _get_target_schema_for_sql(handler.target_db_type, target_connector, schema)

    ckpt, _ = MongoCdcCheckpoint.objects.get_or_create(
        job=job, schema_name=schema, table_name=table
    )

    # Dedupe guard: if we see the same resume token again (restart boundary),
    # skip applying to prevent double-upsert/delete.
    stored = (ckpt.resume_token or "").strip()
    if stored:
        try:
            stored_obj = json.loads(stored)
        except Exception:
            stored_obj = stored
        if _normalize_resume_token_for_compare(stored_obj) == _normalize_resume_token_for_compare(
            event.resume_token
        ):
            logger.info(
                "Skipping already checkpointed Mongo CDC event for %s.%s (resume token match)",
                schema,
                table,
            )
            return

    op = (event.op or "").lower()
    doc_id = event.document_id

    mapping = _load_job_table_mapping(job, schema, table)
    rename_overrides = mapping["column_name_overrides"]
    type_overrides = mapping["column_type_overrides"]
    excluded_columns = mapping["excluded_columns"]

    if op in ("insert", "replace", "update"):
        if not event.full_document:
            # For update events, updateLookup should provide fullDocument; if not, skip safely.
            raise ValueError(f"Missing fullDocument for op={op} on {schema}.{table}")

        # Loop-prevention (optional): if the document was stamped by this job, skip applying it back.
        try:
            stamped = (event.full_document or {}).get(ORIGIN_FIELD_NAME)
        except Exception:
            stamped = None
        if stamped and str(stamped) == str(getattr(job, "id", "")):
            ckpt.resume_token = json.dumps(event.resume_token, default=str)
            ckpt.save(update_fields=["resume_token", "updated_at"])
            logger.info(
                "Skipping Mongo CDC event for %s.%s due to origin stamp match (loop prevention)",
                schema,
                table,
            )
            return

        # Ensure table exists using inferred Mongo columns.
        handler.create_table_if_not_exists(
            schema,
            table,
            target_table=target_table,
            column_type_overrides=type_overrides,
            column_name_overrides=rename_overrides,
            excluded_columns=list(excluded_columns),
            protected_columns=["_id"],
        )

        flat = source_connector.flatten_document_for_sql(event.full_document)
        if "_id" not in flat and doc_id is not None:
            flat["_id"] = doc_id

        flat = _apply_step3_mapping_to_flat(
            flat,
            excluded_columns=excluded_columns,
            column_name_overrides=rename_overrides,
        )

        # Upsert using existing connector upsert_dataframe implementations.
        df = pd.DataFrame([flat])

        # Schema drift reconciliation: add any missing columns before upsert.
        try:
            get_cols_fn = getattr(target_connector, "get_columns", None)
            existing_cols = get_cols_fn(target_schema, target_table) if callable(get_cols_fn) else []
            if not isinstance(existing_cols, (list, tuple, set)):
                existing_cols = []
            existing_lower = {
                (getattr(c, "name", "") or "").strip().lower()
                for c in existing_cols
                if getattr(c, "name", None)
            }
            missing_cols = [c for c in df.columns if (c or "").strip().lower() not in existing_lower]
            if missing_cols:
                add_missing_fn = getattr(target_connector, "add_missing_columns", None)
                if callable(add_missing_fn):
                    df_missing = pd.DataFrame([{col: None for col in missing_cols}])
                    add_missing_fn(target_schema, target_table, df_missing)
        except Exception as e:
            raise ValueError(f"Failed to reconcile schema drift for {schema}.{table}: {str(e)}") from e

        target_connector.upsert_dataframe(target_schema, target_table, df, key_column="_id")

    elif op == "delete":
        if job.no_delete_propagation:
            logger.info("Skipping delete propagation for %s.%s (job policy)", schema, table)
        else:
            if not doc_id:
                raise ValueError(f"Delete event missing documentKey._id for {schema}.{table}")

            # Best-effort delete by _id across SQL targets.
            safe_id = _escape_sql_literal(str(doc_id))
            if handler.target_db_type == "mysql" or handler.target_db_type == "clickhouse":
                query = f"DELETE FROM `{target_schema}`.`{target_table}` WHERE `_id` = '{safe_id}'"
            elif handler.target_db_type == "postgres":
                query = f'DELETE FROM \"{target_schema}\".\"{target_table}\" WHERE \"_id\" = \'{safe_id}\''
            elif handler.target_db_type == "sqlserver":
                query = f"DELETE FROM [{target_schema}].[{target_table}] WHERE [_id] = '{safe_id}'"
            else:
                query = f'DELETE FROM \"{target_schema}\".\"{target_table}\" WHERE \"_id\" = \'{safe_id}\''
            target_connector.execute_query(query)

    else:
        logger.debug("Ignoring unsupported Mongo op=%s for %s.%s", op, schema, table)

    # Advance resume token only after successful apply.
    ckpt.resume_token = json.dumps(event.resume_token, default=str)
    ckpt.save(update_fields=["resume_token", "updated_at"])

