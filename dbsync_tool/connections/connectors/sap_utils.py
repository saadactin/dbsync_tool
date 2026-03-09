"""
SAP data transformation utilities for sync (flatten, hash, schema merge).
Used by SAP sync executor (Day 4) and for change detection.
"""
import hashlib
import json
from typing import Any, Dict, List


def flatten_dict(d: dict, parent_key: str = "", sep: str = "_") -> dict:
    """
    Recursively flatten nested dicts. Keys become e.g. parent_key_child_key.
    Lists are serialized to JSON string so nested JSON from SAP becomes one-level dicts.
    """
    items: List[tuple] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            items.append((new_key, json.dumps(v, sort_keys=True) if v else "[]"))
        else:
            items.append((new_key, v))
    return dict(items)


def compute_record_hash(record: dict) -> str:
    """
    Return a stable hash for a record (for change detection in incremental sync).
    Uses SHA256 of sorted JSON representation.
    """
    canonical = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def merge_schemas(schemas: List[dict]) -> dict:
    """
    Merge a list of record dicts (or flattened key sets) into a single schema (set of keys).
    Each element can be a dict; keys from all dicts are merged.
    Returns a dict mapping key -> None (or key -> type hint if needed); used for target table schema.
    """
    merged: Dict[str, Any] = {}
    for s in schemas:
        if isinstance(s, dict):
            for k in s.keys():
                merged[k] = None
        else:
            merged[str(s)] = None
    return merged
