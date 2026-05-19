"""
Server-Sent Events (SSE) for real-time job status updates.

This provides real-time updates without WebSockets/Channels, using standard HTTP.
"""
import json
import time
import logging
from django.http import StreamingHttpResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .models import SyncJob, SyncExecution
from accounts.services.tenant_service import TenantService

logger = logging.getLogger(__name__)


def _get_job_status_data(user):
    """Get current status of all jobs for the user's tenant."""
    from sync_jobs.services import DashboardService
    from sync_jobs.views import _generate_heatmap_data
    from django.utils import timezone
    from datetime import timedelta

    # Get comprehensive dashboard statistics
    stats = DashboardService.get_user_statistics(user)

    # Get execution trends (last 30 days)
    trends = DashboardService.get_execution_trends(user, days=30)

    # Get recent activity (last 5 jobs)
    recent_activity = DashboardService.get_recent_activity(user, limit=5)

    # Get heatmap data (executions by day/hour for last 7 days)
    heatmap_data = _generate_heatmap_data(user)

    # Format trends for charts
    trends_formatted = []
    for trend in trends:
        trends_formatted.append({
            'day': trend['day'].strftime('%m/%d') if hasattr(trend['day'], 'strftime') else str(trend['day']),
            'total': trend.get('total', 0),
            'successful': trend.get('successful', 0),
            'failed': trend.get('failed', 0),
            'rows_synced': trend.get('rows_synced', 0) or 0,
        })

    # Format recent activity with time_ago
    recent_formatted = []
    for activity in recent_activity:
        if hasattr(activity, 'started_at') and activity.started_at:
            delta = timezone.now() - activity.started_at
            if delta.days > 7:
                time_ago = f"{delta.days // 7} week{'s' if delta.days // 7 > 1 else ''} ago"
            elif delta.days > 0:
                time_ago = f"{delta.days} day{'s' if delta.days > 1 else ''}, {delta.seconds // 3600} hour{'s' if delta.seconds // 3600 > 1 else ''} ago"
            elif delta.seconds >= 3600:
                time_ago = f"{delta.seconds // 3600} hour{'s' if delta.seconds // 3600 > 1 else ''} ago"
            elif delta.seconds >= 60:
                time_ago = f"{delta.seconds // 60} minute{'s' if delta.seconds // 60 > 1 else ''} ago"
            else:
                time_ago = "Just now"
        else:
            time_ago = "Unknown"

        recent_formatted.append({
            'job_id': str(activity.job.id) if hasattr(activity, 'job') else None,
            'job_name': activity.job.name if hasattr(activity, 'job') else 'N/A',
            'time_ago': time_ago,
            'rows_synced': getattr(activity, 'total_rows_synced', 0) or 0,
            'status': activity.status if hasattr(activity, 'status') else 'unknown',
        })

    return {
        'stats': stats,
        'trends': trends_formatted,
        'recent_activity': recent_formatted,
        'heatmap_data': heatmap_data,
    }


def _get_execution_status_data(execution_id):
    """Get detailed status for a specific execution."""
    try:
        execution = SyncExecution.objects.select_related('job').get(id=execution_id)

        # Get table-level status
        table_status = []
        for table in execution.table_logs.all():
            table_status.append({
                'table_name': table.table_name,
                'status': table.status,
                'rows_fetched': table.rows_fetched or 0,
                'rows_inserted': table.rows_inserted or 0,
                'error_message': table.error_message,
            })

        return {
            'execution_id': execution.id,
            'job_id': execution.job.id,
            'job_name': execution.job.name,
            'status': execution.status,
            'started_at': execution.started_at.isoformat() if execution.started_at else None,
            'completed_at': execution.completed_at.isoformat() if execution.completed_at else None,
            'duration_seconds': execution.duration_seconds,
            'rows_fetched': execution.rows_fetched or 0,
            'rows_inserted': execution.rows_inserted or 0,
            'error_message': execution.error_message,
            'table_status': table_status,
        }
    except SyncExecution.DoesNotExist:
        return None


def _sse_event_stream(user, event_type='dashboard', target_id=None):
    """
    Generator that yields SSE events for real-time updates.

    Args:
        user: Django User object
        event_type: 'dashboard' for all jobs, 'execution' for single execution
        target_id: execution_id if event_type='execution'
    """
    # Send initial data
    if event_type == 'dashboard':
        initial_data = _get_job_status_data(user)
        # Merge data into a single response
        response_data = {'type': 'initial'}
        response_data.update(initial_data)
        yield f"data: {json.dumps(response_data)}\n\n"
    elif event_type == 'execution' and target_id:
        initial_data = _get_execution_status_data(target_id)
        if initial_data:
            yield f"data: {json.dumps({'type': 'initial', 'execution': initial_data})}\n\n"

    # Poll for updates every 2 seconds
    last_data = initial_data
    max_duration = 3600  # 1 hour max connection
    start_time = time.time()

    while (time.time() - start_time) < max_duration:
        try:
            time.sleep(2)  # Poll interval

            # Get current data
            if event_type == 'dashboard':
                current_data = _get_job_status_data(user)
            elif event_type == 'execution' and target_id:
                current_data = _get_execution_status_data(target_id)
                if current_data is None:
                    # Execution not found, close connection
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Execution not found'})}\n\n"
                    break
            else:
                break

            # Send update if data changed
            if current_data != last_data:
                if event_type == 'dashboard':
                    response_data = {'type': 'update'}
                    response_data.update(current_data)
                    yield f"data: {json.dumps(response_data)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'update', 'execution': current_data})}\n\n"
                last_data = current_data

                # If execution completed, send final event and close
                if event_type == 'execution' and current_data.get('status') in ['completed', 'failed', 'cancelled']:
                    yield f"data: {json.dumps({'type': 'completed', 'execution': current_data})}\n\n"
                    break

            # Send heartbeat to keep connection alive
            yield ": heartbeat\n\n"

        except GeneratorExit:
            logger.debug("SSE client disconnected")
            break
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            break

    # Send close event
    yield f"data: {json.dumps({'type': 'close'})}\n\n"


@require_GET
@login_required
def dashboard_status_stream(request):
    """
    SSE endpoint for real-time dashboard updates.

    Usage in JavaScript:
        const eventSource = new EventSource('/sync-jobs/sse/dashboard/');
        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.type === 'update') {
                updateDashboard(data.jobs);
            }
        };
    """
    response = StreamingHttpResponse(
        _sse_event_stream(request.user, event_type='dashboard'),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    return response


@require_GET
@login_required
def execution_status_stream(request, execution_id):
    """
    SSE endpoint for real-time execution detail updates.

    URL: /sync-jobs/sse/execution/<execution_id>/

    Usage in JavaScript:
        const eventSource = new EventSource('/sync-jobs/sse/execution/123/');
        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.type === 'update') {
                updateExecutionDetail(data.execution);
            }
        };
    """
    # Verify user has access to this execution
    try:
        execution = SyncExecution.objects.select_related('job').get(id=execution_id)
        job_qs = SyncJob.objects.filter(id=execution.job.id)
        job_qs = TenantService.get_queryset_for_user(job_qs, request.user)
        if not job_qs.exists():
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Access denied")
    except SyncExecution.DoesNotExist:
        from django.http import HttpResponseNotFound
        return HttpResponseNotFound("Execution not found")

    response = StreamingHttpResponse(
        _sse_event_stream(request.user, event_type='execution', target_id=execution_id),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
