"""
Schedule management utilities
Handles next run calculation and scheduled job triggering

Daily/hourly schedules use ``SyncSchedule.next_run_at`` as the wall-clock anchor
(hour/minute) in Django's default timezone (``settings.TIME_ZONE``).
"""
from typing import Optional
from django.utils import timezone
from datetime import timedelta, datetime
from sync_jobs.models import SyncJob, SyncSchedule
from scheduler.cron_parser import parse_cron_expression
import logging
import threading

logger = logging.getLogger(__name__)


def normalize_initial_next_run_for_schedule(
    schedule_type: str,
    dt: timezone.datetime,
    *,
    interval_hours: int = 1,
) -> timezone.datetime:
    """
    Align first-run time for hourly/daily/weekly jobs created from Step 4.

    Preserves hour and minute from the user's Start Date/Time; rolls forward
    until the time is strictly after *now* (same wall time, next eligible slot).
    For hourly, steps forward in ``interval_hours``-hour increments on the anchor grid.
    For weekly, advances in 7-day steps.
    """
    ih = max(1, min(24, int(interval_hours or 1)))
    dt = dt.replace(second=0, microsecond=0)
    now = timezone.now()
    if schedule_type == "hourly":
        while dt <= now:
            dt += timedelta(hours=ih)
        return dt
    if schedule_type == "daily":
        while dt <= now:
            dt += timedelta(days=1)
        return dt
    if schedule_type == "weekly":
        while dt <= now:
            dt += timedelta(weeks=1)
        return dt
    return dt


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
        # Anchor grid: advance by interval_hours from last anchor when due/past
        ih = getattr(schedule, "interval_hours", None) or 1
        ih = max(1, min(24, int(ih)))
        if schedule.next_run_at:
            if schedule.next_run_at > now:
                return schedule.next_run_at
            n = schedule.next_run_at.replace(second=0, microsecond=0)
            while n <= now:
                n += timedelta(hours=ih)
            return n
        next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=ih)
        return next_run

    elif schedule.schedule_type == 'daily':
        # Same clock time each day (from next_run_at anchor)
        if schedule.next_run_at:
            if schedule.next_run_at > now:
                return schedule.next_run_at
            n = schedule.next_run_at.replace(second=0, microsecond=0)
            while n <= now:
                n += timedelta(days=1)
            return n
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

    elif schedule.schedule_type == 'weekly':
        if schedule.next_run_at:
            if schedule.next_run_at > now:
                return schedule.next_run_at
            n = schedule.next_run_at.replace(second=0, microsecond=0)
            while n <= now:
                n += timedelta(weeks=1)
            return n
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
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

                # Cron may fire every hour at :m before DB next_run_at (first-run anchor); do not start early.
                now = timezone.now()
                sched = getattr(job, "schedule", None)
                if sched and sched.next_run_at:
                    nr = sched.next_run_at
                    if isinstance(nr, datetime) and nr > now:
                        logger.info(
                            "Job %s skipped: not due until %s (now=%s)",
                            job_id,
                            nr,
                            now,
                        )
                        return

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

