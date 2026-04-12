"""
MongoDB Change Streams runner (MongoDB -> SQL incremental sync).

Day 4 scope: consume change stream events with resume tokens and provide a bounded
iteration mode for unit tests.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional

from sync_jobs.models import SyncJob, SyncJobTable, MongoCdcCheckpoint

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MongoCdcEvent:
    op: str
    db: str
    coll: str
    document_id: Optional[str]
    full_document: Optional[Dict[str, Any]]
    cluster_time: Any
    resume_token: Any


def _stringify_document_id(document_key: Any) -> Optional[str]:
    if not isinstance(document_key, dict):
        return None
    _id = document_key.get("_id")
    if _id is None:
        return None
    return str(_id)


def _normalize_change(change: Dict[str, Any]) -> MongoCdcEvent:
    op = (change.get("operationType") or "").strip().lower()
    ns = change.get("ns") or {}
    db = ns.get("db")
    coll = ns.get("coll")
    document_id = _stringify_document_id(change.get("documentKey"))
    full_document = change.get("fullDocument")
    cluster_time = change.get("clusterTime")
    resume_token = change.get("_id")  # pymongo uses _id as resume token

    return MongoCdcEvent(
        op=op,
        db=db,
        coll=coll,
        document_id=document_id,
        full_document=full_document,
        cluster_time=cluster_time,
        resume_token=resume_token,
    )


class MongoCdcRunner:
    def __init__(self, job: SyncJob, source_connector):
        self.job = job
        self.source_connector = source_connector

    def _get_checkpoint(self, schema: str, table: str) -> MongoCdcCheckpoint:
        ckpt, _ = MongoCdcCheckpoint.objects.get_or_create(
            job=self.job, schema_name=schema, table_name=table
        )
        return ckpt

    def iter_events_for_table(
        self,
        schema: str,
        table: str,
        max_events: Optional[int] = None,
        max_seconds: Optional[float] = None,
    ) -> Iterator[MongoCdcEvent]:
        """
        Iterate change stream events for a single collection.

        Bounded run (max_events/max_seconds) is intended for tests to avoid hanging.
        """
        started = time.time()
        count = 0

        ckpt = self._get_checkpoint(schema, table)
        resume_token = None
        if ckpt.resume_token:
            try:
                resume_token = json.loads(ckpt.resume_token)
            except Exception:
                # If stored as non-JSON text, pass through as-is.
                resume_token = ckpt.resume_token

        stream = self.source_connector.watch_collection(
            schema=schema,
            table=table,
            resume_token=resume_token,
            full_document="updateLookup",
        )

        for change in stream:
            evt = _normalize_change(change)
            yield evt

            count += 1
            if max_events is not None and count >= max_events:
                return
            if max_seconds is not None and (time.time() - started) >= max_seconds:
                return

    def iter_events(
        self,
        tables: Optional[Iterable[SyncJobTable]] = None,
        max_events: Optional[int] = None,
        max_seconds: Optional[float] = None,
    ) -> Iterator[MongoCdcEvent]:
        """
        Iterate events across job tables.

        Day 4: simple sequential iteration per table.
        """
        if tables is None:
            tables = self.job.tables.filter(is_enabled=True)

        emitted = 0
        started = time.time()

        for jt in tables:
            for evt in self.iter_events_for_table(
                schema=jt.schema_name,
                table=jt.table_name,
                max_events=None if max_events is None else max_events - emitted,
                max_seconds=None if max_seconds is None else max_seconds - (time.time() - started),
            ):
                yield evt
                emitted += 1
                if max_events is not None and emitted >= max_events:
                    return
                if max_seconds is not None and (time.time() - started) >= max_seconds:
                    return

