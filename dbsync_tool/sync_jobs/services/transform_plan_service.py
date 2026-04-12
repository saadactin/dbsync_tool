"""
Transform plan validation and safe SELECT compilation for model-data wizard preview
and runtime full/incremental sync.

Only structured fields are compiled into SQL — no free-text SQL fragments.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from connections.connectors.base import ColumnInfo, DBConnector

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Stable codes for logs and TableSyncError messages (Day 4 hardening)
ERROR_TRANSFORM_PLAN_INVALID = "transform_plan_invalid"
ERROR_TRANSFORM_COMPILE_FAILED = "transform_compile_failed"
ERROR_TRANSFORM_DB_TYPE_DRIFT = "transform_db_type_drift"
ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE = "invalid_transform_column_reference"
ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM = "incremental_unsupported_transform"
ERROR_TRANSFORM_PLAN_CONFLICT = "transform_plan_conflict"
ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM = "incremental_unsupported_transform"

MAX_TRANSFORM_PLAN_BYTES = 64 * 1024

JOIN_TYPES = frozenset({"INNER", "LEFT", "RIGHT", "FULL"})
ALLOWED_FILTER_OPS = frozenset(
    {"=", "!=", "<", ">", "<=", ">=", "LIKE", "IS NULL", "IS NOT NULL"}
)

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TransformPlanValidationError(Exception):
    """User-facing validation error for transform plans."""

    def __init__(self, message: str, error_code: str = "validation_error"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


def normalize_internal_db_type(db_type: str) -> str:
    d = (db_type or "").lower()
    if d == "oracle_adw":
        return "oracle"
    return d


def _identifier_ok(name: str) -> bool:
    return bool(name and IDENT_RE.match(name))


def _quote_ident(db_type: str, part: str) -> str:
    if db_type in ("postgres", "oracle"):
        escaped = part.replace('"', '""')
        return f'"{escaped}"'
    if db_type in ("mysql", "clickhouse"):
        escaped = part.replace("`", "``")
        return f"`{escaped}`"
    if db_type == "sqlserver":
        escaped = part.replace("]", "]]")
        return f"[{escaped}]"
    escaped = part.replace('"', '""')
    return f'"{escaped}"'


def _quote_table(db_type: str, schema: str, table: str) -> str:
    return f"{_quote_ident(db_type, schema)}.{_quote_ident(db_type, table)}"


def _format_filter_value_sql(db_type: str, value: Any, op: str) -> str:
    if op in ("IS NULL", "IS NOT NULL"):
        return ""
    if isinstance(value, bool):
        if db_type == "sqlserver":
            return "1" if value else "0"
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    if value is None:
        raise TransformPlanValidationError("Filter value cannot be null unless op is IS NULL")
    s = str(value).replace("'", "''")
    return f"'{s}'"


def _table_key(schema: str, table: str) -> str:
    return f"{schema}.{table}"


def default_plan_for_table(
    schema_name: str, table_name: str, source_db_type: str
) -> Dict[str, Any]:
    return {
        "mode": "single_table",
        "source_db_type": source_db_type,
        "base_table": {"schema_name": schema_name, "table_name": table_name},
        "join_nodes": [],
        "union_branches": [],
        "union_select_columns": [],
        "lookup": None,
        "selected_output_columns": [],
        "structured_filters": [],
        "order_by": [],
        "derived_columns": [],
    }


def ensure_default_plans(
    selected_tables: List[Dict[str, str]], source_db_type: str, existing: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Build or reconcile per-table plans for current selection."""
    internal = normalize_internal_db_type(source_db_type)
    keys_ordered = []
    for t in selected_tables:
        keys_ordered.append(_table_key(t["schema_name"], t["table_name"]))

    existing = existing or {}
    out: Dict[str, Any] = {}
    for t in selected_tables:
        k = _table_key(t["schema_name"], t["table_name"])
        if k in existing and isinstance(existing[k], dict):
            plan = dict(existing[k])
            plan.setdefault("base_table", {"schema_name": t["schema_name"], "table_name": t["table_name"]})
            plan.setdefault("mode", "single_table")
            out[k] = plan
        else:
            out[k] = default_plan_for_table(t["schema_name"], t["table_name"], internal)
    return out


def _validate_tables_subset(plan_tables: Set[str], allowed: Set[str], label: str) -> None:
    unknown = plan_tables - allowed
    if unknown:
        raise TransformPlanValidationError(
            f"{label}: tables not in job selection: {', '.join(sorted(unknown))}",
            "unknown_table",
        )


def validate_plan_size(plan: Dict[str, Any]) -> None:
    try:
        raw = json.dumps(plan, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise TransformPlanValidationError(f"Transform plan is not JSON-serializable: {e}", "invalid_json")
    if len(raw) > MAX_TRANSFORM_PLAN_BYTES:
        raise TransformPlanValidationError(
            f"Transform plan exceeds max size ({MAX_TRANSFORM_PLAN_BYTES} bytes).",
            "plan_too_large",
        )


def validate_structured_filters(filters: Any, db_type: str) -> List[Dict[str, Any]]:
    if not filters:
        return []
    if not isinstance(filters, list):
        raise TransformPlanValidationError("structured_filters must be a list", "invalid_filters")
    normalized = []
    for i, f in enumerate(filters):
        if not isinstance(f, dict):
            raise TransformPlanValidationError(f"Filter #{i+1} must be an object", "invalid_filters")
        col = f.get("column")
        op = f.get("op", "").strip().upper() if isinstance(f.get("op"), str) else ""
        if op == "IS NULL" or op == "IS NOT NULL":
            # allow IS NULL / IS NOT NULL with optional column only
            if op == "IS NULL":
                op_norm = "IS NULL"
            else:
                op_norm = "IS NOT NULL"
        else:
            op_raw = f.get("op")
            if not isinstance(op_raw, str):
                raise TransformPlanValidationError(f"Filter #{i+1} op must be a string", "invalid_filters")
            op_norm = op_raw.strip().upper()
        if op_norm not in ALLOWED_FILTER_OPS:
            raise TransformPlanValidationError(
                f"Filter #{i+1} op '{op_norm}' is not allowed", "invalid_filter_op"
            )
        if not _identifier_ok(str(col)):
            raise TransformPlanValidationError(
                f"Filter #{i+1} column must be a simple identifier", "invalid_filter_column"
            )
        val = f.get("value")
        if op_norm in ("IS NULL", "IS NOT NULL"):
            normalized.append({"column": str(col), "op": op_norm, "value": None})
            continue
        normalized.append({"column": str(col), "op": op_norm, "value": val})
    return normalized


def validate_order_by(order_by: Any) -> List[str]:
    if not order_by:
        return []
    if not isinstance(order_by, list):
        raise TransformPlanValidationError("order_by must be a list", "invalid_order_by")
    out = []
    for i, item in enumerate(order_by):
        if not isinstance(item, str):
            raise TransformPlanValidationError(f"order_by[{i}] must be a string", "invalid_order_by")
        if not _identifier_ok(item.strip()):
            raise TransformPlanValidationError(
                f"order_by[{i}] must be a simple identifier", "invalid_order_by"
            )
        out.append(item.strip())
    return out


def validate_derived_columns_empty(derived: Any) -> None:
    if derived is None:
        return
    if isinstance(derived, list) and len(derived) == 0:
        return
    raise TransformPlanValidationError(
        "Derived columns with free expressions are not allowed in this version.",
        "derived_not_supported",
    )


def validate_transform_plan(
    plan: Dict[str, Any],
    *,
    plan_table_key: str,
    allowed_table_keys: Set[str],
    source_db_type: str,
) -> Dict[str, Any]:
    """
    Validate and return a normalized plan dict for one table row.
    plan_table_key is schema.table for this SyncJobTable row.
    """
    validate_plan_size(plan)
    validate_derived_columns_empty(plan.get("derived_columns"))

    mode = (plan.get("mode") or "single_table").strip().lower()
    if mode not in ("single_table", "join", "union", "lookup"):
        raise TransformPlanValidationError(f"Invalid mode '{mode}'", "invalid_mode")

    internal = normalize_internal_db_type(source_db_type)

    base = plan.get("base_table") or {}
    if not isinstance(base, dict):
        raise TransformPlanValidationError("base_table must be an object", "invalid_base_table")
    b_schema = base.get("schema_name")
    b_table = base.get("table_name")
    if not b_schema or not b_table:
        raise TransformPlanValidationError("base_table needs schema_name and table_name", "invalid_base_table")
    if _table_key(b_schema, b_table) != plan_table_key:
        raise TransformPlanValidationError(
            "base_table must match the table this plan belongs to.", "base_mismatch"
        )

    structured_filters = validate_structured_filters(plan.get("structured_filters"), internal)
    order_by = validate_order_by(plan.get("order_by"))

    if mode == "single_table":
        sel = plan.get("selected_output_columns") or []
        if sel:
            raise TransformPlanValidationError(
                "For single_table mode, leave selected_output_columns empty (all base columns are used).",
                "invalid_output",
            )
        return {
            "mode": "single_table",
            "source_db_type": internal,
            "base_table": {"schema_name": b_schema, "table_name": b_table},
            "join_nodes": [],
            "union_branches": [],
            "union_select_columns": [],
            "lookup": None,
            "selected_output_columns": [],
            "structured_filters": structured_filters,
            "order_by": order_by,
            "derived_columns": [],
        }

    if mode == "union":
        branches = plan.get("union_branches") or []
        cols = plan.get("union_select_columns") or []
        if not isinstance(branches, list) or len(branches) < 2:
            raise TransformPlanValidationError("union_branches must list at least two tables", "invalid_union")
        if not isinstance(cols, list) or len(cols) < 1:
            raise TransformPlanValidationError(
                "union_select_columns must list at least one column", "invalid_union"
            )
        used = set()
        normalized_branches = []
        for i, br in enumerate(branches):
            if not isinstance(br, dict):
                raise TransformPlanValidationError(f"union_branches[{i}] invalid", "invalid_union")
            s, t = br.get("schema_name"), br.get("table_name")
            if not s or not t:
                raise TransformPlanValidationError(f"union_branches[{i}] needs schema and table", "invalid_union")
            used.add(_table_key(s, t))
            normalized_branches.append({"schema_name": s, "table_name": t})
        for c in cols:
            if not isinstance(c, str) or not _identifier_ok(c):
                raise TransformPlanValidationError(
                    "union_select_columns must be simple identifiers", "invalid_union"
                )
        _validate_tables_subset(used, allowed_table_keys, "Union")
        return {
            "mode": "union",
            "source_db_type": internal,
            "base_table": {"schema_name": b_schema, "table_name": b_table},
            "join_nodes": [],
            "union_branches": normalized_branches,
            "union_select_columns": cols,
            "lookup": None,
            "selected_output_columns": [{"alias": c, "table_ref": None, "column": c} for c in cols],
            "structured_filters": [],
            "order_by": order_by,
            "derived_columns": [],
        }

    if mode == "lookup":
        lk = plan.get("lookup")
        if not isinstance(lk, dict):
            raise TransformPlanValidationError("lookup block is required", "invalid_lookup")
        ls, lt = lk.get("schema_name"), lk.get("table_name")
        if not ls or not lt:
            raise TransformPlanValidationError("lookup needs schema_name and table_name", "invalid_lookup")
        _validate_tables_subset({_table_key(ls, lt), plan_table_key}, allowed_table_keys, "Lookup")
        main_key = lk.get("main_key_column")
        lookup_key = lk.get("lookup_key_column")
        if not _identifier_ok(str(main_key)) or not _identifier_ok(str(lookup_key)):
            raise TransformPlanValidationError("lookup key columns must be identifiers", "invalid_lookup")
        add_cols = lk.get("add_columns") or []
        if not isinstance(add_cols, list) or not add_cols:
            raise TransformPlanValidationError("lookup add_columns must be a non-empty list", "invalid_lookup")
        main_cols = lk.get("main_pass_through_columns") or []
        if not isinstance(main_cols, list) or not main_cols:
            raise TransformPlanValidationError(
                "main_pass_through_columns must list at least one base column", "invalid_lookup"
            )
        normalized_add = []
        for i, ac in enumerate(add_cols):
            if not isinstance(ac, dict):
                raise TransformPlanValidationError(f"add_columns[{i}] invalid", "invalid_lookup")
            lcol, as_alias = ac.get("lookup_column"), ac.get("as")
            if not _identifier_ok(str(lcol)) or not _identifier_ok(str(as_alias)):
                raise TransformPlanValidationError(
                    f"add_columns[{i}] lookup_column and as must be identifiers", "invalid_lookup"
                )
            normalized_add.append({"lookup_column": str(lcol), "as": str(as_alias)})
        main_pass = []
        for i, mc in enumerate(main_cols):
            if not isinstance(mc, str) or not _identifier_ok(mc):
                raise TransformPlanValidationError(
                    f"main_pass_through_columns[{i}] must be a simple identifier", "invalid_lookup"
                )
            main_pass.append(mc)

        aliases = [a["as"] for a in normalized_add] + main_pass
        if len(aliases) != len(set(aliases)):
            raise TransformPlanValidationError("Duplicate output aliases in lookup", "duplicate_alias")

        normalized_lookup = {
            "schema_name": ls,
            "table_name": lt,
            "alias": "lu",
            "main_key_column": str(main_key),
            "lookup_key_column": str(lookup_key),
            "main_pass_through_columns": main_pass,
            "add_columns": normalized_add,
        }
        out_cols = []
        for mc in main_pass:
            out_cols.append({"alias": mc, "table_ref": "b0", "column": mc})
        for ac in normalized_add:
            out_cols.append(
                {"alias": ac["as"], "table_ref": "lu", "column": ac["lookup_column"]}
            )
        return {
            "mode": "lookup",
            "source_db_type": internal,
            "base_table": {"schema_name": b_schema, "table_name": b_table},
            "join_nodes": [],
            "union_branches": [],
            "union_select_columns": [],
            "lookup": normalized_lookup,
            "selected_output_columns": out_cols,
            "structured_filters": structured_filters,
            "order_by": order_by,
            "derived_columns": [],
        }

    # join
    join_nodes = plan.get("join_nodes") or []
    if not isinstance(join_nodes, list) or not join_nodes:
        raise TransformPlanValidationError("join_nodes must be a non-empty list for join mode", "invalid_join")

    base_alias = "b0"
    used_aliases = {base_alias}
    normalized_nodes = []
    referenced_tables = {_table_key(b_schema, b_table)}

    for i, node in enumerate(join_nodes):
        if not isinstance(node, dict):
            raise TransformPlanValidationError(f"join_nodes[{i}] invalid", "invalid_join")
        jt = (node.get("join_type") or "INNER").strip().upper()
        if jt not in JOIN_TYPES:
            raise TransformPlanValidationError(f"Unsupported join_type '{jt}'", "invalid_join")
        if jt == "FULL" and internal == "mysql":
            raise TransformPlanValidationError(
                "FULL OUTER JOIN is not supported on MySQL sources. Use LEFT/INNER joins or a union pattern.",
                "unsupported_full_mysql",
            )
        js, jtbl = node.get("schema_name"), node.get("table_name")
        alias = (node.get("alias") or f"j{i+1}").strip()
        if not _identifier_ok(alias):
            raise TransformPlanValidationError(f"join_nodes[{i}] needs a valid alias", "invalid_join")
        if alias in used_aliases:
            raise TransformPlanValidationError(f"Duplicate join alias '{alias}'", "duplicate_alias")
        used_aliases.add(alias)
        if not js or not jtbl:
            raise TransformPlanValidationError(f"join_nodes[{i}] needs schema and table", "invalid_join")
        referenced_tables.add(_table_key(js, jtbl))
        on_list = node.get("on") or []
        if not isinstance(on_list, list) or not on_list:
            raise TransformPlanValidationError(f"join_nodes[{i}] needs on[] conditions", "invalid_join")
        norm_on = []
        for k, cond in enumerate(on_list):
            if not isinstance(cond, dict):
                raise TransformPlanValidationError(f"join_nodes[{i}].on[{k}] invalid", "invalid_join")
            lc, rc = cond.get("left_column"), cond.get("right_column")
            la = (cond.get("left_alias") or base_alias).strip()
            ra = (cond.get("right_alias") or alias).strip()
            if la not in used_aliases or ra not in used_aliases:
                raise TransformPlanValidationError(
                    f"join_nodes[{i}].on[{k}] references unknown alias", "invalid_join"
                )
            if not _identifier_ok(str(lc)) or not _identifier_ok(str(rc)):
                raise TransformPlanValidationError(
                    f"join_nodes[{i}].on[{k}] columns must be identifiers", "invalid_join"
                )
            norm_on.append(
                {
                    "left_alias": la,
                    "left_column": str(lc),
                    "right_alias": ra,
                    "right_column": str(rc),
                }
            )
        normalized_nodes.append(
            {
                "join_type": jt,
                "schema_name": js,
                "table_name": jtbl,
                "alias": alias,
                "on": norm_on,
            }
        )

    outputs = plan.get("selected_output_columns") or []
    if not isinstance(outputs, list) or not outputs:
        raise TransformPlanValidationError(
            "Join mode requires selected_output_columns with at least one column.", "invalid_join"
        )
    norm_outputs = []
    seen_alias = set()
    for i, oc in enumerate(outputs):
        if not isinstance(oc, dict):
            raise TransformPlanValidationError(f"selected_output_columns[{i}] invalid", "invalid_join")
        al = oc.get("alias")
        tref = (oc.get("table_ref") or "").strip()
        col = oc.get("column")
        if not _identifier_ok(str(al)):
            raise TransformPlanValidationError(f"Output alias invalid at index {i}", "invalid_join")
        if str(al).lower() in seen_alias:
            raise TransformPlanValidationError(f"Duplicate output alias '{al}'", "duplicate_alias")
        seen_alias.add(str(al).lower())
        if not _identifier_ok(str(col)):
            raise TransformPlanValidationError(f"Output column invalid at index {i}", "invalid_join")
        if tref not in used_aliases:
            raise TransformPlanValidationError(
                f"table_ref '{tref}' is not a known alias", "invalid_join"
            )
        dt = oc.get("data_type") or "varchar"
        norm_outputs.append(
            {
                "alias": str(al),
                "table_ref": tref,
                "column": str(col),
                "data_type": str(dt),
            }
        )

    _validate_tables_subset(referenced_tables, allowed_table_keys, "Join")
    return {
        "mode": "join",
        "source_db_type": internal,
        "base_table": {"schema_name": b_schema, "table_name": b_table},
        "join_nodes": normalized_nodes,
        "union_branches": [],
        "union_select_columns": [],
        "lookup": None,
        "selected_output_columns": norm_outputs,
        "structured_filters": structured_filters,
        "order_by": order_by,
        "derived_columns": [],
    }


def validate_transform_plan_column_references(
    plan: Dict[str, Any],
    connector: DBConnector,
) -> None:
    """
    Validate that every physical column referenced inside a validated transform plan
    exists in the source database metadata.

    This prevents runtime failures like SQL Server:
      "Invalid column name 'XYZ'".
    """
    if not isinstance(plan, dict):
        raise TransformPlanValidationError(
            "Transform plan must be a JSON object.",
            ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
        )

    mode = (plan.get("mode") or "single_table").strip().lower()
    base = plan.get("base_table") or {}
    if not isinstance(base, dict) or not base.get("schema_name") or not base.get("table_name"):
        raise TransformPlanValidationError(
            "Transform plan missing base_table information.",
            ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
        )

    base_schema = str(base.get("schema_name")).strip()
    base_table = str(base.get("table_name")).strip()

    # Cache metadata lookups by schema/table to avoid repeated connector calls.
    cols_cache: Dict[Tuple[str, str], Set[str]] = {}

    def get_column_set(schema_name: str, table_name: str) -> Set[str]:
        key = (schema_name.lower().strip(), table_name.lower().strip())
        if key in cols_cache:
            return cols_cache[key]
        try:
            col_infos = connector.get_columns(schema_name, table_name)
        except Exception as e:
            raise TransformPlanValidationError(
                f"Failed to load column metadata for {schema_name}.{table_name}: {e}",
                ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
            )
        names = {
            (getattr(c, "name", "") or "").strip().lower()
            for c in (col_infos or [])
        }
        cols_cache[key] = names
        return names

    missing_tables: Set[Tuple[str, str]] = set()

    def missing_ref(alias: str, col: str, schema_name: str, table_name: str) -> None:
        # Helper for building consistent missing strings.
        missing.append(f"{alias}.{col} (expected in {schema_name}.{table_name})")
        missing_tables.add((schema_name, table_name))

    missing: List[str] = []

    if mode == "single_table":
        base_cols = get_column_set(base_schema, base_table)

        # structured_filters and order_by are compiled against base alias `b0`
        for f in plan.get("structured_filters") or []:
            if not isinstance(f, dict):
                continue
            c = str(f.get("column") or "").strip()
            if c and c.lower() not in base_cols:
                missing_ref("b0", c, base_schema, base_table)

        for c in plan.get("order_by") or []:
            if not isinstance(c, str):
                continue
            cc = c.strip()
            if cc and cc.lower() not in base_cols:
                missing_ref("b0", cc, base_schema, base_table)

    elif mode == "join":
        alias_map: Dict[str, Tuple[str, str]] = {"b0": (base_schema, base_table)}
        for node in plan.get("join_nodes") or []:
            if not isinstance(node, dict):
                continue
            alias = str(node.get("alias") or "").strip()
            js = str(node.get("schema_name") or "").strip()
            jtbl = str(node.get("table_name") or "").strip()
            if alias and js and jtbl:
                alias_map[alias] = (js, jtbl)

        # join_nodes.on[*] compiled against the physical columns in their respective tables
        for node in plan.get("join_nodes") or []:
            if not isinstance(node, dict):
                continue
            alias = str(node.get("alias") or "").strip()
            tbl = alias_map.get(alias)
            if not tbl:
                continue
            node_cols = get_column_set(tbl[0], tbl[1])
            for cond in node.get("on") or []:
                if not isinstance(cond, dict):
                    continue
                la = str(cond.get("left_alias") or "").strip()
                ra = str(cond.get("right_alias") or "").strip()
                lc = str(cond.get("left_column") or "").strip()
                rc = str(cond.get("right_column") or "").strip()

                if not (la and ra and lc and rc):
                    continue

                ltbl = alias_map.get(la)
                rtbl = alias_map.get(ra)
                if not ltbl or not rtbl:
                    continue

                lcols = get_column_set(ltbl[0], ltbl[1])
                rcols = get_column_set(rtbl[0], rtbl[1])

                if lc.lower() not in lcols:
                    missing_ref(la, lc, ltbl[0], ltbl[1])
                if rc.lower() not in rcols:
                    missing_ref(ra, rc, rtbl[0], rtbl[1])

        # selected_output_columns are compiled from (table_ref, column) pairs.
        for oc in plan.get("selected_output_columns") or []:
            if not isinstance(oc, dict):
                continue
            tref = str(oc.get("table_ref") or "").strip()
            col = str(oc.get("column") or "").strip()
            if not tref or not col:
                continue

            tbl = alias_map.get(tref)
            if not tbl:
                missing.append(f"{tref}.{col} (unknown table_ref alias)")
                continue

            cols = get_column_set(tbl[0], tbl[1])
            if col.lower() not in cols:
                missing_ref(tref, col, tbl[0], tbl[1])

        # structured_filters and order_by are compiled against base alias `b0`
        base_cols = get_column_set(base_schema, base_table)
        for f in plan.get("structured_filters") or []:
            if not isinstance(f, dict):
                continue
            c = str(f.get("column") or "").strip()
            if c and c.lower() not in base_cols:
                missing_ref("b0", c, base_schema, base_table)

        for c in plan.get("order_by") or []:
            if not isinstance(c, str):
                continue
            cc = c.strip()
            if cc and cc.lower() not in base_cols:
                missing_ref("b0", cc, base_schema, base_table)

    elif mode == "union":
        branches = plan.get("union_branches") or []
        cols = plan.get("union_select_columns") or []
        if not isinstance(cols, list):
            cols = []

        for br in branches:
            if not isinstance(br, dict):
                continue
            bs = str(br.get("schema_name") or "").strip()
            bt = str(br.get("table_name") or "").strip()
            if not bs or not bt:
                continue
            bcols = get_column_set(bs, bt)
            for c in cols:
                if not isinstance(c, str):
                    continue
                cc = c.strip()
                if cc and cc.lower() not in bcols:
                    missing.append(f"union column '{cc}' missing in {bs}.{bt}")

    elif mode == "lookup":
        lk = plan.get("lookup") or {}
        if not isinstance(lk, dict):
            raise TransformPlanValidationError(
                "lookup block missing or invalid.",
                ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
            )

        lu_alias = str(lk.get("alias") or "lu").strip()
        lookup_schema = str(lk.get("schema_name") or "").strip()
        lookup_table = str(lk.get("table_name") or "").strip()
        if not lookup_schema or not lookup_table:
            raise TransformPlanValidationError(
                "lookup schema_name/table_name missing.",
                ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
            )

        alias_map: Dict[str, Tuple[str, str]] = {
            "b0": (base_schema, base_table),
            lu_alias: (lookup_schema, lookup_table),
        }

        # Validate main/lookup key and passthrough/add columns.
        base_cols = get_column_set(base_schema, base_table)
        lookup_cols = get_column_set(lookup_schema, lookup_table)

        main_key = str(lk.get("main_key_column") or "").strip()
        if main_key and main_key.lower() not in base_cols:
            missing_ref("b0", main_key, base_schema, base_table)

        lookup_key = str(lk.get("lookup_key_column") or "").strip()
        if lookup_key and lookup_key.lower() not in lookup_cols:
            missing_ref(lu_alias, lookup_key, lookup_schema, lookup_table)

        for c in lk.get("main_pass_through_columns") or []:
            if not isinstance(c, str):
                continue
            cc = c.strip()
            if cc and cc.lower() not in base_cols:
                missing_ref("b0", cc, base_schema, base_table)

        for a in lk.get("add_columns") or []:
            if not isinstance(a, dict):
                continue
            lc = str(a.get("lookup_column") or "").strip()
            if lc and lc.lower() not in lookup_cols:
                missing_ref(lu_alias, lc, lookup_schema, lookup_table)

        # selected_output_columns should match what compilation exposes.
        for oc in plan.get("selected_output_columns") or []:
            if not isinstance(oc, dict):
                continue
            tref = str(oc.get("table_ref") or "").strip()
            col = str(oc.get("column") or "").strip()
            if not tref or not col:
                continue
            tbl = alias_map.get(tref)
            if not tbl:
                missing.append(f"{tref}.{col} (unknown table_ref alias)")
                continue
            cols_set = get_column_set(tbl[0], tbl[1])
            if col.lower() not in cols_set:
                missing_ref(tref, col, tbl[0], tbl[1])

        # structured_filters and order_by compile against base alias `b0`
        for f in plan.get("structured_filters") or []:
            if not isinstance(f, dict):
                continue
            c = str(f.get("column") or "").strip()
            if c and c.lower() not in base_cols:
                missing_ref("b0", c, base_schema, base_table)

        for c in plan.get("order_by") or []:
            if not isinstance(c, str):
                continue
            cc = c.strip()
            if cc and cc.lower() not in base_cols:
                missing_ref("b0", cc, base_schema, base_table)

    else:
        # Unknown mode: let validate_transform_plan handle mode correctness,
        # but provide a clear error if this function is called too early.
        raise TransformPlanValidationError(
            f"Unsupported transform mode '{mode}' for column reference validation.",
            ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
        )

    if missing:
        # Keep message readable and stable for UI display.
        uniq = []
        seen = set()
        for m in missing:
            if m in seen:
                continue
            seen.add(m)
            uniq.append(m)

        msg = "Invalid column reference(s): " + "; ".join(uniq)

        if missing_tables:
            # Include available physical columns to make the error actionable.
            # Keep formatting simple so UI renders consistently.
            lines: List[str] = []
            for schema_name, table_name in sorted(
                missing_tables, key=lambda x: (x[0].lower(), x[1].lower())
            ):
                cols = sorted(get_column_set(schema_name, table_name), key=lambda s: s.lower())
                # Avoid huge messages if a table has many columns.
                max_cols = 50
                suffix = ""
                if len(cols) > max_cols:
                    cols = cols[:max_cols]
                    suffix = " (truncated)"
                lines.append(
                    f"Available columns for {schema_name}.{table_name}: [{', '.join(cols)}]{suffix}"
                )
            msg += " | " + " | ".join(lines)

        raise TransformPlanValidationError(msg, ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE)


def _compile_select_inner(plan: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Build core SELECT SQL (no outer LIMIT/TOP). Returns (sql_body, warnings)."""
    warnings: List[str] = []
    db_type = normalize_internal_db_type(plan.get("source_db_type") or "")
    mode = (plan.get("mode") or "single_table").strip().lower()

    if mode == "single_table":
        b = plan["base_table"]
        tref = _quote_table(db_type, b["schema_name"], b["table_name"])
        parts = [f"SELECT * FROM {tref} AS {_quote_ident(db_type, 'b0')}"]
        where_sql, where_warnings = _compile_where_sql(plan.get("structured_filters") or [], db_type, "b0")
        warnings.extend(where_warnings)
        if where_sql:
            parts.append(f"WHERE {where_sql}")
        parts.extend(_compile_order_by(plan.get("order_by") or [], db_type, "b0"))
        sql_body = " ".join(p for p in parts if p)
        return sql_body, warnings

    if mode == "union":
        branches = plan["union_branches"]
        cols = plan["union_select_columns"]
        selects = []
        for br in branches:
            tq = _quote_table(db_type, br["schema_name"], br["table_name"])
            col_list = ", ".join(f"{_quote_ident(db_type, c)}" for c in cols)
            selects.append(f"SELECT {col_list} FROM {tq}")
        sql_body = " UNION ALL ".join(selects)
        return sql_body, warnings

    if mode == "lookup":
        lk = plan["lookup"]
        b = plan["base_table"]
        main_t = _quote_table(db_type, b["schema_name"], b["table_name"])
        lu_t = _quote_table(db_type, lk["schema_name"], lk["table_name"])
        b0 = _quote_ident(db_type, "b0")
        lu = _quote_ident(db_type, lk["alias"])
        pass_cols = [
            f"{b0}.{_quote_ident(db_type, c)} AS {_quote_ident(db_type, c)}"
            for c in lk["main_pass_through_columns"]
        ]
        add_cols = [
            f"{lu}.{_quote_ident(db_type, a['lookup_column'])} AS {_quote_ident(db_type, a['as'])}"
            for a in lk["add_columns"]
        ]
        on_clause = (
            f"{b0}.{_quote_ident(db_type, lk['main_key_column'])} = "
            f"{lu}.{_quote_ident(db_type, lk['lookup_key_column'])}"
        )
        sel = ", ".join(pass_cols + add_cols)
        parts = [f"SELECT {sel} FROM {main_t} AS {b0}", f"LEFT JOIN {lu_t} AS {lu}", f"ON {on_clause}"]
        where_sql, where_warnings = _compile_where_sql(plan.get("structured_filters") or [], db_type, "b0")
        warnings.extend(where_warnings)
        if where_sql:
            parts.append(f"WHERE {where_sql}")
        parts.extend(_compile_order_by(plan.get("order_by") or [], db_type, "b0"))
        sql_body = " ".join(parts)
        return sql_body, warnings

    # join
    b = plan["base_table"]
    main_t = _quote_table(db_type, b["schema_name"], b["table_name"])
    b0 = _quote_ident(db_type, "b0")
    from_clause = f"FROM {main_t} AS {b0}"
    for node in plan["join_nodes"]:
        jt = node["join_type"]
        if jt == "FULL":
            join_kw = "FULL OUTER JOIN"
        else:
            join_kw = f"{jt} JOIN"
        jt_quoted = _quote_table(db_type, node["schema_name"], node["table_name"])
        ja = _quote_ident(db_type, node["alias"])
        on_parts = []
        for cond in node["on"]:
            la = _quote_ident(db_type, cond["left_alias"])
            ra = _quote_ident(db_type, cond["right_alias"])
            lc = _quote_ident(db_type, cond["left_column"])
            rc = _quote_ident(db_type, cond["right_column"])
            on_parts.append(f"{la}.{lc} = {ra}.{rc}")
        on_sql = " AND ".join(on_parts)
        from_clause = f"{from_clause} {join_kw} {jt_quoted} AS {ja} ON {on_sql}"

    outs = plan["selected_output_columns"]
    sel_list = []
    for oc in outs:
        ta = _quote_ident(db_type, oc["table_ref"])
        col = _quote_ident(db_type, oc["column"])
        alias = _quote_ident(db_type, oc["alias"])
        sel_list.append(f"{ta}.{col} AS {alias}")
    sel = ", ".join(sel_list)
    parts = [f"SELECT {sel}", from_clause]
    where_sql, where_warnings = _compile_where_sql(plan.get("structured_filters") or [], db_type, "b0")
    warnings.extend(where_warnings)
    if where_sql:
        parts.append(f"WHERE {where_sql}")
    parts.extend(_compile_order_by(plan.get("order_by") or [], db_type, "b0"))
    sql_body = " ".join(parts)
    return sql_body, warnings


def compile_select_from_plan(
    plan: Dict[str, Any], *, preview_limit: Optional[int] = None
) -> Tuple[str, List[str]]:
    """
    Build SELECT from a validated plan.
    If preview_limit is set, wrap with per-DB row cap (wizard preview).
    If None, return unconstrained SQL for runtime sync (batching uses connector LIMIT/OFFSET).
    """
    sql_body, warnings = _compile_select_inner(plan)
    db_type = normalize_internal_db_type(plan.get("source_db_type") or "")
    mode = (plan.get("mode") or "single_table").strip().lower()
    if preview_limit is None:
        return sql_body, warnings
    lim = max(1, min(int(preview_limit), 500))
    if mode == "union":
        return _wrap_limit_outer(sql_body, db_type, lim), warnings
    return _wrap_limit(sql_body, db_type, lim), warnings


def compile_preview_select(plan: Dict[str, Any], *, limit: int = 50) -> Tuple[str, List[str]]:
    """Build SELECT SQL with LIMIT/TOP/FETCH. Returns (sql, warnings)."""
    return compile_select_from_plan(plan, preview_limit=limit)


def uses_transform_runtime(plan_raw: Any) -> bool:
    if not isinstance(plan_raw, dict):
        return False
    mode = (plan_raw.get("mode") or "single_table").strip().lower()
    return mode in ("join", "union", "lookup")


def check_transform_db_type_drift(plan: Dict[str, Any], current_connector_db_type: str) -> None:
    stored = plan.get("source_db_type")
    if stored is None or stored == "":
        return
    cur = normalize_internal_db_type(current_connector_db_type)
    stor = normalize_internal_db_type(str(stored))
    if cur != stor:
        raise TransformPlanValidationError(
            f"Source database type changed since the model was saved (was {stor}, now {cur}). "
            "Re-open the job wizard model step and save again, or reset the transform plan.",
            ERROR_TRANSFORM_DB_TYPE_DRIFT,
        )


def trim_transform_plan_for_runtime(
    plan: Dict[str, Any],
    excluded_cols_lower: Set[str],
    protected_cols_lower: Set[str],
) -> Dict[str, Any]:
    """Apply Step 3 exclusions to transform output columns (copy)."""
    eff = excluded_cols_lower - protected_cols_lower
    if not eff:
        return plan
    out = copy.deepcopy(plan)
    mode = (out.get("mode") or "single_table").strip().lower()
    if mode == "join":
        outs = [
            o
            for o in (out.get("selected_output_columns") or [])
            if isinstance(o, dict) and (o.get("alias") or "").strip().lower() not in eff
        ]
        if not outs:
            raise TransformPlanValidationError(
                "All model output columns are excluded; adjust exclusions or the model.",
                ERROR_TRANSFORM_PLAN_INVALID,
            )
        out["selected_output_columns"] = outs
    elif mode == "union":
        cols = [
            c
            for c in (out.get("union_select_columns") or [])
            if isinstance(c, str) and c.strip().lower() not in eff
        ]
        if not cols:
            raise TransformPlanValidationError(
                "All union columns are excluded; adjust exclusions or the model.",
                ERROR_TRANSFORM_PLAN_INVALID,
            )
        out["union_select_columns"] = cols
        out["selected_output_columns"] = [{"alias": c, "table_ref": None, "column": c} for c in cols]
    elif mode == "lookup":
        lk = out.get("lookup") or {}
        lk = copy.deepcopy(lk)
        lk["main_pass_through_columns"] = [
            c
            for c in (lk.get("main_pass_through_columns") or [])
            if isinstance(c, str) and c.strip().lower() not in eff
        ]
        lk["add_columns"] = [
            a
            for a in (lk.get("add_columns") or [])
            if isinstance(a, dict) and (a.get("as") or "").strip().lower() not in eff
        ]
        out["lookup"] = lk
        outs = [
            o
            for o in (out.get("selected_output_columns") or [])
            if isinstance(o, dict) and (o.get("alias") or "").strip().lower() not in eff
        ]
        if not outs:
            raise TransformPlanValidationError(
                "All lookup output columns are excluded; adjust exclusions or the model.",
                ERROR_TRANSFORM_PLAN_INVALID,
            )
        out["selected_output_columns"] = outs
        if not lk["main_pass_through_columns"] or not lk["add_columns"]:
            raise TransformPlanValidationError(
                "Lookup model has no remaining columns after exclusions.",
                ERROR_TRANSFORM_PLAN_INVALID,
            )
    return out


def column_infos_from_transform_plan(plan: Dict[str, Any]) -> List[ColumnInfo]:
    """Synthetic ColumnInfo rows for target DDL from transform output aliases."""
    mcols = mapping_columns_from_plan(plan) or []
    return [
        ColumnInfo(
            name=c["name"],
            data_type=c.get("data_type") or "varchar",
            is_nullable=True,
            is_primary_key=False,
            max_length=None,
            default_value=None,
        )
        for c in mcols
    ]


def prepare_runtime_transform_plan(
    job_table: Any,
    job: Any,
    source_db_type: str,
    *,
    excluded_cols_lower: Set[str],
    protected_cols_lower: Set[str],
) -> Optional[Dict[str, Any]]:
    """
    Validate drift + exclusions; return trimmed plan for join/union/lookup, or None for legacy path.
    """
    raw = getattr(job_table, "transform_plan", None)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TransformPlanValidationError(
            "transform_plan must be a JSON object when provided.",
            ERROR_TRANSFORM_PLAN_INVALID,
        )

    mode = (raw.get("mode") or "").strip().lower()
    # Contract: single_table uses legacy SELECT/transformation pipeline.
    if mode in ("", "single_table"):
        return None
    if mode not in ("join", "union", "lookup"):
        raise TransformPlanValidationError(
            f"Invalid transform_plan mode '{mode}'.",
            ERROR_TRANSFORM_PLAN_INVALID,
        )
    if not uses_transform_runtime(raw):
        # Defensive: if mode checks drift, keep legacy path safe.
        return None

    plan_key = f"{job_table.schema_name}.{job_table.table_name}"
    allowed = {f"{t.schema_name}.{t.table_name}" for t in job.tables.all()}
    validated = validate_transform_plan(
        raw,
        plan_table_key=plan_key,
        allowed_table_keys=allowed,
        source_db_type=source_db_type,
    )
    check_transform_db_type_drift(validated, source_db_type)
    return trim_transform_plan_for_runtime(validated, excluded_cols_lower, protected_cols_lower)


def runtime_output_aliases(plan: Dict[str, Any]) -> List[str]:
    """Ordered output column names as returned by the transform SELECT."""
    mcols = mapping_columns_from_plan(plan) or []
    return [c["name"] for c in mcols]


def validate_incremental_key_from_base(plan: Dict[str, Any], incremental_column_alias: str) -> None:
    """
    Incremental watermark/keyset semantics require the incremental key to be tied to the base-table row grain.

    In the validated plan representation, that means the output alias for `incremental_column_alias`
    must point to the base alias `b0` in `selected_output_columns`.
    """
    if not isinstance(plan, dict):
        raise TransformPlanValidationError("Transform plan is not a JSON object.", ERROR_TRANSFORM_PLAN_INVALID)

    mode = (plan.get("mode") or "").strip().lower()
    if mode not in ("join", "lookup"):
        # UNION is handled separately by the sync executor, but keep this guardrail explicit.
        raise TransformPlanValidationError(
            "Incremental sync supports only join/lookup transform modes.",
            ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM,
        )

    wanted = (incremental_column_alias or "").strip().lower()
    outputs = plan.get("selected_output_columns") or []
    for oc in outputs:
        if not isinstance(oc, dict):
            continue
        if str(oc.get("alias") or "").strip().lower() != wanted:
            continue
        table_ref = str(oc.get("table_ref") or "").strip().lower()
        if table_ref != "b0":
            raise TransformPlanValidationError(
                "Incremental model transforms require the incremental column to come from the base table "
                "(table_ref='b0') to keep checkpoint semantics consistent.",
                ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM,
            )
        return

    raise TransformPlanValidationError(
        f"Incremental column '{incremental_column_alias}' is not present in transform outputs.",
        ERROR_TRANSFORM_PLAN_INVALID,
    )


def _compile_where_sql(filters: List[Dict[str, Any]], db_type: str, default_alias: str) -> Tuple[str, List[str]]:
    if not filters:
        return "", []
    warnings = []
    parts = []
    fa = _quote_ident(db_type, default_alias)
    for f in filters:
        col = _quote_ident(db_type, f["column"])
        op = f["op"]
        if op == "IS NULL":
            parts.append(f"{fa}.{col} IS NULL")
        elif op == "IS NOT NULL":
            parts.append(f"{fa}.{col} IS NOT NULL")
        else:
            val_sql = _format_filter_value_sql(db_type, f.get("value"), op)
            parts.append(f"{fa}.{col} {op} {val_sql}")
    return " AND ".join(parts), warnings


def _compile_order_by(order_by: List[str], db_type: str, alias: str) -> List[str]:
    if not order_by:
        return []
    a = _quote_ident(db_type, alias)
    ob = ", ".join(f"{a}.{_quote_ident(db_type, c)}" for c in order_by)
    return [f"ORDER BY {ob}"]


def _wrap_limit(sql_body: str, db_type: str, lim: int) -> str:
    qa = _quote_ident(db_type, "preview_sub")
    if db_type == "sqlserver":
        return f"SELECT TOP {lim} * FROM ({sql_body}) AS {qa}"
    if db_type == "oracle":
        return f"SELECT * FROM ({sql_body}) {qa} WHERE ROWNUM <= {lim}"
    return f"{sql_body} LIMIT {lim}"


def _wrap_limit_outer(sql_body: str, db_type: str, lim: int) -> str:
    qa = _quote_ident(db_type, "union_sub")
    if db_type == "oracle":
        sub = f"SELECT * FROM ({sql_body}) {qa}"
    else:
        sub = f"SELECT * FROM ({sql_body}) AS {qa}"
    return _wrap_limit(sub, db_type, lim)


def serialize_preview_value(val: Any) -> Any:
    """JSON-safe cell value for preview API."""
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    from decimal import Decimal

    if isinstance(val, Decimal):
        return str(val)
    from datetime import date, datetime, time

    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace")
        except Exception:
            return str(val)
    return str(val)


def execute_preview_query(connector: Any, sql: str, max_rows: int = 50) -> Tuple[List[str], List[List[Any]]]:
    """
    Run SELECT on connector; return (column_names, rows as JSON-serializable lists).
    """
    if not getattr(connector, "_connection", None):
        connector.connect()
    conn = connector._connection
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        desc = cursor.description or []
        columns = [d[0] for d in desc] if desc else []
        raw_rows = cursor.fetchall()
        out_rows = []
        for row in raw_rows[:max_rows]:
            if row is None:
                continue
            if hasattr(row, "keys") and callable(row.keys):
                out_rows.append([serialize_preview_value(row[k]) for k in columns])
            else:
                out_rows.append([serialize_preview_value(v) for v in tuple(row)])
        return columns, out_rows
    finally:
        cursor.close()


def mapping_columns_from_plan(plan: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """
    If plan defines output columns, return synthetic column dicts for mapping step.
    """
    mode = (plan.get("mode") or "single_table").strip().lower()
    if mode == "single_table":
        return None
    outs = plan.get("selected_output_columns") or []
    if not isinstance(outs, list):
        return None
    columns = []
    for oc in outs:
        if not isinstance(oc, dict):
            continue
        alias = oc.get("alias")
        if not alias:
            continue
        src_type = oc.get("data_type") or "varchar"
        columns.append(
            {
                "name": alias,
                "column_name": alias,
                "data_type": src_type,
                "is_nullable": True,
                "is_primary_key": False,
            }
        )
    return columns if columns else None


def suggest_join_keys(
    left_columns: List[str],
    right_columns: List[str],
) -> List[Dict[str, Any]]:
    """
    Suggest join key pairs using safe name-based heuristics.
    Returns ordered candidates with coarse confidence labels.
    """
    left = [str(c).strip() for c in (left_columns or []) if str(c).strip()]
    right = [str(c).strip() for c in (right_columns or []) if str(c).strip()]
    if not left or not right:
        return []
    left_l = {c.lower(): c for c in left}
    right_l = {c.lower(): c for c in right}
    out: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()

    def push(lc: str, rc: str, confidence: str) -> None:
        k = (lc.lower(), rc.lower())
        if k in seen:
            return
        seen.add(k)
        out.append(
            {
                "left_column": lc,
                "right_column": rc,
                "confidence": confidence,
            }
        )

    # Exact normalized name match first.
    for ll, lc in left_l.items():
        if ll in right_l:
            push(lc, right_l[ll], "high")

    # Common id-pattern matches.
    id_aliases = ("id",)
    for ll, lc in left_l.items():
        if ll.endswith("id"):
            for rr, rc in right_l.items():
                if rr.endswith("id"):
                    if ll == rr:
                        push(lc, rc, "high")
                    elif ll in id_aliases or rr in id_aliases:
                        push(lc, rc, "medium")
                    elif ll[:-2] == rr[:-2]:
                        push(lc, rc, "medium")
    return out[:20]


def validate_custom_sql_preview(sql: str) -> str:
    """
    Validate admin-provided SQL for preview-only safety.
    Enforces a single SELECT statement and blocks obvious DDL/DML tokens.
    """
    query = (sql or "").strip()
    if not query:
        raise TransformPlanValidationError("custom_sql query is required.", "invalid_custom_sql")
    ql = query.lower()
    if ";" in query:
        raise TransformPlanValidationError(
            "custom_sql must contain a single SELECT statement without semicolons.",
            "invalid_custom_sql",
        )
    if not ql.startswith("select "):
        raise TransformPlanValidationError("custom_sql must start with SELECT.", "invalid_custom_sql")
    blocked = (
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " truncate ",
        " create ",
        " merge ",
        " grant ",
        " revoke ",
        " execute ",
        " exec ",
    )
    padded = f" {ql} "
    for token in blocked:
        if token in padded:
            raise TransformPlanValidationError(
                f"custom_sql contains blocked token '{token.strip()}'.",
                "invalid_custom_sql",
            )
    return query


def validate_transform_builder_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate the high-level Step 3 builder payload.
    Returns normalized payload (not the runtime transform plan).
    """
    if not isinstance(payload, dict):
        raise TransformPlanValidationError("builder payload must be an object.", "invalid_builder_payload")
    mode = str(payload.get("mode") or "single_table").strip().lower()
    if mode not in {"single_table", "join", "union", "lookup", "custom_sql"}:
        raise TransformPlanValidationError(f"Unsupported builder mode '{mode}'.", "invalid_builder_payload")
    out = dict(payload)
    out["mode"] = mode
    return out


def builder_to_transform_plan(
    payload: Dict[str, Any],
    *,
    plan_table_key: str,
    allowed_table_keys: Set[str],
    source_db_type: str,
    allow_custom_sql: bool = False,
) -> Dict[str, Any]:
    """
    Compile builder payload into the canonical validated transform plan shape.
    """
    normalized = validate_transform_builder_payload(payload)
    mode = normalized["mode"]

    if mode == "custom_sql":
        if not allow_custom_sql:
            raise TransformPlanValidationError("custom_sql mode is admin-only.", "custom_sql_not_allowed")
        query = validate_custom_sql_preview(str(normalized.get("custom_sql") or ""))
        # Preserve as single_table runtime plan while attaching admin-only preview metadata.
        base_schema, base_table = plan_table_key.split(".", 1)
        return {
            "mode": "single_table",
            "source_db_type": normalize_internal_db_type(source_db_type),
            "base_table": {"schema_name": base_schema, "table_name": base_table},
            "join_nodes": [],
            "union_branches": [],
            "union_select_columns": [],
            "lookup": None,
            "selected_output_columns": [],
            "structured_filters": [],
            "order_by": [],
            "derived_columns": [],
            "_custom_sql_preview_only": query,
        }

    # Other modes are already close to canonical and go through existing validator.
    return validate_transform_plan(
        normalized,
        plan_table_key=plan_table_key,
        allowed_table_keys=allowed_table_keys,
        source_db_type=source_db_type,
    )

