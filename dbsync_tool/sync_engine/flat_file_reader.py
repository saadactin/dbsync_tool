"""
Chunked CSV reader for flat-file sync execution.
"""
import csv
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def read_csv_in_chunks(
    file_path: Path,
    delimiter: str = ",",
    encoding: str = "utf-8",
    has_header: bool = True,
    chunk_size: int = 1000,
) -> Tuple[List[str], Iterable[List[Dict[str, str]]], Dict[str, int]]:
    """
    Return headers and an iterator yielding row chunks as dicts.
    """
    if chunk_size <= 0:
        chunk_size = 1000

    stats: Dict[str, int] = {
        "rows_read": 0,
        "rows_padded": 0,
        "rows_truncated": 0,
        "single_column_warning": 0,
    }

    def _iterator():
        with file_path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter or ",")
            headers: List[str] = []
            if has_header:
                headers = next(reader, [])
            first_rows = []
            for row in reader:
                first_rows.append(row)
                if len(first_rows) >= 1:
                    break
            if not has_header:
                max_cols = len(first_rows[0]) if first_rows else 0
                headers.extend([f"column_{idx + 1}" for idx in range(max_cols)])
            if not headers:
                return
            if len(headers) == 1:
                stats["single_column_warning"] = 1

            def _row_to_dict(raw: List[str]) -> Dict[str, str]:
                row_vals = list(raw)
                if len(row_vals) < len(headers):
                    row_vals.extend([""] * (len(headers) - len(row_vals)))
                    stats["rows_padded"] += 1
                if len(row_vals) > len(headers):
                    row_vals = row_vals[: len(headers)]
                    stats["rows_truncated"] += 1
                stats["rows_read"] += 1
                return {headers[idx]: ("" if row_vals[idx] is None else str(row_vals[idx])) for idx in range(len(headers))}

            chunk: List[Dict[str, str]] = []
            for raw in first_rows:
                chunk.append(_row_to_dict(raw))
            for raw in reader:
                chunk.append(_row_to_dict(raw))
                if len(chunk) >= chunk_size:
                    yield chunk
                    chunk = []
            if chunk:
                yield chunk

    # Warm-up read to get deterministic headers and validate readability.
    with file_path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter or ",")
        headers: List[str] = []
        if has_header:
            headers = next(reader, [])
        else:
            first = next(reader, [])
            headers = [f"column_{idx + 1}" for idx in range(len(first))]
        headers = [str(h).strip() if str(h).strip() else f"column_{i + 1}" for i, h in enumerate(headers)]
    if len(headers) == 1:
        stats["single_column_warning"] = 1
    return headers, _iterator(), stats

