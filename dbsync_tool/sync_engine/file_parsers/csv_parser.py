"""CSV / TSV / TXT delimited parser."""
from __future__ import annotations

import csv
from typing import Dict, Iterable, List, Tuple

from sync_engine.exceptions import FlatFileReadError

from .common import normalize_headers, resolve_source_path


_FORMAT_DEFAULT_DELIMITER = {
    'csv': ',',
    'tsv': '\t',
    'txt': ',',
}


def _resolve_delimiter(file_source) -> str:
    fmt = (getattr(file_source, 'file_format', None) or 'csv').lower()
    raw = getattr(file_source, 'delimiter', None)
    if isinstance(raw, str) and len(raw) == 1:
        return raw
    return _FORMAT_DEFAULT_DELIMITER.get(fmt, ',')


def iter_records(
    file_source,
    *,
    chunk_size: int = 1000,
    encoding: str = 'utf-8',
) -> Tuple[List[str], Iterable[List[Dict[str, str]]], Dict[str, int]]:
    if chunk_size <= 0:
        chunk_size = 1000
    path = resolve_source_path(file_source)
    delimiter = _resolve_delimiter(file_source)
    has_header = bool(getattr(file_source, 'has_header', True))

    stats: Dict[str, int] = {
        'rows_read': 0,
        'rows_padded': 0,
        'rows_truncated': 0,
        'single_column_warning': 0,
    }

    try:
        with path.open('r', encoding=encoding, newline='') as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            if has_header:
                raw_headers = next(reader, [])
            else:
                first = next(reader, [])
                raw_headers = [f'column_{idx + 1}' for idx in range(len(first))]
            headers = normalize_headers(raw_headers)
    except UnicodeDecodeError as exc:
        raise FlatFileReadError(
            f"Failed to decode flat file with encoding {encoding}: {exc}"
        ) from exc
    except FileNotFoundError as exc:
        raise FlatFileReadError(f"File not found: {path}") from exc

    if len(headers) == 1:
        stats['single_column_warning'] = 1

    def _row_to_dict(raw: List[str]) -> Dict[str, str]:
        row_vals = list(raw)
        if len(row_vals) < len(headers):
            row_vals.extend([''] * (len(headers) - len(row_vals)))
            stats['rows_padded'] += 1
        if len(row_vals) > len(headers):
            row_vals = row_vals[: len(headers)]
            stats['rows_truncated'] += 1
        stats['rows_read'] += 1
        return {
            headers[idx]: ('' if row_vals[idx] is None else str(row_vals[idx]))
            for idx in range(len(headers))
        }

    def _iterator():
        with path.open('r', encoding=encoding, newline='') as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            if has_header:
                next(reader, None)
            chunk: List[Dict[str, str]] = []
            for raw in reader:
                chunk.append(_row_to_dict(raw))
                if len(chunk) >= chunk_size:
                    yield chunk
                    chunk = []
            if chunk:
                yield chunk

    return headers, _iterator(), stats
