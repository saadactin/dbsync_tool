"""
Cron expression parser for custom schedules
Uses croniter to parse and calculate next run times
"""
from typing import Optional
from datetime import datetime
from django.utils import timezone
from django.conf import settings
from croniter import croniter
import pytz
import logging

logger = logging.getLogger(__name__)


def parse_cron_expression(cron_expr: str, start_time: Optional[datetime] = None) -> Optional[datetime]:
    """
    Parse cron expression and get next run time
    
    Args:
        cron_expr: Cron expression (e.g., '*/5 * * * *' for every 5 minutes)
        start_time: Starting time for calculation (defaults to now)
        
    Returns:
        Next run datetime or None if invalid expression
    """
    if not cron_expr or not cron_expr.strip():
        return None
    
    try:
        # Use current time if not provided
        if start_time is None:
            start_time = timezone.now()
        
        # Ensure timezone-aware datetime in Django's configured timezone
        if timezone.is_naive(start_time):
            tz = pytz.timezone(settings.TIME_ZONE)
            start_time = tz.localize(start_time)
        else:
            # Convert to Django's timezone if needed
            tz = pytz.timezone(settings.TIME_ZONE)
            if start_time.tzinfo != tz:
                start_time = start_time.astimezone(tz)
        
        # Parse cron expression (croniter works with timezone-aware datetimes)
        cron = croniter(cron_expr.strip(), start_time)
        next_run = cron.get_next(datetime)
        
        # Ensure timezone-aware in Django's timezone
        if timezone.is_naive(next_run):
            tz = pytz.timezone(settings.TIME_ZONE)
            next_run = tz.localize(next_run)
        else:
            # Convert to Django's timezone
            tz = pytz.timezone(settings.TIME_ZONE)
            if next_run.tzinfo != tz:
                next_run = next_run.astimezone(tz)
        
        return next_run
        
    except Exception as e:
        logger.error(f"Error parsing cron expression '{cron_expr}': {str(e)}")
        return None


def validate_cron_expression(cron_expr: str) -> bool:
    """
    Validate cron expression format
    
    Args:
        cron_expr: Cron expression to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not cron_expr or not cron_expr.strip():
        return False
    
    try:
        # Try to create a croniter instance
        now = timezone.now()
        cron = croniter(cron_expr.strip(), now)
        # Try to get next run to ensure it's valid
        cron.get_next(datetime)
        return True
    except Exception:
        return False


def get_next_runs(cron_expr: str, count: int = 5, start_time: Optional[datetime] = None) -> list:
    """
    Get next N run times for a cron expression
    
    Args:
        cron_expr: Cron expression
        count: Number of future runs to calculate
        start_time: Starting time for calculation
        
    Returns:
        List of datetime objects for next runs
    """
    if not cron_expr or not cron_expr.strip():
        return []
    
    try:
        if start_time is None:
            start_time = timezone.now()
        
        if timezone.is_naive(start_time):
            start_time = timezone.make_aware(start_time)
        
        cron = croniter(cron_expr.strip(), start_time)
        next_runs = []
        
        for _ in range(count):
            next_run = cron.get_next(datetime)
            if timezone.is_naive(next_run):
                next_run = timezone.make_aware(next_run)
            next_runs.append(next_run)
        
        return next_runs
        
    except Exception as e:
        logger.error(f"Error getting next runs for '{cron_expr}': {str(e)}")
        return []

