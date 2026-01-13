from django import template
from django.utils import timezone

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def status_badge_class(status):
    """Return Bootstrap badge class for status"""
    status_map = {
        'pending': 'secondary',
        'running': 'info',
        'completed': 'success',
        'failed': 'danger',
        'cancelled': 'warning',
        'paused': 'warning',
    }
    return status_map.get(status, 'secondary')

@register.filter
def execution_duration(execution):
    """Calculate and format execution duration"""
    if execution.completed_at and execution.started_at:
        duration = execution.completed_at - execution.started_at
    elif execution.status == 'running' and execution.started_at:
        duration = timezone.now() - execution.started_at
    else:
        return '-'
    
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

@register.filter
def format_duration(duration):
    """Format a timedelta object as human-readable duration"""
    if duration is None:
        return '-'
    
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

@register.filter
def get_checkpoint_for_table(table, checkpoint_map):
    """Get checkpoint for a table from checkpoint_map"""
    if not checkpoint_map or not table:
        return None
    try:
        key = f"{table.schema_name}|{table.table_name}"
        return checkpoint_map.get(key)
    except (AttributeError, KeyError):
        return None

