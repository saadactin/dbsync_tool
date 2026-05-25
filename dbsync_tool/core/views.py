from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from core.monitoring import HealthCheckService, PerformanceMonitor
from core.models import NotificationRecipient
from core.decorators import api_view, json_response
import json
import logging

logger = logging.getLogger(__name__)


@login_required
def dashboard(request):
    """
    Redirect to sync_jobs dashboard
    """
    from django.shortcuts import redirect
    return redirect('sync_jobs:dashboard')


@require_http_methods(["GET"])
def health_check(request):
    """
    Health check endpoint for monitoring
    Returns system health status
    """
    health = HealthCheckService.get_system_health()
    status_code = 200 if health['overall_status'] == 'healthy' else 503
    return JsonResponse(health, status=status_code)


@require_http_methods(["GET"])
def performance_metrics(request):
    """
    Performance metrics endpoint
    Returns system performance metrics
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    metrics = {
        'celery_stats': PerformanceMonitor.get_celery_stats(),
        'queue_lengths': PerformanceMonitor.get_queue_lengths(),
    }
    
    return JsonResponse(metrics)


def permission_denied_view(request, exception):
    """Custom 403 error handler"""
    return render(request, '403.html', {'exception': exception}, status=403)


def page_not_found_view(request, exception):
    """Custom 404 error handler"""
    return render(request, '404.html', {'exception': exception}, status=404)


def server_error_view(request):
    """Custom 500 error handler"""
    return render(request, '500.html', status=500)


@login_required
def notifications_page(request):
    """
    Notifications management page - allows admins to manage email recipients
    for system alerts (e.g., server shutdown notifications).
    """
    return render(request, 'notifications.html')


@api_view(methods=['GET'])
@json_response
def notification_recipients_list(request):
    """
    API endpoint: List all notification recipients.
    GET /api/notification-recipients/
    """
    recipients = NotificationRecipient.objects.all().order_by('-created_at')
    data = [
        {
            'id': r.id,
            'email': r.email,
            'name': r.name,
            'is_active': r.is_active,
            'created_at': r.created_at.isoformat(),
            'updated_at': r.updated_at.isoformat(),
        }
        for r in recipients
    ]
    return {'success': True, 'data': data}


@api_view(methods=['POST'])
@json_response
def notification_recipients_create(request):
    """
    API endpoint: Add a new notification recipient.
    POST /api/notification-recipients/
    Body: {"email": "user@example.com", "name": "John Doe" (optional)}
    """
    data = request.json_data or {}
    email = data.get('email', '').strip()
    name = data.get('name', '').strip()

    if not email:
        raise ValueError('Email is required')

    # Validate email format
    try:
        validate_email(email)
    except ValidationError:
        raise ValueError('Invalid email format')

    # Check for duplicates
    if NotificationRecipient.objects.filter(email=email).exists():
        raise ValueError('Email already exists')

    # Create recipient
    recipient = NotificationRecipient.objects.create(
        email=email,
        name=name,
        is_active=True
    )

    return JsonResponse({
        'success': True,
        'message': 'Recipient added successfully',
        'data': {
            'id': recipient.id,
            'email': recipient.email,
            'name': recipient.name,
            'is_active': recipient.is_active,
            'created_at': recipient.created_at.isoformat(),
        }
    }, status=201)


@api_view(methods=['PATCH'])
@json_response
def notification_recipients_toggle(request, recipient_id):
    """
    API endpoint: Toggle active/inactive status.
    PATCH /api/notification-recipients/<id>/toggle/
    """
    try:
        recipient = NotificationRecipient.objects.get(id=recipient_id)
    except NotificationRecipient.DoesNotExist:
        raise ValueError('Recipient not found')

    old_status = recipient.is_active
    recipient.is_active = not recipient.is_active
    recipient.save()

    logger.info(f"User {request.user.username} toggled recipient {recipient.email} from {old_status} to {recipient.is_active}")

    return {
        'success': True,
        'message': f'Recipient {"activated" if recipient.is_active else "deactivated"}',
        'data': {
            'id': recipient.id,
            'is_active': recipient.is_active
        }
    }


@api_view(methods=['DELETE'])
@json_response
def notification_recipients_delete(request, recipient_id):
    """
    API endpoint: Delete a notification recipient.
    DELETE /api/notification-recipients/<id>/delete/
    """
    try:
        recipient = NotificationRecipient.objects.get(id=recipient_id)
    except NotificationRecipient.DoesNotExist:
        raise ValueError('Recipient not found')

    email = recipient.email
    recipient.delete()

    logger.info(f"User {request.user.username} deleted recipient {email}")

    return {
        'success': True,
        'message': f'Recipient {email} deleted successfully'
    }

