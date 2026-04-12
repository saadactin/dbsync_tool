"""
Hash helpers for flat-file hybrid incremental sync.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def _resolve_hash_name(algorithm: str) -> str:
    algo = (algorithm or "sha256").strip().lower()
    if algo not in hashlib.algorithms_available:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")
    return algo


def compute_file_hash(path: Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    """Compute file hash in streaming mode."""
    algo = _resolve_hash_name(algorithm)
    h = hashlib.new(algo)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _stable_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def compute_row_hash(
    row: Mapping[str, object],
    columns: Sequence[str],
    algorithm: str = "sha256",
) -> str:
    """Compute deterministic row hash for selected columns."""
    algo = _resolve_hash_name(algorithm)
    payload = {col: _stable_value(row.get(col)) for col in columns}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    h = hashlib.new(algo)
    h.update(encoded)
    return h.hexdigest()


def normalize_hash_columns(effective_headers: Sequence[str], configured_columns: Iterable[str] | None) -> list[str]:
    """
    Resolve hash column allowlist against effective headers.
    Empty config falls back to all effective headers.
    """
    by_lower = {h.lower(): h for h in effective_headers if h}
    out: list[str] = []
    if not configured_columns:
        return [h for h in effective_headers if h]
    for col in configured_columns:
        key = (str(col or "")).strip().lower()
        if key in ("none", "null"):
            continue
        if not key:
            continue
        resolved = by_lower.get(key)
        if resolved:
            out.append(resolved)
    # Dedupe while preserving order
    seen = set()
    deduped: list[str] = []
    for col in out:
        kl = col.lower()
        if kl in seen:
            continue
        seen.add(kl)
        deduped.append(col)
    # If user configured columns but none matched (common when UI posts "None"),
    # fall back safely to all effective columns.
    return deduped if deduped else [h for h in effective_headers if h]
