"""JSON and JSONL/NDJSON parser."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from django.conf import settings

from sync_engine.exceptions import FlatFileReadError

from .common import normalize_headers, resolve_source_path


MAX_JSON_DEPTH = int(getattr(settings, 'FILE_FORMAT_JSON_MAX_DEPTH', 64))
HEADER_SAMPLE_SIZE = 64


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise FlatFileReadError(
            f"JSON nesting exceeds maximum depth of {MAX_JSON_DEPTH}."
        )
    if isinstance(value, Mapping):
        for v in value.values():
            _check_depth(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _check_depth(v, depth + 1)


def _drill_path(payload: Any, dotted: str) -> Any:
    if not dotted:
        return payload
    cur = payload
    for token in dotted.split('.'):
        if isinstance(cur, Mapping):
            cur = cur.get(token)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(token)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def _flatten(record: Any, separator: str, prefix: str = '') -> Dict[str, str]:
    out: Dict[str, str] = {}
    if isinstance(record, Mapping):
        if not record:
            out[prefix or 'value'] = '{}'
            return out
        for key, value in record.items():
            new_key = f'{prefix}{separator}{key}' if prefix else str(key)
            if isinstance(value, Mapping):
                out.update(_flatten(value, separator, new_key))
            elif isinstance(value, (list, tuple)):
                try:
                    out[new_key] = json.dumps(value, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    out[new_key] = str(value)
            elif value is None:
                out[new_key] = ''
            else:
                out[new_key] = str(value)
        return out
    if isinstance(record, (list, tuple)):
        out[prefix or 'value'] = json.dumps(list(record), ensure_ascii=False, default=str)
        return out
    out[prefix or 'value'] = '' if record is None else str(record)
    return out


def _to_blob_row(record: Any) -> Dict[str, str]:
    if not isinstance(record, Mapping):
        if record is None:
            return {'value': ''}
        if isinstance(record, (list, tuple)):
            return {'value': json.dumps(record, ensure_ascii=False, default=str)}
        return {'value': str(record)}
    out: Dict[str, str] = {}
    for key, value in record.items():
        if value is None:
            out[str(key)] = ''
        elif isinstance(value, (Mapping, list, tuple)):
            try:
                out[str(key)] = json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                out[str(key)] = str(value)
        else:
            out[str(key)] = str(value)
    return out


def _record_to_dict(record: Any, strategy: str, separator: str) -> Dict[str, str]:
    if strategy == 'json_blob':
        return _to_blob_row(record)
    return _flatten(record, separator)


def _iter_jsonl(path, encoding: str) -> Iterable[Any]:
    with path.open('r', encoding=encoding) as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise FlatFileReadError(
                    f"Invalid JSON on line {line_no}: {exc.msg}"
                ) from exc


def _iter_json(path, encoding: str, record_path: str) -> Iterable[Any]:
    with path.open('r', encoding=encoding) as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise FlatFileReadError(f"Invalid JSON document: {exc.msg}") from exc
    _check_depth(payload)
    target = _drill_path(payload, record_path) if record_path else payload
    if target is None:
        return
    if isinstance(target, list):
        for item in target:
            yield item
        return
    yield target


def _collect_headers(samples: Sequence[Mapping[str, Any]]) -> List[str]:
    seen: Dict[str, None] = {}
    for row in samples:
        for key in row.keys():
            if key not in seen:
                seen[key] = None
    return list(seen.keys())


def _make_iter(file_source, encoding: str) -> Iterable[Any]:
    fmt = (getattr(file_source, 'file_format', None) or 'json').lower()
    path = resolve_source_path(file_source)
    record_path = (getattr(file_source, 'record_path', '') or '').strip().strip('/').replace('/', '.')
    if fmt == 'jsonl':
        return _iter_jsonl(path, encoding)
    return _iter_json(path, encoding, record_path)


def iter_records(
    file_source,
    *,
    chunk_size: int = 1000,
    encoding: str = 'utf-8',
) -> Tuple[List[str], Iterable[List[Dict[str, str]]], Dict[str, int]]:
    if chunk_size <= 0:
        chunk_size = 1000
    strategy = (getattr(file_source, 'nested_strategy', None) or 'flatten').lower()
    separator = (getattr(file_source, 'flatten_separator', '.') or '.')

    stats: Dict[str, int] = {
        'rows_read': 0,
        'rows_padded': 0,
        'rows_truncated': 0,
        'single_column_warning': 0,
    }

    sample_rows: List[Dict[str, str]] = []
    try:
        for idx, item in enumerate(_make_iter(file_source, encoding)):
            sample_rows.append(_record_to_dict(item, strategy, separator))
            if idx + 1 >= HEADER_SAMPLE_SIZE:
                break
    except UnicodeDecodeError as exc:
        raise FlatFileReadError(
            f"Failed to decode JSON file with encoding {encoding}: {exc}"
        ) from exc

    headers = normalize_headers(_collect_headers(sample_rows)) or ['value']
    if len(headers) == 1:
        stats['single_column_warning'] = 1

    def _row_to_table(row: Dict[str, str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        missing = False
        extra = False
        for header in headers:
            if header in row:
                value = row[header]
                out[header] = '' if value is None else str(value)
            else:
                out[header] = ''
                missing = True
        for key in row.keys():
            if key not in headers:
                extra = True
                break
        if missing:
            stats['rows_padded'] += 1
        if extra:
            stats['rows_truncated'] += 1
        stats['rows_read'] += 1
        return out

    def _iterator():
        chunk: List[Dict[str, str]] = []
        for item in _make_iter(file_source, encoding):
            row = _record_to_dict(item, strategy, separator)
            chunk.append(_row_to_table(row))
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    return headers, _iterator(), stats
