"""Structured pre/post DQ packs (Day 5).

All entry points return a :class:`DQPack` and never raise — failures are
recorded in ``errors`` / ``warnings`` and reflected via ``confidence``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sync_engine.query_builder import QueryBuilder
from sync_engine.verification import VerificationResult

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_NUMERIC_DT_PREFIXES = (
    "int",
    "bigint",
    "smallint",
    "tinyint",
    "numeric",
    "decimal",
    "float",
    "double",
    "real",
    "number",
    "date",
    "time",
    "timestamp",
    "datetime",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connector_db_type(connector) -> str:
    try:
        return (QueryBuilder.get_db_type(connector) or "").strip().lower()
    except Exception:
        return ""


def _qual_table(db_type: str, schema: str, table: str) -> str:
    db = db_type or ""
    if db == "sqlserver":
        return f"[{schema}].[{table}]"
    if db == "mysql":
        return f"`{schema}`.`{table}`"
    if db == "oracle":
        # Often identifiers are case-sensitive when quoted; callers pass resolved schema/table.
        return f'"{schema}"."{table}"'
    if db == "clickhouse":
        return f"`{schema}`.`{table}`"
    # postgres default
    return f'"{schema}"."{table}"'


def _qual_col(db_type: str, col: str) -> str:
    db = db_type or ""
    if db == "sqlserver":
        return f"[{col}]"
    if db == "mysql":
        return f"`{col}`"
    if db == "oracle":
        return f'"{col}"'
    if db == "clickhouse":
        return f"`{col}`"
    return f'"{col}"'


def _float_cast_type(db_type: str) -> str:
    """Return dialect-safe floating cast target.

    PostgreSQL rejects ``DOUBLE`` (expects ``DOUBLE PRECISION``), which caused
    repeated ``type "double" does not exist`` errors in Day-7 reconciliation
    reports when computing null ratios and distribution averages.
    """
    db = (db_type or "").strip().lower()
    if db == "sqlserver":
        return "FLOAT"
    if db == "clickhouse":
        return "Float64"
    if db == "oracle":
        return "BINARY_DOUBLE"
    # Works for MySQL and remains explicit for PostgreSQL.
    return "DOUBLE PRECISION"


def _safe_execute_fetch_one(
    connector,
    sql_text: str,
    *,
    metric_name: str,
    errors: List[str],
    confidence: float,
) -> Tuple[Optional[Tuple], float]:
    fn = getattr(connector, "execute_query_fetchall", None)
    if not callable(fn):
        errors.append(f"{metric_name}: execute_query_fetchall_unavailable")
        return None, max(0.0, confidence - 0.1)
    try:
        rows = fn(sql_text)
        if not rows:
            return None, confidence
        return rows[0], confidence
    except Exception as exc:
        errors.append(f"{metric_name}: {exc}")
        return None, max(0.0, confidence - 0.1)


def _count_rows_safe(connector, schema: str, table: str) -> Tuple[Optional[int], Optional[str]]:
    fn = getattr(connector, "count_rows", None)
    if not callable(fn):
        return None, "count_rows_unavailable"
    try:
        return int(fn(schema, table, None)), None
    except Exception as exc:
        return None, str(exc)


def _null_ratio_sql(db_type: str, schema: str, table: str, col: str) -> str:
    t = _qual_table(db_type, schema, table)
    c = _qual_col(db_type, col)
    flt = _float_cast_type(db_type)
    # Portable NULL ratio via CASE (works on PG, SQL Server, MySQL, ClickHouse basic).
    return (
        f"SELECT CAST(SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS {flt}) "
        f"/ NULLIF(CAST(COUNT(*) AS {flt}), 0.0) AS null_ratio FROM {t}"
    )


def _pk_uniqueness_sql(db_type: str, schema: str, table: str, pk_cols: Sequence[str]) -> str:
    t = _qual_table(db_type, schema, table)
    if len(pk_cols) == 1:
        c = _qual_col(db_type, pk_cols[0])
        return (
            f"SELECT CAST(COUNT(*) AS BIGINT) AS total_rows, "
            f"CAST(COUNT(DISTINCT {c}) AS BIGINT) AS distinct_keys FROM {t}"
        )
    parts = ", ".join(_qual_col(db_type, c) for c in pk_cols)
    inner = f"SELECT DISTINCT {parts} FROM {t}"
    return (
        f"SELECT CAST((SELECT COUNT(*) FROM {t}) AS BIGINT) AS total_rows, "
        f"CAST((SELECT COUNT(*) FROM ({inner}) AS dq_distinct) AS BIGINT) AS distinct_keys"
    )


def _incremental_min_max_sql(db_type: str, schema: str, table: str, inc_col: str) -> str:
    t = _qual_table(db_type, schema, table)
    c = _qual_col(db_type, inc_col)
    return f"SELECT MIN({c}) AS mn, MAX({c}) AS mx FROM {t}"


def _pk_dupe_delta_sql(db_type: str, schema: str, table: str, pk_cols: Sequence[str]) -> str:
    """Rows exceeding one per distinct PK (0 when unique)."""
    t = _qual_table(db_type, schema, table)
    if len(pk_cols) == 1:
        c = _qual_col(db_type, pk_cols[0])
        return (
            f"SELECT CAST(COUNT(*) - COUNT(DISTINCT {c}) AS BIGINT) AS dup_delta FROM {t}"
        )
    parts = ", ".join(_qual_col(db_type, c) for c in pk_cols)
    sub = f"SELECT {parts}, CAST(COUNT(*) AS BIGINT) AS cnt FROM {t} GROUP BY {parts} HAVING COUNT(*) > 1"
    return f"SELECT CAST(COALESCE(SUM(cnt - 1), 0) AS BIGINT) AS dup_delta FROM ({sub}) AS dq_dupes"


def _aggregate_min_max_avg_sql(db_type: str, schema: str, table: str, col: str) -> str:
    t = _qual_table(db_type, schema, table)
    c = _qual_col(db_type, col)
    flt = _float_cast_type(db_type)
    # AVG returns numeric; MIN/MAX preserve types — OK for JSON via repr downstream.
    return (
        f"SELECT MIN({c}) AS mn, MAX({c}) AS mx, AVG(CAST({c} AS {flt})) AS av FROM {t}"
    )


def _null_count_sql(db_type: str, schema: str, table: str, col: str) -> str:
    t = _qual_table(db_type, schema, table)
    c = _qual_col(db_type, col)
    return f"SELECT CAST(SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS BIGINT) AS n FROM {t}"


def numeric_columns_from_column_infos(column_infos, *, limit: int = 8) -> List[str]:
    """Pick up to ``limit`` numeric/date column names from cached ``ColumnInfo`` rows."""
    out: List[str] = []
    for ci in column_infos or []:
        dt = (getattr(ci, "data_type", None) or "").lower()
        if any(dt.startswith(p) for p in _NUMERIC_DT_PREFIXES):
            name = getattr(ci, "name", None)
            if name:
                out.append(str(name))
        if len(out) >= limit:
            break
    return out


def discover_numeric_or_date_columns(
    connector,
    schema: str,
    table: str,
    *,
    limit: int = 8,
) -> Tuple[List[str], List[str]]:
    """Return up to ``limit`` column names suitable for distribution drift."""
    warnings: List[str] = []
    fn = getattr(connector, "get_columns", None)
    if not callable(fn):
        warnings.append("numeric_column_discovery_failed_no_get_columns")
        return [], warnings
    try:
        cols = fn(schema, table)
    except Exception as exc:
        warnings.append(f"numeric_column_discovery_failed:{exc}")
        return [], warnings
    out: List[str] = []
    for ci in cols or []:
        dt = (getattr(ci, "data_type", None) or "").lower()
        if any(dt.startswith(p) for p in _NUMERIC_DT_PREFIXES):
            name = getattr(ci, "name", None)
            if name:
                out.append(str(name))
        if len(out) >= limit:
            break
    return out, warnings


@dataclass
class DQPack:
    metrics: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    decision: str = "ok"
    confidence: float = 1.0


def compute_pre_pack(
    *,
    execution,
    job,
    job_table,
    source_connector,
    source_schema: str,
    source_table: str,
    sync_mode: str = "incremental",
    schema_drift_added_columns: Optional[Sequence[str]] = None,
    incremental_column: Optional[str] = None,
    pk_columns: Optional[Sequence[str]] = None,
    flat_file_skip_source_metrics: bool = False,
    flat_file_skip_reason: Optional[str] = None,
) -> DQPack:
    """Best-effort source-side metrics before data movement."""
    warnings: List[str] = []
    errors: List[str] = []
    confidence = 1.0

    pk_list = [str(c) for c in (pk_columns or []) if c]
    db_type = _connector_db_type(source_connector)

    source_block: Dict[str, Any] = {
        "row_count": None,
        "row_count_error": None,
        "pk_columns": pk_list,
        "pk_unique": None,
        "pk_unique_skipped_reason": None,
        "null_ratio": {},
        "incremental_column": incremental_column,
        "incremental_min_max": None,
    }

    if flat_file_skip_source_metrics:
        source_block["row_count"] = None
        source_block["row_count_error"] = None
        reason = flat_file_skip_reason or "flat_file_pre_scan_disabled"
        source_block["row_count_skipped_reason"] = reason
        warnings.append(reason)
        confidence = max(0.0, confidence - 0.2)
        metrics = {
            "schema_version": SCHEMA_VERSION,
            "computed_at": _utc_iso(),
            "scope": {
                "schema": source_schema,
                "table": source_table,
                "mode": sync_mode,
            },
            "source": source_block,
            "schema_drift": {
                "added_columns": list(schema_drift_added_columns or []),
                "blocked": False,
            },
            "warnings": warnings,
            "errors": errors,
        }
        return DQPack(metrics=metrics, warnings=warnings, errors=errors, decision="ok", confidence=confidence)

    try:
        return _compute_pre_pack_core(
            source_connector=source_connector,
            source_schema=source_schema,
            source_table=source_table,
            sync_mode=sync_mode,
            schema_drift_added_columns=schema_drift_added_columns,
            incremental_column=incremental_column,
            pk_list=pk_list,
            db_type=db_type,
            source_block=source_block,
            warnings=warnings,
            errors=errors,
            confidence=confidence,
        )
    except Exception as exc:
        logger.exception("compute_pre_pack failed unexpectedly for %s.%s", source_schema, source_table)
        errors.append(str(exc))
        metrics = {
            "schema_version": SCHEMA_VERSION,
            "computed_at": _utc_iso(),
            "scope": {"schema": source_schema, "table": source_table, "mode": sync_mode},
            "source": source_block,
            "schema_drift": {
                "added_columns": list(schema_drift_added_columns or []),
                "blocked": False,
            },
            "warnings": warnings,
            "errors": errors,
        }
        return DQPack(metrics=metrics, warnings=warnings, errors=errors, decision="ok", confidence=0.0)


def _compute_pre_pack_core(
    *,
    source_connector,
    source_schema: str,
    source_table: str,
    sync_mode: str,
    schema_drift_added_columns: Optional[Sequence[str]],
    incremental_column: Optional[str],
    pk_list: List[str],
    db_type: str,
    source_block: Dict[str, Any],
    warnings: List[str],
    errors: List[str],
    confidence: float,
) -> DQPack:
    rc, rc_err = _count_rows_safe(source_connector, source_schema, source_table)
    source_block["row_count"] = rc
    source_block["row_count_error"] = rc_err
    if rc_err:
        errors.append(f"row_count:{rc_err}")
        confidence = max(0.0, confidence - 0.1)

    # PK uniqueness
    if not pk_list:
        source_block["pk_unique_skipped_reason"] = "no_pk_columns"
    elif db_type in ("", "mongodb"):
        source_block["pk_unique_skipped_reason"] = "unsupported_connector_for_pk_sql"
        warnings.append("pk_unique_skipped")
        confidence = max(0.0, confidence - 0.05)
    else:
        sql_pk = _pk_uniqueness_sql(db_type, source_schema, source_table, pk_list)
        row, confidence = _safe_execute_fetch_one(
            source_connector,
            sql_pk,
            metric_name="pk_uniqueness",
            errors=errors,
            confidence=confidence,
        )
        if row and len(row) >= 2:
            total_rows, distinct_keys = row[0], row[1]
            try:
                tr = int(total_rows) if total_rows is not None else None
                dk = int(distinct_keys) if distinct_keys is not None else None
                if tr is not None and dk is not None:
                    source_block["pk_unique"] = tr == dk
                else:
                    source_block["pk_unique"] = None
            except Exception:
                source_block["pk_unique"] = None
        else:
            source_block["pk_unique_skipped_reason"] = "query_failed"

    # Null ratios on PK columns (bounded)
    if pk_list and db_type not in ("", "mongodb"):
        for col in pk_list[:16]:
            sql_n = _null_ratio_sql(db_type, source_schema, source_table, col)
            row, confidence = _safe_execute_fetch_one(
                source_connector,
                sql_n,
                metric_name=f"null_ratio[{col}]",
                errors=errors,
                confidence=confidence,
            )
            if row and row[0] is not None:
                try:
                    source_block["null_ratio"][col] = float(row[0])
                except Exception:
                    source_block["null_ratio"][col] = None

    # Incremental min/max
    if incremental_column and db_type not in ("", "mongodb"):
        sql_mm = _incremental_min_max_sql(db_type, source_schema, source_table, incremental_column)
        row, confidence = _safe_execute_fetch_one(
            source_connector,
            sql_mm,
            metric_name="incremental_min_max",
            errors=errors,
            confidence=confidence,
        )
        if row:
            source_block["incremental_min_max"] = {
                "min": row[0],
                "max": row[1] if len(row) > 1 else None,
            }

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "computed_at": _utc_iso(),
        "scope": {
            "schema": source_schema,
            "table": source_table,
            "mode": sync_mode,
        },
        "source": source_block,
        "schema_drift": {
            "added_columns": list(schema_drift_added_columns or []),
            "blocked": False,
        },
        "warnings": warnings,
        "errors": errors,
    }
    return DQPack(metrics=metrics, warnings=warnings, errors=errors, decision="ok", confidence=confidence)


def _post_decision(
    *,
    parity: Optional[VerificationResult],
    pk_dupes: int,
    confidence: float,
    dead_letter_count: int,
    no_delete_propagation: bool,
    source_count: Optional[int],
    target_count: Optional[int],
) -> str:
    if parity and parity.decision == "repair_full":
        return "repair_full"
    if parity and parity.decision == "repair_incremental":
        return "repair_incremental"
    if parity and parity.decision == "warning":
        return "warning"
    if pk_dupes > 0:
        return "warning"
    if dead_letter_count > 0:
        return "warning"
    if confidence < 0.8:
        return "warning"
    if (
        source_count is not None
        and target_count is not None
        and no_delete_propagation
        and source_count > 0
    ):
        delta_ratio = abs(source_count - target_count) / float(source_count)
        if delta_ratio > 0.001:
            return "warning"
    return "ok"


def compute_post_pack(
    *,
    execution,
    job,
    job_table,
    source_connector,
    target_connector,
    source_schema: str,
    source_table: str,
    target_schema: str,
    target_table: str,
    sync_mode: str = "incremental",
    parity_result: Optional[VerificationResult] = None,
    dead_letter_count: int = 0,
    attempts: int = 0,
    last_error_code: Optional[str] = None,
    pk_columns: Optional[Sequence[str]] = None,
    source_pk_columns: Optional[Sequence[str]] = None,
    target_pk_columns: Optional[Sequence[str]] = None,
    numeric_columns: Optional[Sequence[str]] = None,
    schema_drift_added_columns: Optional[Sequence[str]] = None,
    no_delete_propagation: bool = True,
    flat_file: bool = False,
) -> DQPack:
    """Post-run metrics merged with parity + reliability counters."""
    try:
        return _compute_post_pack_core(
            execution=execution,
            job=job,
            job_table=job_table,
            source_connector=source_connector,
            target_connector=target_connector,
            source_schema=source_schema,
            source_table=source_table,
            target_schema=target_schema,
            target_table=target_table,
            sync_mode=sync_mode,
            parity_result=parity_result,
            dead_letter_count=dead_letter_count,
            attempts=attempts,
            last_error_code=last_error_code,
            pk_columns=pk_columns,
            source_pk_columns=source_pk_columns,
            target_pk_columns=target_pk_columns,
            numeric_columns=numeric_columns,
            schema_drift_added_columns=schema_drift_added_columns,
            no_delete_propagation=no_delete_propagation,
            flat_file=flat_file,
        )
    except Exception as exc:
        logger.exception("compute_post_pack failed unexpectedly for %s.%s", source_schema, source_table)
        metrics = {
            "schema_version": SCHEMA_VERSION,
            "computed_at": _utc_iso(),
            "scope": {
                "schema": source_schema,
                "table": source_table,
                "mode": sync_mode,
            },
            "errors": [str(exc)],
            "decision": "warning",
            "confidence": 0.0,
            "warnings": [],
        }
        return DQPack(metrics=metrics, warnings=[], errors=[str(exc)], decision="warning", confidence=0.0)


def _compute_post_pack_core(
    *,
    execution,
    job,
    job_table,
    source_connector,
    target_connector,
    source_schema: str,
    source_table: str,
    target_schema: str,
    target_table: str,
    sync_mode: str = "incremental",
    parity_result: Optional[VerificationResult] = None,
    dead_letter_count: int = 0,
    attempts: int = 0,
    last_error_code: Optional[str] = None,
    pk_columns: Optional[Sequence[str]] = None,
    source_pk_columns: Optional[Sequence[str]] = None,
    target_pk_columns: Optional[Sequence[str]] = None,
    numeric_columns: Optional[Sequence[str]] = None,
    schema_drift_added_columns: Optional[Sequence[str]] = None,
    no_delete_propagation: bool = True,
    flat_file: bool = False,
) -> DQPack:
    warnings: List[str] = []
    errors: List[str] = []
    confidence = 1.0

    base_pk = [str(c) for c in (pk_columns or []) if c]
    src_pk_list = base_pk if source_pk_columns is None else [str(c) for c in source_pk_columns if c]
    tgt_pk_list = base_pk if target_pk_columns is None else [str(c) for c in target_pk_columns if c]
    pk_list = base_pk
    src_db = _connector_db_type(source_connector)
    tgt_db = _connector_db_type(target_connector)

    tgt_count, te = _count_rows_safe(target_connector, target_schema, target_table)
    if te:
        errors.append(f"target_row_count:{te}")
        confidence = max(0.0, confidence - 0.1)

    pk_dupes = 0
    dup_key_cols = tgt_pk_list or pk_list
    if dup_key_cols and tgt_db not in ("", "mongodb"):
        sql_dup = _pk_dupe_delta_sql(tgt_db, target_schema, target_table, dup_key_cols)
        row, confidence = _safe_execute_fetch_one(
            target_connector,
            sql_dup,
            metric_name="pk_dupes",
            errors=errors,
            confidence=confidence,
        )
        if row and row[0] is not None:
            try:
                pk_dupes = max(0, int(row[0]))
            except Exception:
                pk_dupes = 0

    null_parity: Dict[str, Any] = {}
    if (
        not flat_file
        and src_pk_list
        and tgt_pk_list
        and src_db not in ("", "mongodb")
        and tgt_db not in ("", "mongodb")
    ):
        if len(src_pk_list) != len(tgt_pk_list):
            warnings.append("pk_null_parity_skipped_mismatched_src_tgt_key_lengths")
        for src_col, tgt_col in zip(src_pk_list[:16], tgt_pk_list[:16]):
            s_sql = _null_count_sql(src_db, source_schema, source_table, src_col)
            t_sql = _null_count_sql(tgt_db, target_schema, target_table, tgt_col)
            sr, confidence = _safe_execute_fetch_one(
                source_connector,
                s_sql,
                metric_name=f"src_null[{src_col}]",
                errors=errors,
                confidence=confidence,
            )
            tr, confidence = _safe_execute_fetch_one(
                target_connector,
                t_sql,
                metric_name=f"tgt_null[{tgt_col}]",
                errors=errors,
                confidence=confidence,
            )
            sn = int(sr[0]) if sr and sr[0] is not None else None
            tn = int(tr[0]) if tr and tr[0] is not None else None
            delta = None if sn is None or tn is None else tn - sn
            label = tgt_col or src_col
            null_parity[label] = {"source": sn, "target": tn, "delta": delta}

    parity_block = None
    src_ct: Optional[int] = None
    tgt_ct: Optional[int] = None
    if parity_result is not None:
        parity_block = {
            "decision": parity_result.decision,
            "source_count": parity_result.source_count,
            "target_count": parity_result.target_count,
            "sample_hash_match": parity_result.sample_hash_match,
        }
        src_ct = parity_result.source_count
        tgt_ct = parity_result.target_count
    elif flat_file:
        src_ct = None
        tgt_ct = tgt_count
    else:
        src_ct, _ = _count_rows_safe(source_connector, source_schema, source_table)
        tgt_ct = tgt_count

    distribution: Dict[str, Any] = {}
    cols = list(numeric_columns or [])[:8]
    if flat_file:
        cols = []
    for col in cols:
        entry: Dict[str, Any] = {
            "source": None,
            "target": None,
            "delta_pct_mean": None,
            "skipped_reason": None,
        }
        if src_db in ("", "mongodb") or tgt_db in ("", "mongodb"):
            entry["skipped_reason"] = "aggregate_unsupported"
            distribution[col] = entry
            continue
        s_sql = _aggregate_min_max_avg_sql(src_db, source_schema, source_table, col)
        t_sql = _aggregate_min_max_avg_sql(tgt_db, target_schema, target_table, col)
        sr, confidence = _safe_execute_fetch_one(
            source_connector,
            s_sql,
            metric_name=f"dist_src[{col}]",
            errors=errors,
            confidence=confidence,
        )
        tr, confidence = _safe_execute_fetch_one(
            target_connector,
            t_sql,
            metric_name=f"dist_tgt[{col}]",
            errors=errors,
            confidence=confidence,
        )
        if not sr or not tr:
            entry["skipped_reason"] = "aggregate_unsupported"
            distribution[col] = entry
            continue

        def _triplet(r):
            return {
                "min": r[0],
                "max": r[1] if len(r) > 1 else None,
                "approx_mean": float(r[2]) if len(r) > 2 and r[2] is not None else None,
            }

        try:
            entry["source"] = _triplet(sr)
            entry["target"] = _triplet(tr)
            sm = entry["source"]["approx_mean"]
            tm = entry["target"]["approx_mean"]
            if sm is not None and tm is not None:
                denom = max(abs(sm), 1.0)
                entry["delta_pct_mean"] = abs(sm - tm) / denom
        except Exception:
            entry["skipped_reason"] = "parse_failed"
        distribution[col] = entry

    decision = _post_decision(
        parity=parity_result,
        pk_dupes=pk_dupes,
        confidence=confidence,
        dead_letter_count=dead_letter_count,
        no_delete_propagation=no_delete_propagation,
        source_count=src_ct,
        target_count=tgt_ct,
    )

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "computed_at": _utc_iso(),
        "scope": {
            "schema": source_schema,
            "table": source_table,
            "mode": sync_mode,
        },
        "target": {
            "row_count": tgt_count,
            "pk_dupes": pk_dupes,
            "null_count_parity": null_parity,
        },
        "parity": parity_block,
        "distribution_drift": distribution,
        "schema_drift": {
            "added_columns": list(schema_drift_added_columns or []),
            "blocked": False,
        },
        "reliability": {
            "dead_letter_count": dead_letter_count,
            "attempts": attempts,
            "last_error_code": last_error_code,
        },
        "decision": decision,
        "confidence": confidence,
        "warnings": warnings,
        "errors": errors,
    }
    return DQPack(metrics=metrics, warnings=warnings, errors=errors, decision=decision, confidence=confidence)
