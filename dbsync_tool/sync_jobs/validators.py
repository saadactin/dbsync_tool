"""
Validators for sync job creation and management
"""
import re
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
from core.sanitization import sanitize_string


def validate_job_name(name):
    """
    Validate sync job name
    
    Args:
        name: Job name string
    
    Returns:
        Sanitized name
    
    Raises:
        ValidationError: If validation fails
    """
    # Required field check
    if not name:
        raise ValidationError("Job name is required.")
    
    # Strip and sanitize
    name = name.strip()
    name = sanitize_string(name, max_length=100)
    
    # Length validation
    if len(name) < 1:
        raise ValidationError("Job name cannot be empty.")
    
    if len(name) > 100:
        raise ValidationError("Job name must be no more than 100 characters long.")
    
    # Format validation (alphanumeric, spaces, underscore, hyphen)
    if not re.match(r'^[a-zA-Z0-9\s_-]+$', name):
        raise ValidationError("Job name can only contain letters, numbers, spaces, underscores, and hyphens.")
    
    return name


def validate_sync_type(sync_type):
    """
    Validate sync type
    
    Args:
        sync_type: Sync type string
    
    Returns:
        Validated sync type
    
    Raises:
        ValidationError: If validation fails
    """
    # Required field check
    if not sync_type:
        raise ValidationError("Sync type is required.")
    
    # Enum validation
    valid_types = ['full', 'incremental']
    if sync_type not in valid_types:
        raise ValidationError(f"Invalid sync type. Must be one of: {', '.join(valid_types)}")
    
    return sync_type


def validate_schedule_type(schedule_type):
    """
    Validate schedule type
    
    Args:
        schedule_type: Schedule type string
    
    Returns:
        Validated schedule type
    
    Raises:
        ValidationError: If validation fails
    """
    # Required field check
    if not schedule_type:
        raise ValidationError("Schedule type is required.")
    
    # Enum validation
    valid_types = ['once', 'hourly', 'daily', 'weekly', 'custom']
    if schedule_type not in valid_types:
        raise ValidationError(f"Invalid schedule type. Must be one of: {', '.join(valid_types)}")
    
    return schedule_type


def validate_cron_expression(cron_expression):
    """
    Validate cron expression format
    
    Args:
        cron_expression: Cron expression string
    
    Returns:
        Validated cron expression
    
    Raises:
        ValidationError: If validation fails
    """
    if not cron_expression:
        raise ValidationError("Cron expression is required.")
    
    # Strip whitespace
    cron_expression = cron_expression.strip()
    
    # Basic format validation: 5 fields separated by spaces
    parts = cron_expression.split()
    if len(parts) != 5:
        raise ValidationError("Cron expression must have exactly 5 fields: minute hour day month day-of-week")
    
    # Validate each field
    minute, hour, day, month, day_of_week = parts
    
    # Minute: 0-59 or * or */n or n1-n2 or n1,n2,n3
    if not re.match(r'^(\*|\d+(-\d+)?(/\d+)?|(\d+,)+\d+)$', minute):
        raise ValidationError("Invalid minute field in cron expression. Must be 0-59, *, */n, n1-n2, or n1,n2,n3")
    
    # Hour: 0-23 or * or */n or n1-n2 or n1,n2,n3
    if not re.match(r'^(\*|\d+(-\d+)?(/\d+)?|(\d+,)+\d+)$', hour):
        raise ValidationError("Invalid hour field in cron expression. Must be 0-23, *, */n, n1-n2, or n1,n2,n3")
    
    # Day: 1-31 or * or */n or n1-n2 or n1,n2,n3
    if not re.match(r'^(\*|\d+(-\d+)?(/\d+)?|(\d+,)+\d+)$', day):
        raise ValidationError("Invalid day field in cron expression. Must be 1-31, *, */n, n1-n2, or n1,n2,n3")
    
    # Month: 1-12 or * or */n or n1-n2 or n1,n2,n3
    if not re.match(r'^(\*|\d+(-\d+)?(/\d+)?|(\d+,)+\d+)$', month):
        raise ValidationError("Invalid month field in cron expression. Must be 1-12, *, */n, n1-n2, or n1,n2,n3")
    
    # Day of week: 0-7 or * or */n or n1-n2 or n1,n2,n3 (0 and 7 both mean Sunday)
    if not re.match(r'^(\*|\d+(-\d+)?(/\d+)?|(\d+,)+\d+)$', day_of_week):
        raise ValidationError("Invalid day-of-week field in cron expression. Must be 0-7, *, */n, n1-n2, or n1,n2,n3")
    
    # Range validation for numeric values
    def validate_range(value, min_val, max_val, field_name):
        """Validate numeric range in cron field"""
        if value == '*':
            return True
        
        # Handle ranges like 0-59
        if '-' in value:
            parts = value.split('-')
            if len(parts) == 2:
                try:
                    start, end = int(parts[0]), int(parts[1])
                    if start < min_val or end > max_val or start > end:
                        raise ValidationError(f"Invalid range in {field_name} field: {value}")
                except ValueError:
                    raise ValidationError(f"Invalid numeric value in {field_name} field: {value}")
        
        # Handle lists like 0,5,10
        if ',' in value:
            for v in value.split(','):
                try:
                    num = int(v)
                    if num < min_val or num > max_val:
                        raise ValidationError(f"Invalid value in {field_name} field: {v}")
                except ValueError:
                    raise ValidationError(f"Invalid numeric value in {field_name} field: {v}")
        
        # Handle single values
        try:
            num = int(value.replace('/', '').split('/')[0])
            if num < min_val or num > max_val:
                raise ValidationError(f"Invalid value in {field_name} field: {value}")
        except ValueError:
            pass  # Could be */n format
        
        return True
    
    validate_range(minute, 0, 59, 'minute')
    validate_range(hour, 0, 23, 'hour')
    validate_range(day, 1, 31, 'day')
    validate_range(month, 1, 12, 'month')
    validate_range(day_of_week, 0, 7, 'day-of-week')
    
    return cron_expression


def validate_start_datetime(start_datetime, schedule_type):
    """
    Validate start datetime
    
    Args:
        start_datetime: Datetime string
        schedule_type: Schedule type
    
    Returns:
        Validated datetime object
    
    Raises:
        ValidationError: If validation fails
    """
    # Only required for scheduled jobs (not 'once')
    if schedule_type == 'once':
        return None
    
    if not start_datetime:
        # Default to current time if not provided
        return timezone.now()
    
    # Strip whitespace
    start_datetime = start_datetime.strip()
    
    # Parse datetime-local format (YYYY-MM-DDTHH:mm)
    try:
        dt_str = start_datetime.replace('T', ' ')
        if ':' in dt_str:
            # Ensure we have seconds
            if dt_str.count(':') == 1:
                dt_str += ':00'
        
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        
        # Future date check (if scheduled)
        if schedule_type != 'once' and dt < timezone.now():
            raise ValidationError("Start datetime must be in the future for scheduled jobs.")
        
        return dt
    except ValueError as e:
        raise ValidationError(f"Invalid datetime format: {str(e)}. Expected format: YYYY-MM-DDTHH:mm")


def validate_incremental_column(column_name, table_name):
    """
    Validate incremental column name
    
    Args:
        column_name: Column name string
        table_name: Table name for context
    
    Returns:
        Validated column name
    
    Raises:
        ValidationError: If validation fails
    """
    if not column_name:
        raise ValidationError(f"Incremental column is required for table {table_name}.")
    
    # Strip and sanitize
    column_name = column_name.strip()
    column_name = sanitize_string(column_name, max_length=100)
    
    # Length validation
    if len(column_name) < 1:
        raise ValidationError(f"Incremental column name cannot be empty for table {table_name}.")
    
    if len(column_name) > 100:
        raise ValidationError(f"Incremental column name must be no more than 100 characters for table {table_name}.")
    
    # Format validation (alphanumeric, underscore)
    if not re.match(r'^[a-zA-Z0-9_]+$', column_name):
        raise ValidationError(f"Invalid column name format for table {table_name}. Column names can only contain letters, numbers, and underscores.")
    
    return column_name

