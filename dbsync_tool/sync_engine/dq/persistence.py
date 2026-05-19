"""Persist DQ packs to ``ReconciliationReport`` + mirror into ``SyncVerificationReport``.

Failures are logged and swallowed so DQ never breaks sync execution (Day 5).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from sync_jobs.models import (
    ReconciliationReport,
    SyncDeadLetterRow,
    SyncVerificationReport,
)

if TYPE_CHECKING:
    from .pack import DQPack

logger = logging.getLogger(__name__)

# Cap how many dead-letter rows we mirror into ``snapshots_json``.  The full
# payload still lives in ``SyncDeadLetterRow`` and is the source of truth.
_SNAPSHOT_ROW_LIMIT = 50
_SNAPSHOT_SCHEMA_VERSION = 1


def _build_snapshots(
    *,
    execution,
    schema: str,
    table: str,
    limit: int = _SNAPSHOT_ROW_LIMIT,
) -> Dict[str, Any]:
    """Mirror up to ``limit`` dead-letter rows for this table into a compact dict.

    The block is intentionally lightweight - it carries the markers an
    operator needs to triage drift (PK text, row hash, error code, batch)
    while leaving the heavy ``raw_row_json`` payload in ``SyncDeadLetterRow``.

    Failures are caught by the caller's outer try/except; this helper only
    handles the empty-queryset case explicitly.
    """
    qs = (
        SyncDeadLetterRow.objects.filter(
            execution=execution,
            schema_name=schema,
            table_name=table,
        )
        .only(
            "source_pk_text",
            "source_row_hash",
            "error_code",
            "error_message",
            "batch_id",
            "created_at",
        )
        .order_by("created_at")[:limit]
    )
    rows: List[Dict[str, Any]] = []
    for dl in qs:
        rows.append({
            "source_pk_text": dl.source_pk_text,
            "source_row_hash": dl.source_row_hash,
            "error_code": dl.error_code,
            "error_message": (dl.error_message or "")[:512],
            "batch_id": dl.batch_id,
            "created_at": dl.created_at.isoformat() if dl.created_at else None,
        })
    return {
        "schema_version": _SNAPSHOT_SCHEMA_VERSION,
        "captured_at": timezone.now().isoformat(),
        "limit": int(limit),
        "row_count": len(rows),
        "rows": rows,
    }


def persist_dq_packs(
    *,
    execution,
    job,
    job_table,
    source_schema: str,
    source_table: str,
    pre_pack: Optional["DQPack"] = None,
    post_pack: Optional["DQPack"] = None,
    parity_result=None,
) -> Optional[ReconciliationReport]:
    """Upsert per-table reconciliation row and mirror structured metrics to SVR."""
    try:
        with transaction.atomic():
            defaults: Dict[str, Any] = {"job": job}
            if pre_pack is not None:
                defaults["dq_pre_json"] = pre_pack.metrics
                defaults["decision"] = pre_pack.decision
                defaults["confidence"] = float(pre_pack.confidence)
            if post_pack is not None:
                defaults["dq_post_json"] = post_pack.metrics
                defaults["decision"] = post_pack.decision
                defaults["confidence"] = float(post_pack.confidence)
                tgt = post_pack.metrics.get("target") if isinstance(post_pack.metrics, dict) else {}
                parity = post_pack.metrics.get("parity") if isinstance(post_pack.metrics, dict) else {}
                drift = (
                    post_pack.metrics.get("distribution_drift")
                    if isinstance(post_pack.metrics, dict)
                    else {}
                )
                if isinstance(tgt, dict):
                    defaults["target_metrics_json"] = tgt
                if isinstance(parity, dict):
                    defaults["source_metrics_json"] = parity
                if isinstance(drift, dict):
                    defaults["drift_json"] = drift

                # Day-7: when the post-pack is non-OK, mirror up to 50
                # dead-letter rows already on disk into ``snapshots_json``
                # so drift triage works directly from the per-table report.
                # Failures are swallowed by the outer try/except so DQ
                # persistence never breaks sync execution.
                if (post_pack.decision or "").lower() != "ok":
                    try:
                        defaults["snapshots_json"] = _build_snapshots(
                            execution=execution,
                            schema=source_schema,
                            table=source_table,
                        )
                    except Exception:
                        logger.exception(
                            "persist_dq_packs: snapshots backfill failed for "
                            "execution=%s table=%s.%s",
                            getattr(execution, "pk", execution),
                            source_schema,
                            source_table,
                        )

            obj, _created = ReconciliationReport.objects.update_or_create(
                execution=execution,
                schema_name=source_schema,
                table_name=source_table,
                defaults=defaults,
            )

            pre_metrics: Dict[str, Any] = {}
            post_metrics: Dict[str, Any] = {}
            if pre_pack is not None:
                pre_metrics = pre_pack.metrics if isinstance(pre_pack.metrics, dict) else {}
            if post_pack is not None:
                post_metrics = post_pack.metrics if isinstance(post_pack.metrics, dict) else {}

            metrics_json: Dict[str, Any] = {
                "dq_pre": pre_metrics,
                "dq_post": post_metrics,
            }
            if post_pack is not None:
                metrics_json["decision"] = post_pack.decision
                metrics_json["confidence"] = float(post_pack.confidence)
            elif pre_pack is not None:
                metrics_json["decision"] = pre_pack.decision
                metrics_json["confidence"] = float(pre_pack.confidence)

            SyncVerificationReport.objects.filter(
                execution=execution,
                schema_name=source_schema,
                table_name=source_table,
            ).update(metrics_json=metrics_json)

            return obj
    except Exception:
        logger.exception(
            "persist_dq_packs failed for execution=%s table=%s.%s",
            getattr(execution, "pk", execution),
            source_schema,
            source_table,
        )
        return None
