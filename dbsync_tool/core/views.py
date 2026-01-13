from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from core.monitoring import HealthCheckService, PerformanceMonitor


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

