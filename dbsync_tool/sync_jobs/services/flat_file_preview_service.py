"""Flat-file preview service for sync wizard Step 2."""
import csv
import os
import re

from django.core.exceptions import ValidationError

from connections.file_source_paths import resolve_safe_source_path

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
    resolved_path = resolve_safe_source_path(file_source_connection.relative_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise FileNotFoundError(str(resolved_path))

    headers = []
    rows = []
    sampled_rows = 0

    with resolved_path.open("r", encoding=file_source_connection.encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=file_source_connection.delimiter or ",")
        if file_source_connection.has_header:
            headers = next(reader, [])

        for row in reader:
            sampled_rows += 1
            if sampled_rows > PREVIEW_ROW_LIMIT:
                break
            rows.append([_truncate(cell) for cell in row[:PREVIEW_COLUMN_LIMIT]])

    if not headers:
        max_cols = max((len(r) for r in rows), default=0)
        headers = [f"column_{idx + 1}" for idx in range(min(max_cols, PREVIEW_COLUMN_LIMIT))]
    headers = [str(h).strip() if str(h).strip() else f"column_{idx + 1}" for idx, h in enumerate(headers[:PREVIEW_COLUMN_LIMIT])]
    if not headers:
        raise ValidationError("File appears empty or unreadable for preview.")

    return {
        "message": f"Preview loaded for {sampled_rows if sampled_rows <= PREVIEW_ROW_LIMIT else PREVIEW_ROW_LIMIT} row(s).",
        "columns": headers,
        "rows": rows,
        "file_stats": {
            "size_bytes": resolved_path.stat().st_size,
            "sample_rows": len(rows),
            "has_header": bool(file_source_connection.has_header),
            "delimiter": file_source_connection.delimiter,
            "encoding": file_source_connection.encoding,
            "relative_path": file_source_connection.relative_path,
        },
        "default_table_name": _safe_table_name_from_path(file_source_connection.relative_path),
    }
