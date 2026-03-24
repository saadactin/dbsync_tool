"""
Validators for sync job creation and management
"""
import re
from typing import Iterable, List, Set
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
from core.sanitization import sanitize_string
from core.constants import DEFAULT_PROTECTED_COLUMN_NAMES


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


def validate_interval_hours(raw, schedule_type) -> int:
    """
    For hourly schedules: every N hours on the anchor grid (1-24).
    For other schedule types: always 1 (ignored).
    """
    if schedule_type != "hourly":
        return 1
    if raw is None:
        return 1
    s = raw.strip() if isinstance(raw, str) else str(raw)
    if not s:
        return 1
    try:
        n = int(s)
    except ValueError:
        raise ValidationError(
            "Interval hours must be a whole number between 1 and 24."
        )
    if n < 1 or n > 24:
        raise ValidationError("Interval hours must be between 1 and 24.")
    return n


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


def validate_schedule_start_inputs(
    start_datetime: str,
    start_date: str,
    start_time: str,
    schedule_type: str,
):
    """
    Resolve schedule start from combined datetime-local and/or separate date + time
    (Step 4 / job edit). Empty date and time means "start now" for recurring jobs.

    Args:
        start_datetime: Hidden or legacy combined field (YYYY-MM-DDTHH:mm)
        start_date: Optional YYYY-MM-DD
        start_time: Optional time as `HH:mm` (24-hour) or `h:mm AM/PM`
        schedule_type: once | hourly | daily | weekly | custom

    Returns:
        Aware datetime for recurring schedules, or None for ``once``.
    """
    if schedule_type == 'once':
        return None

    combined = (start_datetime or '').strip()
    if not combined:
        sd = (start_date or '').strip()
        st = (start_time or '').strip()
        if not sd and not st:
            return timezone.now()
        if not sd:
            sd = timezone.localdate().isoformat()
        if not st:
            st = '00:00'

        # Normalize start_time into strict `HH:mm` (24-hour) so that
        # validate_start_datetime can parse it reliably.
        #
        # Examples we support:
        # - "14:40"
        # - "2:40"
        # - "02:40 PM"
        # - "02:40AM"
        # - "02:40 am"
        st = st.strip()
        import re as _re

        ampm_match = _re.match(r'^(\d{1,2}):(\d{2})\s*([aApP][mM])$', st)
        if ampm_match:
            hour = int(ampm_match.group(1))
            minute = int(ampm_match.group(2))
            ampm = ampm_match.group(3).lower()
            if minute > 59:
                raise ValidationError("Invalid start_time minutes. Expected 0-59.")
            if ampm == 'pm' and hour < 12:
                hour += 12
            elif ampm == 'am' and hour == 12:
                hour = 0
            if hour > 23:
                raise ValidationError("Invalid start_time hour for AM/PM input. Expected 1-12.")
            st = f"{hour:02d}:{minute:02d}"
        else:
            time_match = _re.match(r'^(\d{1,2}):(\d{2})$', st)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                if hour > 23:
                    raise ValidationError("Invalid start_time hour. Expected 0-23 in 24-hour format.")
                if minute > 59:
                    raise ValidationError("Invalid start_time minutes. Expected 0-59.")
                st = f"{hour:02d}:{minute:02d}"
            else:
                # Backward/legacy tolerance: if value is longer (e.g. includes seconds),
                # try the first 5 characters as HH:mm; otherwise error out.
                if len(st) > 5:
                    candidate = st[:5].strip()
                    time_match2 = _re.match(r'^(\d{1,2}):(\d{2})$', candidate)
                    if not time_match2:
                        raise ValidationError("Invalid start_time format. Use `HH:mm` or `h:mm AM/PM`.")
                    hour = int(time_match2.group(1))
                    minute = int(time_match2.group(2))
                    if hour > 23 or minute > 59:
                        raise ValidationError("Invalid start_time value. Hour must be 0-23 and minutes 0-59.")
                    st = f"{hour:02d}:{minute:02d}"
                else:
                    raise ValidationError("Invalid start_time format. Use `HH:mm` or `h:mm AM/PM`.")

        combined = f"{sd}T{st}"

    return validate_start_datetime(combined, schedule_type)


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


def validate_target_column_name(column_name: str) -> str:
    """
    Validate target column name used in Step 3 mappings.
    """
    val = (column_name or "").strip()
    if not val:
        raise ValidationError("Target column name cannot be empty.")
    if len(val) > 100:
        raise ValidationError("Target column name must be <= 100 characters.")
    if not re.match(r"^[a-zA-Z0-9_]+$", val):
        raise ValidationError("Target column name may only contain letters, numbers, and underscores.")
    return val


def resolve_protected_columns(
    columns: Iterable[dict],
    predicted_incremental_column: str = None,
    manual_protected: Iterable[str] = None,
) -> List[str]:
    """
    Resolve protected source columns using PK flags, predicted incremental,
    configurable default names, and manual selections.
    Returns lower-cased source column names.
    """
    protected: Set[str] = set()
    manual_set = {(c or "").strip().lower() for c in (manual_protected or []) if c}
    default_names = {(c or "").strip().lower() for c in DEFAULT_PROTECTED_COLUMN_NAMES if c}
    predicted = (predicted_incremental_column or "").strip().lower()

    for col in columns or []:
        col_name = (col.get("name") or col.get("column_name") or "").strip()
        if not col_name:
            continue
        col_lower = col_name.lower()
        if col.get("is_primary_key"):
            protected.add(col_lower)
            continue
        if predicted and col_lower == predicted:
            protected.add(col_lower)
            continue
        if col_lower in default_names:
            protected.add(col_lower)
            continue
        if col_lower in manual_set:
            protected.add(col_lower)

    return sorted(protected)

