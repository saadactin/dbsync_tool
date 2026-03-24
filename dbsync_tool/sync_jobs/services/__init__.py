"""
Service helpers for sync job orchestration.

Note: This project historically exposed `DashboardService` from
`dbsync_tool/sync_jobs/services.py`.

When a `dbsync_tool/sync_jobs/services/` package directory exists, Python
imports resolve to this package first. To keep backward compatibility (and
avoid the `ImportError: cannot import name 'DashboardService' from
'sync_jobs.services'`), we dynamically re-export the legacy symbols from the
original `services.py` module.
"""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _export_legacy_dashboard_service() -> None:
    legacy_pkg = __package__.rsplit(".", 1)[0]  # e.g. "sync_jobs"
    legacy_services_path = Path(__file__).resolve().parent.parent / "services.py"

    spec = spec_from_file_location(f"{legacy_pkg}._legacy_services", legacy_services_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load legacy services module at {legacy_services_path}")

    module = module_from_spec(spec)
    module.__package__ = legacy_pkg  # ensures `from .models import ...` works
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # Re-export expected symbols for older imports.
    globals()["DashboardService"] = getattr(module, "DashboardService")
    # If other legacy symbols are required in the future, add them here.


_export_legacy_dashboard_service()

__all__ = ["DashboardService"]

