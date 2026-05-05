"""File-format detection, validation and size limits for FileSourceConnection.

This module is intentionally dependency-light: it only inspects extensions and
small content prefixes, so it can be used in forms, views and the sync engine
without importing parser libraries.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import IO, Iterable, Optional, Tuple

from django.conf import settings
from django.core.exceptions import ValidationError


SUPPORTED_FORMATS: Tuple[str, ...] = (
    'csv', 'tsv', 'txt', 'json', 'jsonl', 'xml', 'xlsx',
)
DELIMITED_FORMATS = {'csv', 'tsv', 'txt'}

EXTENSION_TO_FORMAT = {
    '.csv': 'csv',
    '.tsv': 'tsv',
    '.txt': 'txt',
    '.json': 'json',
    '.jsonl': 'jsonl',
    '.ndjson': 'jsonl',
    '.xml': 'xml',
    '.xlsx': 'xlsx',
}

# Acceptable mime hints for upload validation; primary check is content sniffing.
ACCEPT_MIME = (
    '.csv,.tsv,.txt,.json,.jsonl,.ndjson,.xml,.xlsx,'
    'text/csv,text/tab-separated-values,text/plain,application/json,'
    'application/x-ndjson,application/xml,text/xml,'
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)

DEFAULT_MAX_BYTES_BY_FORMAT = {
    'csv': 1024 * 1024 * 1024,        # 1 GB
    'tsv': 1024 * 1024 * 1024,        # 1 GB
    'txt': 1024 * 1024 * 1024,        # 1 GB
    'json': 512 * 1024 * 1024,        # 512 MB
    'jsonl': 512 * 1024 * 1024,       # 512 MB
    'xml': 256 * 1024 * 1024,         # 256 MB
    'xlsx': 128 * 1024 * 1024,        # 128 MB
}


def _max_bytes_for(fmt: str) -> int:
    overrides = getattr(settings, 'FILE_FORMAT_MAX_BYTES', {}) or {}
    base = DEFAULT_MAX_BYTES_BY_FORMAT.get(fmt, DEFAULT_MAX_BYTES_BY_FORMAT['csv'])
    try:
        return int(overrides.get(fmt, base))
    except (TypeError, ValueError):
        return base


def extension_format(name: str) -> Optional[str]:
    """Return canonical format string for a filename extension or None."""
    ext = os.path.splitext((name or '').lower())[1]
    return EXTENSION_TO_FORMAT.get(ext)


def _read_prefix(source, num_bytes: int = 4096) -> bytes:
    """Read up to num_bytes bytes from the start of a file-like or path.

    Restores the original cursor for file-like inputs.
    """
    if hasattr(source, 'read'):
        try:
            pos = source.tell()
        except Exception:
            pos = None
        try:
            try:
                source.seek(0)
            except Exception:
                pass
            data = source.read(num_bytes)
            if isinstance(data, str):
                data = data.encode('utf-8', errors='replace')
            return data or b''
        finally:
            if pos is not None:
                try:
                    source.seek(pos)
                except Exception:
                    pass
    path = Path(source)
    with path.open('rb') as fh:
        return fh.read(num_bytes)


def detect_format(path_or_file, *, declared_name: Optional[str] = None) -> str:
    """Detect file format using extension hint plus a content sniff.

    Args:
        path_or_file: Path-like or file-like object opened in binary mode.
        declared_name: Original filename for upload-time detection (when
            ``path_or_file`` is a file-like with no name).
    Returns:
        One of SUPPORTED_FORMATS.
    """
    name = declared_name
    if name is None:
        name = getattr(path_or_file, 'name', None) or str(path_or_file)
    ext_fmt = extension_format(name)

    prefix = _read_prefix(path_or_file, 4096)
    sniff = prefix.lstrip()

    # XLSX is a zip starting with PK\x03\x04
    if prefix[:4] == b'PK\x03\x04':
        if b'xl/' in prefix or b'[Content_Types].xml' in prefix:
            return 'xlsx'
        # Generic zip; fall back to extension if known.
        if ext_fmt:
            return ext_fmt

    if sniff[:5].lower() == b'<?xml' or sniff.startswith(b'<') and b'</' in prefix:
        return 'xml'

    if sniff[:1] in (b'{', b'['):
        # Heuristic for JSONL: many lines each starting with '{'.
        lines = [ln for ln in prefix.splitlines() if ln.strip()]
        if len(lines) >= 2 and all(ln.lstrip().startswith(b'{') for ln in lines[:3]):
            return 'jsonl'
        return 'json'

    if ext_fmt:
        return ext_fmt

    return 'csv'


def validate_upload(uploaded_file, declared_format: Optional[str]) -> str:
    """Validate that an uploaded file is consistent with declared format.

    Returns the canonical format string (declared_format normalised). Raises
    ``ValidationError`` if extension/content do not match.
    """
    fmt = (declared_format or '').strip().lower()
    if fmt and fmt not in SUPPORTED_FORMATS:
        raise ValidationError({'file_format': f'Unsupported file format: {declared_format}.'})

    if uploaded_file is None:
        if not fmt:
            raise ValidationError({'file_format': 'File format is required.'})
        return fmt

    name = getattr(uploaded_file, 'name', '') or ''
    ext_fmt = extension_format(name)
    detected = None
    try:
        detected = detect_format(uploaded_file, declared_name=name)
    except Exception:
        detected = None

    chosen = fmt or ext_fmt or detected or 'csv'

    # Cross-check: if declared and detected disagree on a "structural" format
    # (xlsx/xml/json/jsonl), reject. Delimited formats are allowed to alias.
    structural = {'xlsx', 'xml', 'json', 'jsonl'}
    if detected and chosen != detected and chosen in structural and detected in structural:
        raise ValidationError(
            {'upload_file': (
                f"Uploaded file looks like '{detected}' but declared format is '{chosen}'."
            )}
        )

    size = getattr(uploaded_file, 'size', None)
    if size is None:
        try:
            size = os.fstat(uploaded_file.fileno()).st_size
        except Exception:
            size = None
    if size is not None and size > _max_bytes_for(chosen):
        max_mb = _max_bytes_for(chosen) / (1024 * 1024)
        raise ValidationError(
            {'upload_file': f'File exceeds maximum allowed size for {chosen} ({max_mb:.0f} MB).'}
        )

    return chosen


def default_extension_for(fmt: str) -> str:
    """Return canonical extension (with dot) for a format."""
    rev = {
        'csv': '.csv', 'tsv': '.tsv', 'txt': '.txt',
        'json': '.json', 'jsonl': '.jsonl', 'xml': '.xml', 'xlsx': '.xlsx',
    }
    return rev.get((fmt or '').lower(), '.csv')


def accepted_extensions(fmt: Optional[str] = None) -> Iterable[str]:
    """Return file-input ``accept`` value for the given format (or all)."""
    if fmt and fmt in EXTENSION_TO_FORMAT.values():
        return [default_extension_for(fmt)]
    return list(EXTENSION_TO_FORMAT.keys())
