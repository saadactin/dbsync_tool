from __future__ import annotations

from django.core.management import BaseCommand, call_command, CommandError


class Command(BaseCommand):
    help = (
        "Day-7 reliability smoke: run focused reliability/DQ tests and fail fast "
        "if any invariant is broken."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-tests",
            action="store_true",
            help="Only print smoke checklist; skip running test labels.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting Day-7 reliability smoke run..."))

        checklist = [
            "rerun-noop semantics (idempotent commits)",
            "mid-run resume behavior",
            "dead-letter under threshold",
            "reconciliation report downloadability (json/csv)",
            "single drift alert pathway",
            "SLO streak breach detector + alert hook",
            "embedded dashboard reliability insights render",
            "snapshots_json backfill for non-ok post-pack",
        ]
        for item in checklist:
            self.stdout.write(f" - {item}")

        if options.get("skip_tests"):
            self.stdout.write(self.style.WARNING("Skipped test execution (--skip-tests)."))
            return

        labels = [
            "sync_engine.tests.test_retry_policy",
            "sync_engine.tests.test_idempotent_batch_commit",
            "sync_engine.tests.test_dead_letter",
            "sync_engine.tests.test_dq_pack",
            "sync_jobs.tests.test_reconciliation_persistence",
            "sync_jobs.tests.test_reconciliation_endpoint",
            "sync_jobs.tests.test_drift_alert_email",
            "sync_jobs.tests.test_ops_metrics_service",
            "sync_jobs.tests.test_slo_breach_detector",
            "sync_jobs.tests.test_ops_health_view",
            "sync_jobs.tests.test_snapshots_persistence",
        ]

        failed = []
        for label in labels:
            self.stdout.write(self.style.NOTICE(f"Running: {label}"))
            try:
                call_command("test", label, verbosity=1)
            except Exception as exc:
                failed.append((label, str(exc)))

        if failed:
            self.stderr.write(self.style.ERROR("Reliability smoke failed:"))
            for label, err in failed:
                self.stderr.write(f" - {label}: {err}")
            raise CommandError("reliability_smoke detected failures")

        self.stdout.write(self.style.SUCCESS("Reliability smoke passed."))
