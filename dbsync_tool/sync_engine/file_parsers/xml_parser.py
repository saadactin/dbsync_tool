"""XML parser with streaming iterparse and XXE/billion-laughs guards."""
from __future__ import annotations

import json
from typing import Dict, Iterable, List, Tuple

from sync_engine.exceptions import FlatFileReadError

from .common import normalize_headers, resolve_source_path


HEADER_SAMPLE_SIZE = 64
DOCTYPE_SCAN_BYTES = 8192


def _import_lxml():
    try:
        from lxml import etree  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise FlatFileReadError(
            "lxml is required for XML sources. Install requirements.txt."
        ) from exc
    return etree


def _local_tag(tag: str) -> str:
    if tag and isinstance(tag, str) and tag.startswith('{'):
        return tag.split('}', 1)[1]
    return tag


def _normalize_record_path(raw: str) -> List[str]:
    cleaned = (raw or '').strip()
    if cleaned.startswith('//'):
        cleaned = cleaned[2:]
    elif cleaned.startswith('/'):
        cleaned = cleaned[1:]
    parts = [p for p in cleaned.split('/') if p and p != '*']
    return parts


def _flatten_element(element, separator: str, prefix: str = '') -> Dict[str, str]:
    out: Dict[str, str] = {}
    for attr_name, attr_value in element.attrib.items():
        local = _local_tag(attr_name)
        key = f'{prefix}{separator}@{local}' if prefix else f'@{local}'
        out[key] = '' if attr_value is None else str(attr_value)
    text = (element.text or '').strip()
    children = list(element)
    if children:
        for child in children:
            child_local = _local_tag(child.tag)
            child_key = f'{prefix}{separator}{child_local}' if prefix else child_local
            child_data = _flatten_element(child, separator, child_key)
            for k, v in child_data.items():
                if k in out:
                    if isinstance(out[k], list):
                        out[k].append(v)
                    else:
                        out[k] = [out[k], v]
                else:
                    out[k] = v
        if text:
            out[(prefix or '#text')] = text
    else:
        if text:
            out[prefix or _local_tag(element.tag)] = text
        elif prefix:
            out.setdefault(prefix, '')
    serialised: Dict[str, str] = {}
    for k, v in out.items():
        if isinstance(v, list):
            serialised[k] = json.dumps(v, ensure_ascii=False, default=str)
        else:
            serialised[k] = '' if v is None else str(v)
    return serialised


def _blob_element(element) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for attr_name, attr_value in element.attrib.items():
        out[f'@{_local_tag(attr_name)}'] = '' if attr_value is None else str(attr_value)
    children = list(element)
    if children:
        children_payload = []
        for child in children:
            child_data = _blob_element(child)
            child_local = _local_tag(child.tag)
            children_payload.append({child_local: child_data})
        out['_children'] = json.dumps(children_payload, ensure_ascii=False, default=str)
    text = (element.text or '').strip()
    if text:
        out['#text'] = text
    return out


def _element_to_record(element, strategy: str, separator: str) -> Dict[str, str]:
    if strategy == 'json_blob':
        return _blob_element(element)
    return _flatten_element(element, separator)


def _iter_elements(path, record_parts: List[str]):
    etree = _import_lxml()
    target = record_parts[-1] if record_parts else None
    with path.open('rb') as probe:
        prefix = probe.read(DOCTYPE_SCAN_BYTES).upper()
    if b'<!DOCTYPE' in prefix:
        raise FlatFileReadError("XML DOCTYPE is not allowed for security reasons.")
    with path.open('rb') as handle:
        try:
            context = etree.iterparse(
                handle,
                events=('end',),
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                huge_tree=False,
            )
        except etree.XMLSyntaxError as exc:
            raise FlatFileReadError(f"XML parse error: {exc}") from exc
        try:
            stack: List[str] = []
            for event, elem in context:
                local = _local_tag(elem.tag)
                if target is None or local == target:
                    if not record_parts or _path_matches(elem, record_parts):
                        yield elem
                        elem.clear()
                        # Free preceding siblings to bound memory.
                        while elem.getprevious() is not None:
                            del elem.getparent()[0]
        except etree.XMLSyntaxError as exc:
            raise FlatFileReadError(f"XML parse error: {exc}") from exc


def _path_matches(elem, record_parts: List[str]) -> bool:
    if not record_parts:
        return True
    cur = elem
    for part in reversed(record_parts):
        if cur is None:
            return False
        if _local_tag(cur.tag) != part:
            return False
        cur = cur.getparent()
    return True


def _collect_headers(samples) -> List[str]:
    seen: Dict[str, None] = {}
    for row in samples:
        for key in row.keys():
            if key not in seen:
                seen[key] = None
    return list(seen.keys())


def iter_records(
    file_source,
    *,
    chunk_size: int = 1000,
    encoding: str = 'utf-8',
) -> Tuple[List[str], Iterable[List[Dict[str, str]]], Dict[str, int]]:
    if chunk_size <= 0:
        chunk_size = 1000
    path = resolve_source_path(file_source)
    record_path = (getattr(file_source, 'record_path', '') or '').strip()
    if not record_path:
        raise FlatFileReadError("XML sources require a record_path (e.g. /root/items/item).")
    record_parts = _normalize_record_path(record_path)
    strategy = (getattr(file_source, 'nested_strategy', None) or 'flatten').lower()
    separator = (getattr(file_source, 'flatten_separator', '.') or '.')

    stats: Dict[str, int] = {
        'rows_read': 0,
        'rows_padded': 0,
        'rows_truncated': 0,
        'single_column_warning': 0,
    }

    # Initial pass to collect headers from a sample.
    sample_rows: List[Dict[str, str]] = []
    for idx, elem in enumerate(_iter_elements(path, record_parts)):
        sample_rows.append(_element_to_record(elem, strategy, separator))
        if idx + 1 >= HEADER_SAMPLE_SIZE:
            break

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
        for elem in _iter_elements(path, record_parts):
            row = _element_to_record(elem, strategy, separator)
            chunk.append(_row_to_table(row))
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    return headers, _iterator(), stats
