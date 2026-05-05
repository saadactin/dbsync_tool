"""Flat-file preview service for sync wizard Step 2."""
import os
import re

from django.core.exceptions import ValidationError

from sync_engine.file_parsers import iter_records, resolve_source_path

PREVIEW_ROW_LIMIT = 20
PREVIEW_COLUMN_LIMIT = 100
MAX_CELL_LEN = 512


def _safe_table_name_from_path(relative_path: str) -> str:
    stem = os.path.splitext(os.path.basename(relative_path or ""))[0] or "flat_file_source"
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", stem).strip("_").lower()
    if not cleaned:
        cleaned = "flat_file_source"
    return cleaned[:63]


def _truncate(value) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= MAX_CELL_LEN else text[:MAX_CELL_LEN]


def build_flat_file_preview(file_source_connection):
    """Return bounded preview payload for a FileSourceConnection."""
    resolved_path = resolve_source_path(file_source_connection)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise FileNotFoundError(str(resolved_path))

    headers = []
    rows = []
    sampled_rows = 0

    headers, chunks, read_stats = iter_records(
        file_source_connection,
        chunk_size=PREVIEW_ROW_LIMIT,
        encoding=file_source_connection.encoding,
    )
    headers = [
        str(h).strip() if str(h).strip() else f"column_{idx + 1}"
        for idx, h in enumerate(headers[:PREVIEW_COLUMN_LIMIT])
    ]
    if not headers:
        raise ValidationError("File appears empty or unreadable for preview.")

    for chunk in chunks:
        for row_map in chunk:
            sampled_rows += 1
            if sampled_rows > PREVIEW_ROW_LIMIT:
                break
            rows.append([_truncate(row_map.get(h, "")) for h in headers])
        if sampled_rows >= PREVIEW_ROW_LIMIT:
            break

    return {
        "message": f"Preview loaded for {len(rows)} row(s).",
        "columns": headers,
        "rows": rows,
        "file_stats": {
            "size_bytes": resolved_path.stat().st_size,
            "sample_rows": len(rows),
            "file_format": getattr(file_source_connection, "file_format", "csv"),
            "has_header": bool(file_source_connection.has_header),
            "delimiter": file_source_connection.delimiter,
            "encoding": file_source_connection.encoding,
            "record_path": getattr(file_source_connection, "record_path", ""),
            "sheet_name": getattr(file_source_connection, "sheet_name", ""),
            "nested_strategy": getattr(file_source_connection, "nested_strategy", "flatten"),
            "warnings": {
                "single_column_warning": bool(read_stats.get("single_column_warning")),
                "rows_padded": int(read_stats.get("rows_padded", 0)),
                "rows_truncated": int(read_stats.get("rows_truncated", 0)),
            },
            "relative_path": file_source_connection.relative_path,
        },
        "default_table_name": _safe_table_name_from_path(file_source_connection.relative_path),
    }
