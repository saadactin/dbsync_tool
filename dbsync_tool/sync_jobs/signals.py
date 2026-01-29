"""
Signal handlers for sync_jobs app
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from sync_jobs.models import SyncExecution

logger = logging.getLogger(__name__)


@receiver(post_save, sender=SyncExecution)
def update_freshness_on_execution_complete(sender, instance, created, **kwargs):
    """
    Update freshness metric when execution completes successfully
    """
    # Only process if execution is completed
    if instance.status == 'completed' and instance.completed_at:
        try:
            from sync_jobs.services import FreshnessMapService
            
            # Get the job's tenant (via created_by or tenant field)
            job = instance.job
            user = job.created_by  # Use created_by as user for tenant service
            
            # Update freshness metric
            FreshnessMapService.update_freshness_metric(job, user)
            
            logger.debug(f"Updated freshness metric for job {job.id}")
        except Exception as e:
            logger.error(f"Error updating freshness metric for job {instance.job.id}: {str(e)}", exc_info=True)
