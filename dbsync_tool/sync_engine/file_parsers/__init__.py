"""Unified parser registry for flat-file sources.

Each parser implements ``iter_records(file_source, *, chunk_size, encoding) ->
(headers, chunks_iterator, stats)`` so the preview service and the sync
executor share a single contract.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Tuple

from sync_engine.exceptions import FlatFileReadError

from . import csv_parser, json_parser, xlsx_parser, xml_parser
from .common import normalize_headers, resolve_source_path


ParserFn = Callable[..., Tuple[List[str], Iterable[List[Dict[str, str]]], Dict[str, int]]]


_PARSERS: Dict[str, ParserFn] = {
    'csv': csv_parser.iter_records,
    'tsv': csv_parser.iter_records,
    'txt': csv_parser.iter_records,
    'json': json_parser.iter_records,
    'jsonl': json_parser.iter_records,
    'xml': xml_parser.iter_records,
    'xlsx': xlsx_parser.iter_records,
}


def iter_records(
    file_source,
    *,
    chunk_size: int = 1000,
    encoding: str | None = None,
) -> Tuple[List[str], Iterable[List[Dict[str, str]]], Dict[str, int]]:
    """Dispatch to the parser matching ``file_source.file_format``.

    The ``file_source`` argument is expected to expose attributes from
    :class:`connections.models.FileSourceConnection` (``relative_path``,
    ``file_format``, ``delimiter``, ``encoding``, ``has_header``,
    ``record_path``, ``sheet_name``, ``nested_strategy``,
    ``flatten_separator``).
    """
    fmt = (getattr(file_source, 'file_format', None) or 'csv').lower()
    parser = _PARSERS.get(fmt)
    if parser is None:
        raise FlatFileReadError(f"Unsupported file format: {fmt}")
    enc = encoding or getattr(file_source, 'encoding', None) or 'utf-8'
    return parser(file_source, chunk_size=chunk_size, encoding=enc)

__all__ = [
    'iter_records',
    'normalize_headers',
    'resolve_source_path',
    'FlatFileReadError',
]
