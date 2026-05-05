"""Management command: verify_sync --job <id>

Re-runs source vs target parity (counts + optional hash) for every enabled
table on a SyncJob and prints a report. Optionally writes SyncVerificationReport
rows. Designed for SQL Server -> Postgres reconciliation, but works on any
source/target combination that exposes count_rows().
"""
import logging

from django.core.management.base import BaseCommand, CommandError

from connections.connectors.factory import get_connector
from sync_engine.full_sync import get_target_table_name
from sync_engine.verification import verify_table_parity
from sync_jobs.models import SyncJob


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Verify source vs target parity for every table in a sync job."

    def add_arguments(self, parser):
        parser.add_argument("--job", required=True, help="SyncJob UUID")
        parser.add_argument(
            "--persist",
            action="store_true",
            default=False,
            help="Persist a SyncVerificationReport row per table (default: report only).",
        )
        parser.add_argument(
            "--mode",
            default="auto",
            choices=("auto", "full", "incremental"),
            help="Verification mode: auto picks job.sync_type, otherwise the explicit value.",
        )

    def handle(self, *args, **options):
        job_id = options["job"]
        persist = options["persist"]
        mode_arg = options["mode"]

        try:
            job = SyncJob.objects.get(id=job_id)
        except SyncJob.DoesNotExist as exc:
            raise CommandError(f"Sync job not found: {job_id}") from exc

        if not job.source_connection or not job.target_connection:
            raise CommandError(
                f"Job {job_id} requires both source_connection and target_connection (DB jobs only)."
            )

        sync_mode = mode_arg if mode_arg != "auto" else (job.sync_type or "full")

        source_connector = get_connector(job.source_connection)
        target_connector = get_connector(job.target_connection)
        source_connector.connect()
        target_connector.connect()

        target_db_type = target_connector.__class__.__name__.lower()
        if "postgres" in target_db_type:
            target_schema_default = "public"
        elif "sqlserver" in target_db_type:
            target_schema_default = "dbo"
        elif "clickhouse" in target_db_type:
            target_schema_default = getattr(target_connector, "database_name", None) or "default"
        elif "mysql" in target_db_type:
            target_schema_default = getattr(target_connector, "database_name", None)
        elif "oracle" in target_db_type:
            target_schema_default = (
                (getattr(target_connector, "username", None) or "").upper() or None
            )
        else:
            target_schema_default = None

        try:
            tables = list(job.tables.filter(is_enabled=True))
            if not tables:
                self.stdout.write(self.style.WARNING("No enabled tables for this job."))
                return

            self.stdout.write(self.style.NOTICE(
                f"Verifying job={job_id} mode={sync_mode} tables={len(tables)} persist={persist}"
            ))
            ok = 0
            drift = 0
            warning = 0
            for jt in tables:
                target_table = get_target_table_name(job, jt.table_name)
                target_schema = target_schema_default or jt.schema_name
                report_kwargs = dict(
                    job=job if persist else SyncJob(id=job.id, name=job.name),
                    execution=None,
                    source_connector=source_connector,
                    target_connector=target_connector,
                    source_schema=jt.schema_name,
                    source_table=jt.table_name,
                    target_schema=target_schema,
                    target_table=target_table,
                    sync_mode=sync_mode,
                    no_delete_propagation=getattr(job, "no_delete_propagation", True),
                )
                if not persist:
                    src_count = self._safe_count(source_connector, jt.schema_name, jt.table_name)
                    tgt_count = self._safe_count(target_connector, target_schema, target_table)
                    decision = self._decide(
                        sync_mode, src_count, tgt_count,
                        no_deletes=getattr(job, "no_delete_propagation", True),
                    )
                    self.stdout.write(
                        f"  {jt.schema_name}.{jt.table_name} -> "
                        f"src={src_count} tgt={tgt_count} decision={decision}"
                    )
                    if decision == "ok":
                        ok += 1
                    elif decision == "warning":
                        warning += 1
                    else:
                        drift += 1
                    continue

                result = verify_table_parity(**report_kwargs)
                self.stdout.write(
                    f"  {jt.schema_name}.{jt.table_name} -> "
                    f"src={result.source_count} tgt={result.target_count} decision={result.decision}"
                )
                if result.decision == "ok":
                    ok += 1
                elif result.decision == "warning":
                    warning += 1
                else:
                    drift += 1

            self.stdout.write(self.style.SUCCESS(
                f"Verification complete: ok={ok} drift={drift} warning={warning}"
            ))
        finally:
            try:
                source_connector.close()
            except Exception:
                pass
            try:
                target_connector.close()
            except Exception:
                pass

    @staticmethod
    def _safe_count(connector, schema, table):
        fn = getattr(connector, "count_rows", None)
        if not callable(fn):
            return None
        try:
            return int(fn(schema, table, None))
        except Exception:
            return None

    @staticmethod
    def _decide(mode, src, tgt, *, no_deletes):
        if src is None or tgt is None:
            return "warning"
        if mode == "full":
            return "ok" if src == tgt else "repair_full"
        if no_deletes:
            return "ok" if tgt >= src else "repair_full"
        return "ok" if src == tgt else "repair_full"
