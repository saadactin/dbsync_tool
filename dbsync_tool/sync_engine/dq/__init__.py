"""Data-quality pack computation (Day 5).

Structured pre-run + post-run metrics persisted on ``ReconciliationReport``
and mirrored into ``SyncVerificationReport.metrics_json``.
"""

from .pack import (
    DQPack,
    compute_post_pack,
    compute_pre_pack,
    discover_numeric_or_date_columns,
    numeric_columns_from_column_infos,
)
from .persistence import persist_dq_packs

__all__ = [
    "DQPack",
    "compute_pre_pack",
    "compute_post_pack",
    "discover_numeric_or_date_columns",
    "numeric_columns_from_column_infos",
    "persist_dq_packs",
]
