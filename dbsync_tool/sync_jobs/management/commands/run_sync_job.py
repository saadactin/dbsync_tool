import logging

from django.core.management.base import BaseCommand, CommandError

from sync_engine.executor import SyncExecutor
from sync_jobs.models import SyncJob


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run a sync job in a standalone process."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True, help="Sync job UUID")
        parser.add_argument(
            "--initiated-by-user-id",
            required=False,
            type=int,
            help="Optional user id who initiated this run",
        )

    def handle(self, *args, **options):
        job_id = options["job_id"]
        initiated_by_user_id = options.get("initiated_by_user_id")
        try:
            job = SyncJob.objects.get(id=job_id)
        except SyncJob.DoesNotExist as exc:
            raise CommandError(f"Sync job not found: {job_id}") from exc

        logger.info(
            "Starting standalone sync process for job=%s initiated_by_user_id=%s",
            job_id,
            initiated_by_user_id,
        )
        executor = SyncExecutor(job)
        executor.execute()
        logger.info("Standalone sync process completed for job=%s", job_id)
