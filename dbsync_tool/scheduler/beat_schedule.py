"""
Celery Beat schedule configuration for periodic task execution
"""
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule
from django.core.exceptions import ObjectDoesNotExist
import logging

logger = logging.getLogger(__name__)


def setup_beat_schedule():
    """
    Setup Celery Beat schedule for periodic task execution
    This creates the periodic task that triggers scheduled sync jobs every minute
    Should be called on Django startup (via AppConfig.ready() or management command)
    
    Returns:
        tuple: (PeriodicTask instance, created boolean)
    """
    try:
        # Create interval schedule for checking scheduled jobs (every minute)
        interval_schedule, created = IntervalSchedule.objects.get_or_create(
            every=1,
            period=IntervalSchedule.MINUTES,
        )
        
        if created:
            logger.info("Created IntervalSchedule: every 1 minute")
        else:
            logger.debug("Using existing IntervalSchedule: every 1 minute")
        
        # Create or update periodic task
        periodic_task, task_created = PeriodicTask.objects.get_or_create(
            name='trigger-scheduled-jobs',
            defaults={
                'task': 'scheduler.tasks.trigger_scheduled_jobs_task',
                'interval': interval_schedule,
                'enabled': True,
                'description': 'Periodic task to trigger scheduled sync jobs every minute',
            }
        )
        
        if not task_created:
            # Update existing task
            periodic_task.interval = interval_schedule
            periodic_task.enabled = True
            periodic_task.task = 'scheduler.tasks.trigger_scheduled_jobs_task'
            periodic_task.description = 'Periodic task to trigger scheduled sync jobs every minute'
            periodic_task.save()
            logger.info("Updated existing periodic task 'trigger-scheduled-jobs'")
        else:
            logger.info("Created periodic task 'trigger-scheduled-jobs'")
        
        return periodic_task, task_created
        
    except Exception as e:
        logger.error(f"Error setting up Celery Beat schedule: {str(e)}", exc_info=True)
        raise


def cleanup_beat_schedule():
    """
    Cleanup beat schedule (for testing or reset)
    Removes the periodic task (but keeps interval schedule)
    """
    try:
        deleted, _ = PeriodicTask.objects.filter(name='trigger-scheduled-jobs').delete()
        if deleted > 0:
            logger.info(f"Deleted {deleted} periodic task(s)")
        return deleted
    except Exception as e:
        logger.error(f"Error cleaning up beat schedule: {str(e)}", exc_info=True)
        return 0


def verify_beat_schedule():
    """
    Verify that beat schedule is properly configured
    Returns True if configured correctly, False otherwise
    """
    try:
        task = PeriodicTask.objects.get(name='trigger-scheduled-jobs')
        if not task.enabled:
            logger.warning("Periodic task 'trigger-scheduled-jobs' exists but is disabled")
            return False
        if task.task != 'scheduler.tasks.trigger_scheduled_jobs_task':
            logger.warning(f"Periodic task has incorrect task name: {task.task}")
            return False
        return True
    except PeriodicTask.DoesNotExist:
        logger.warning("Periodic task 'trigger-scheduled-jobs' does not exist")
        return False
    except Exception as e:
        logger.error(f"Error verifying beat schedule: {str(e)}", exc_info=True)
        return False

