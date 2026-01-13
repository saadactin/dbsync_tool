"""
Schedule management utilities
Handles next run calculation and scheduled job triggering
"""
from typing import Optional
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncSchedule
from scheduler.cron_parser import parse_cron_expression
import logging
import threading

logger = logging.getLogger(__name__)


def calculate_next_run(schedule: SyncSchedule) -> Optional[timezone.datetime]:
    """
    Calculate next run time based on schedule configuration
    
    Args:
        schedule: SyncSchedule instance
        
    Returns:
        datetime for next run or None if schedule disabled/invalid
    """
    if not schedule.is_enabled:
        return None
    
    now = timezone.now()
    
    if schedule.schedule_type == 'once':
        # Run once at specified time (if in future)
        if schedule.next_run_at and schedule.next_run_at > now:
            return schedule.next_run_at
        # Already past or not set
        return None
    
    elif schedule.schedule_type == 'hourly':
        # Run every hour
        if schedule.next_run_at and schedule.next_run_at > now:
            return schedule.next_run_at
        # Calculate next hour
        next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_run
    
    elif schedule.schedule_type == 'daily':
        # Run daily at midnight (or specified time)
        if schedule.next_run_at and schedule.next_run_at > now:
            return schedule.next_run_at
        # Calculate next midnight
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run
    
    elif schedule.schedule_type == 'weekly':
        # Run weekly (Monday at midnight)
        if schedule.next_run_at and schedule.next_run_at > now:
            return schedule.next_run_at
        # Calculate next Monday
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7  # Next week's Monday
        next_run += timedelta(days=days_until_monday)
        return next_run
    
    elif schedule.schedule_type == 'custom':
        # Use cron expression parsing
        # Always calculate from current time for custom cron (don't use old next_run_at)
        if schedule.cron_expression:
            next_run = parse_cron_expression(schedule.cron_expression, now)
            return next_run
        return None
    
    return None


def schedule_job_execution(job: SyncJob):
    """
    Schedule a job for execution based on its schedule configuration
    
    Args:
        job: SyncJob instance
    """
    try:
        if not hasattr(job, 'schedule') or not job.schedule:
            logger.debug(f"Job {job.id} has no schedule")
            return
        
        schedule = job.schedule
        if not schedule.is_enabled:
            logger.debug(f"Job {job.id} schedule is disabled")
            return
        
        next_run = calculate_next_run(schedule)
        if next_run:
            schedule.next_run_at = next_run
            schedule.save(update_fields=['next_run_at'])
            
            job.next_run_at = next_run
            job.save(update_fields=['next_run_at'])
            
            logger.info(f"Scheduled job {job.id} for execution at {next_run}")
        else:
            logger.debug(f"Job {job.id} has no next run time")
    except Exception as e:
        logger.error(f"Error scheduling job {job.id}: {str(e)}", exc_info=True)


def execute_sync_job_direct(job_id: str):
    """
    Execute a sync job directly (without Celery)
    
    Args:
        job_id: UUID string of SyncJob to execute
    """
    try:
        from sync_engine.executor import SyncExecutor
        from django.db import transaction
        
        # Get job from database
        try:
            with transaction.atomic():
                job = SyncJob.objects.select_for_update().get(id=job_id)
                
                # Check if job is already running or paused before spawning thread
                if job.status == 'running':
                    logger.warning(f"Job {job_id} is already running, skipping")
                    return
                if job.status == 'paused':
                    logger.info(f"Job {job_id} is paused, skipping execution")
                    return
                
                # Mark as running immediately to prevent duplicate triggers
                job.status = 'running'
                job.save(update_fields=['status'])
        except SyncJob.DoesNotExist:
            logger.error(f"Job {job_id} not found")
            return
        
        # Execute sync in a separate thread to avoid blocking
        def run_execution():
            try:
                logger.info(f"Starting execution of job {job_id}")
                executor = SyncExecutor(job)
                executor.execute()
                logger.info(f"Completed execution of job {job_id}")
            except Exception as e:
                logger.error(f"Error executing job {job_id}: {str(e)}", exc_info=True)
        
        thread = threading.Thread(target=run_execution)
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        logger.error(f"Error in execute_sync_job_direct for {job_id}: {str(e)}", exc_info=True)


def trigger_scheduled_jobs():
    """
    Trigger jobs that are due for execution
    This is a fallback mechanism - APScheduler handles most scheduling
    """
    from scheduler.service import trigger_due_jobs
    return trigger_due_jobs()

