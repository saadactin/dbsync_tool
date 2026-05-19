"""
Scheduler service using APScheduler
Manages scheduled sync jobs without Celery/Redis

Hourly schedules with ``interval_hours == 1`` use a cron trigger at the minute from
``next_run_at``. For ``interval_hours > 1``, an ``IntervalTrigger`` is used. Daily
uses hour/minute from ``next_run_at`` (Django default timezone). The periodic
``trigger_due_jobs`` task only starts runs; ``next_run_at`` is advanced when the sync
finishes (see ``schedule_job_execution`` from ``SyncExecutor``).
"""
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from sync_jobs.models import SyncJob, SyncSchedule
from scheduler.cron_parser import parse_cron_expression, validate_cron_expression
import logging
import threading
import atexit
import pytz

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[BackgroundScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> Optional[BackgroundScheduler]:
    """Get the global scheduler instance"""
    return _scheduler


def start_scheduler():
    """
    Initialize and start the scheduler
    Should be called once on Django startup
    """
    global _scheduler
    
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            logger.warning("Scheduler is already running")
            return
        
        try:
            # Configure scheduler with Django timezone
            timezone_str = getattr(settings, 'TIME_ZONE', 'UTC')
            tz = pytz.timezone(timezone_str)
            
            _scheduler = BackgroundScheduler(timezone=tz)
            _scheduler.start()
            logger.info(f"Scheduler started successfully with timezone: {timezone_str}")
            
            # Load all existing scheduled jobs
            load_all_jobs()
            
            # Add periodic checker: runs every minute to trigger due jobs
            # This ensures jobs run at their scheduled times even if per-job triggers miss,
            # and picks up jobs created before the scheduler was ready
            _scheduler.add_job(
                func=trigger_due_jobs,
                trigger=IntervalTrigger(minutes=1),
                id='trigger_due_jobs_checker',
                name='Check and trigger due sync jobs',
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info("Added periodic due-jobs checker (every 1 minute)")

            # Add daily health check: tests all connections at configured time
            # Time is read from HEALTH_CHECK_TIME env variable (default: 02:00)
            health_check_time = getattr(settings, 'HEALTH_CHECK_TIME', '02:00')
            try:
                hour, minute = health_check_time.split(':')
                _scheduler.add_job(
                    func=run_daily_health_check,
                    trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
                    id='daily_health_check',
                    name='Daily connection health check',
                    replace_existing=True,
                    misfire_grace_time=3600,  # 1 hour grace
                )
                logger.info(f"Added daily health check (runs at {health_check_time} {timezone_str})")
            except Exception as e:
                logger.error(f"Failed to schedule daily health check: {e}")

            # Register shutdown handler
            atexit.register(stop_scheduler)
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {str(e)}", exc_info=True)
            _scheduler = None


def stop_scheduler():
    """
    Gracefully stop the scheduler
    """
    global _scheduler
    
    with _scheduler_lock:
        if _scheduler is None:
            return
        
        try:
            if _scheduler.running:
                _scheduler.shutdown(wait=True)
                logger.info("Scheduler stopped successfully")
            _scheduler = None
        except Exception as e:
            logger.error(f"Error stopping scheduler: {str(e)}", exc_info=True)


def add_job_schedule(job: SyncJob):
    """
    Add or update a job schedule in the scheduler
    
    Args:
        job: SyncJob instance with schedule
    """
    if _scheduler is None or not _scheduler.running:
        logger.warning("Scheduler is not running, cannot add job schedule")
        return
    
    try:
        if not hasattr(job, 'schedule') or not job.schedule:
            logger.debug(f"Job {job.id} has no schedule")
            return
        
        schedule = job.schedule
        
        if not schedule.is_enabled:
            logger.debug(f"Job {job.id} schedule is disabled")
            remove_job_schedule(job)
            return
        
        # Remove existing job if present
        job_id = f"sync_job_{job.id}"
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass  # Job doesn't exist, that's fine
        
        # Create trigger based on schedule type
        trigger = None
        
        if schedule.schedule_type == 'once':
            if schedule.next_run_at and schedule.next_run_at > timezone.now():
                trigger = DateTrigger(run_date=schedule.next_run_at)
            else:
                logger.debug(f"Job {job.id} 'once' schedule is in the past, skipping")
                return
        
        elif schedule.schedule_type == 'hourly':
            # Every hour at :minute (N=1) or IntervalTrigger every N hours from anchor (N>1)
            tz = pytz.timezone(settings.TIME_ZONE)
            if not schedule.next_run_at:
                logger.warning(f"Job {job.id} hourly schedule has no next_run_at; cannot build trigger")
                return
            local = timezone.localtime(schedule.next_run_at)
            interval_h = getattr(schedule, "interval_hours", None) or 1
            interval_h = max(1, min(24, int(interval_h)))
            if interval_h == 1:
                trigger = CronTrigger(minute=local.minute, timezone=tz)
            else:
                trigger = IntervalTrigger(
                    hours=interval_h,
                    start_date=schedule.next_run_at,
                    timezone=tz,
                )

        elif schedule.schedule_type == 'daily':
            # Same local time each day (hour/minute from next_run_at)
            tz = pytz.timezone(settings.TIME_ZONE)
            if not schedule.next_run_at:
                logger.warning(f"Job {job.id} daily schedule has no next_run_at; cannot build trigger")
                return
            local = timezone.localtime(schedule.next_run_at)
            trigger = CronTrigger(hour=local.hour, minute=local.minute, timezone=tz)

        elif schedule.schedule_type == 'weekly':
            tz = pytz.timezone(settings.TIME_ZONE)
            if schedule.next_run_at:
                local = timezone.localtime(schedule.next_run_at)
                trigger = CronTrigger(
                    day_of_week="mon",
                    hour=local.hour,
                    minute=local.minute,
                    timezone=tz,
                )
            else:
                trigger = CronTrigger(day_of_week="mon", hour=0, minute=0, timezone=tz)
        
        elif schedule.schedule_type == 'custom':
            if schedule.cron_expression:
                if not validate_cron_expression(schedule.cron_expression):
                    logger.error(f"Invalid cron expression for job {job.id}: {schedule.cron_expression}")
                    return
                
                # APScheduler CronTrigger can accept cron expression string directly
                # Format: minute hour day month day_of_week (standard cron format)
                # Use Django's configured timezone
                try:
                    tz = pytz.timezone(settings.TIME_ZONE)
                    trigger = CronTrigger.from_crontab(schedule.cron_expression.strip(), timezone=tz)
                except Exception as e:
                    logger.error(f"Error creating CronTrigger for job {job.id}: {str(e)}")
                    return
            else:
                logger.warning(f"Job {job.id} has custom schedule type but no cron expression")
                return
        
        if trigger is None:
            logger.warning(f"Could not create trigger for job {job.id}")
            return
        
        # Import here to avoid circular imports
        from scheduler.utils import execute_sync_job_direct
        
        # Add job to scheduler
        _scheduler.add_job(
            func=execute_sync_job_direct,
            trigger=trigger,
            args=[str(job.id)],
            id=job_id,
            name=f"Sync Job: {job.name}",
            replace_existing=True,
            max_instances=1,  # Prevent concurrent executions of same job
            misfire_grace_time=300  # 5 minutes grace time for missed executions
        )
        
        # Update next_run_at in database to match scheduler
        try:
            from scheduler.utils import schedule_job_execution
            schedule_job_execution(job)
            logger.info(f"Updated next_run_at for job {job.id}: {job.next_run_at}")
        except Exception as e:
            logger.warning(f"Error updating next_run_at for job {job.id}: {str(e)}")
        
        logger.info(f"Added job {job.id} to scheduler with trigger: {schedule.schedule_type}")
        
    except Exception as e:
        logger.error(f"Error adding job schedule for {job.id}: {str(e)}", exc_info=True)


def remove_job_schedule(job: SyncJob):
    """
    Remove a job from the scheduler
    
    Args:
        job: SyncJob instance
    """
    if _scheduler is None or not _scheduler.running:
        return
    
    try:
        job_id = f"sync_job_{job.id}"
        _scheduler.remove_job(job_id)
        logger.info(f"Removed job {job.id} from scheduler")
    except Exception as e:
        # Job might not exist in scheduler, that's fine
        logger.debug(f"Could not remove job {job.id} from scheduler: {str(e)}")


def load_all_jobs():
    """
    Load all enabled scheduled jobs into the scheduler
    Called on startup
    """
    try:
        jobs = SyncJob.objects.filter(
            status__in=['pending', 'completed', 'failed']
        ).select_related('schedule').prefetch_related('schedule')
        
        loaded_count = 0
        for job in jobs:
            if hasattr(job, 'schedule') and job.schedule and job.schedule.is_enabled:
                add_job_schedule(job)
                loaded_count += 1
        
        logger.info(f"Loaded {loaded_count} scheduled jobs into scheduler")
        
    except Exception as e:
        logger.error(f"Error loading jobs into scheduler: {str(e)}", exc_info=True)


def trigger_due_jobs():
    """
    Check for due jobs and trigger them
    This is a fallback mechanism that runs periodically
    """
    try:
        now = timezone.now()
        
        due_jobs = SyncJob.objects.filter(
            status__in=['pending', 'completed', 'failed'],
            next_run_at__lte=now
        ).select_related('schedule')
        
        triggered_count = 0
        
        for job in due_jobs:
            try:
                if not hasattr(job, 'schedule') or not job.schedule:
                    continue
                
                if not job.schedule.is_enabled:
                    continue
                
                if job.status == 'running':
                    continue
                
                # Trigger execution (next_run_at is advanced when the run finishes in SyncExecutor)
                from scheduler.utils import execute_sync_job_direct
                execute_sync_job_direct(str(job.id))
                triggered_count += 1

                logger.info(f"Triggered due job {job.id}")
                
            except Exception as e:
                logger.error(f"Error triggering job {job.id}: {str(e)}", exc_info=True)
                continue
        
        if triggered_count > 0:
            logger.info(f"Triggered {triggered_count} due job(s)")
        
        return triggered_count
        
    except Exception as e:
        logger.error(f"Error in trigger_due_jobs: {str(e)}", exc_info=True)
        return 0


def run_daily_health_check():
    """
    Run daily health check on all connections.
    Scheduled to run at configured time (default: 02:00).
    """
    try:
        logger.info("Starting daily health check...")

        from connections.health_check import run_health_check
        from connections.models import ConnectionHealthCheckLog

        # Run health check for all tenants
        results = run_health_check(tenant=None)

        # Save results to database
        log = ConnectionHealthCheckLog.objects.create(
            tested_at=results['tested_at'],
            total_tested=results['total_tested'],
            total_passed=results['total_passed'],
            total_failed=results['total_failed'],
            results_json=results,
            tenant=None
        )

        if results['total_failed'] > 0:
            logger.warning(
                f"Daily health check complete: {results['total_failed']} of {results['total_tested']} "
                f"connections failed. Log ID: {log.id}"
            )
        else:
            logger.info(
                f"Daily health check complete: All {results['total_tested']} connections healthy. "
                f"Log ID: {log.id}"
            )

        return log.id

    except Exception as e:
        logger.error(f"Error in daily health check: {str(e)}", exc_info=True)
        return None

