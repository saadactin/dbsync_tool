"""
Job execution functions (formerly Celery tasks)
Now executed directly via threading or scheduler service
"""
from django.utils import timezone
from sync_jobs.models import SyncExecution
from scheduler.utils import execute_sync_job_direct
import logging

logger = logging.getLogger(__name__)


def cleanup_old_executions():
    """
    Cleanup old execution records (older than 90 days)
    Can be called periodically by scheduler
    """
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=90)
    
    deleted_count = SyncExecution.objects.filter(
        started_at__lt=cutoff_date,
        status__in=['completed', 'failed']
    ).delete()[0]
    
    logger.info(f"Cleaned up {deleted_count} old execution records")
    return deleted_count


# Note: execute_sync_job is now execute_sync_job_direct in scheduler.utils
# trigger_scheduled_jobs_task is now handled by APScheduler in scheduler.service

