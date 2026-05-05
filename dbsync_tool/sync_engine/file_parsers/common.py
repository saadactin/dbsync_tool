"""Shared parser helpers."""
from pathlib import Path
from typing import Dict, Iterable, List


def normalize_headers(raw: Iterable[str]) -> List[str]:
    """Strip, dedupe and provide column_N fallbacks for header rows."""
    seen: Dict[str, int] = {}
    cleaned: List[str] = []
    for idx, value in enumerate(raw):
        text = str(value).strip() if value is not None else ''
        if not text:
            text = f'column_{idx + 1}'
        base = text
        n = seen.get(base.lower(), 0)
        if n:
            text = f'{base}_{n + 1}'
        seen[base.lower()] = n + 1
        cleaned.append(text)
    return cleaned


def resolve_source_path(file_source) -> Path:
    """Resolve the underlying flat-file path safely under FILE_SYNC_ROOT."""
    from connections.file_source_paths import resolve_safe_source_path

    return resolve_safe_source_path(getattr(file_source, 'relative_path', ''))
