"""
API views for Celery task status - DISABLED FOR MVP
In MVP, sync jobs run synchronously, so task status endpoints are not needed.
"""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
# from celery.result import AsyncResult  # DISABLED FOR MVP
import logging

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET"])
def task_status(request, task_id):
    """
    Get status of a task - DISABLED FOR MVP
    
    In MVP, tasks run synchronously, so this endpoint returns not available.
    For async execution, check the execution status directly from SyncExecution model.
    """
    return JsonResponse({
        'error': 'Task status API not available in MVP. Jobs run synchronously. Check execution status via job detail page.'
    }, status=410)  # 410 Gone - feature not available
