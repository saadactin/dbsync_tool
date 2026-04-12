"""
Helpers for building BSON-safe MongoDB documents from SQL rows.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any, Iterable, List, Optional, Sequence


def sanitize_mongo_key(key: Any) -> str:
    name = str(key or "").strip()
    if not name:
        return "_field"
    name = name.replace(".", "_")
    if name.startswith("$"):
        name = f"_{name[1:]}" if len(name) > 1 else "_field"
    return name


def normalize_mongo_value(value: Any) -> Any:
    """Normalize values to BSON-safe representations."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.time):
        return value.isoformat()
    if isinstance(value, dt.date):
        # BSON datetime cannot store date-only objects directly.
        return dt.datetime.combine(value, dt.time.min)
    if isinstance(value, Decimal):
        try:
            from bson.decimal128 import Decimal128  # type: ignore

            return Decimal128(str(value))
        except Exception:
            return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        try:
            from bson.binary import Binary  # type: ignore

            return Binary(raw)
        except Exception:
            return base64.b64encode(raw).decode("ascii")
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[sanitize_mongo_key(k)] = normalize_mongo_value(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [normalize_mongo_value(v) for v in value]
    return value


def _to_stable_json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _derive_document_id(
    source_columns: Sequence[str],
    row: Sequence[Any],
    pk_columns: Optional[Iterable[str]] = None,
    payload_for_fallback: Optional[dict] = None,
) -> str:
    by_lower = {str(c).lower(): i for i, c in enumerate(source_columns)}
    pk_cols = [str(c) for c in (pk_columns or []) if c]

    if pk_cols:
        vals: List[Any] = []
        for pk in pk_cols:
            idx = by_lower.get(pk.lower())
            if idx is None:
                vals = []
                break
            vals.append(row[idx])
        if vals and all(v is not None for v in vals):
            if len(vals) == 1:
                return str(vals[0])
            norm_vals = [normalize_mongo_value(v) for v in vals]
            return hashlib.sha256(_to_stable_json(norm_vals).encode("utf-8")).hexdigest()

    payload = payload_for_fallback or {}
    return hashlib.sha256(_to_stable_json(payload).encode("utf-8")).hexdigest()


def build_document_from_sql_row(
    source_columns: Sequence[str],
    target_fields: Sequence[str],
    row: Sequence[Any],
    pk_columns: Optional[Iterable[str]] = None,
    origin_job_id: Optional[str] = None,
    origin_field_name: str = "__dbsync_origin_job_id",
) -> dict:
    doc = {}
    for i, field in enumerate(target_fields):
        key = sanitize_mongo_key(field)
        value = row[i] if i < len(row) else None
        doc[key] = normalize_mongo_value(value)

    doc["_id"] = _derive_document_id(
        source_columns=source_columns,
        row=row,
        pk_columns=pk_columns,
        payload_for_fallback=doc,
    )
    if origin_job_id:
        doc[sanitize_mongo_key(origin_field_name)] = str(origin_job_id)
    return doc

