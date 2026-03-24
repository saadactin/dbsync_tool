"""Helpers for secure server-side flat-file path resolution."""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError


def get_file_sync_root() -> Path:
    """Return configured FILE_SYNC_ROOT as an absolute canonical Path."""
    configured = getattr(settings, 'FILE_SYNC_ROOT', None)
    if not configured:
        raise ValidationError('FILE_SYNC_ROOT is not configured on the server.')

    root = Path(configured)
    try:
        return root.resolve(strict=False)
    except Exception as exc:
        raise ValidationError(f'Invalid FILE_SYNC_ROOT configuration: {exc}') from exc


def resolve_safe_source_path(relative_path: str) -> Path:
    """
    Resolve a relative source path under FILE_SYNC_ROOT.

    Raises ValidationError for invalid paths or traversal attempts.
    """
    value = (relative_path or '').strip()
    if not value:
        raise ValidationError('Relative path is required.')
    if '\x00' in value:
        raise ValidationError('Relative path contains invalid characters.')

    input_path = Path(value)
    if input_path.is_absolute() or value.startswith('\\\\') or value.startswith('//'):
        raise ValidationError('Path must be relative to FILE_SYNC_ROOT.')
    if any(part == '..' for part in input_path.parts):
        raise ValidationError('Relative path cannot contain parent-directory traversal (..).')

    root = get_file_sync_root()
    resolved = (root / input_path).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValidationError('Path escapes FILE_SYNC_ROOT and is not allowed.') from exc
    return resolved
