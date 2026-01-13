"""
Performance monitoring and health check service
"""
from django.utils import timezone
from django.db import connection
from django.core.cache import cache
# Celery and Redis imports - DISABLED FOR MVP
# from celery import current_app
# import redis
import logging

logger = logging.getLogger(__name__)


class HealthCheckService:
    """Service for health checks"""
    
    @staticmethod
    def check_database():
        """Check database connectivity"""
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return {'status': 'healthy', 'message': 'Database connection OK'}
        except Exception as e:
            return {'status': 'unhealthy', 'message': str(e)}
    
    @staticmethod
    def check_redis():
        """Check Redis connectivity - DISABLED FOR MVP"""
        return {
            'status': 'not_configured',
            'message': 'Redis not used in MVP - sync jobs run synchronously'
        }
    
    @staticmethod
    def check_celery():
        """Check Celery worker status - DISABLED FOR MVP"""
        return {
            'status': 'not_configured',
            'message': 'Celery not used in MVP - sync jobs run synchronously'
        }
    
    @staticmethod
    def get_system_health():
        """Get overall system health"""
        checks = {
            'database': HealthCheckService.check_database(),
            'redis': HealthCheckService.check_redis(),
            'celery': HealthCheckService.check_celery(),
        }
        
        # For MVP: Only check database health, Redis/Celery are not configured
        database_healthy = checks['database']['status'] == 'healthy'
        # Redis and Celery show as 'not_configured', not 'unhealthy'
        redis_not_configured = checks['redis']['status'] == 'not_configured'
        celery_not_configured = checks['celery']['status'] == 'not_configured'
        
        all_healthy = database_healthy and redis_not_configured and celery_not_configured
        
        return {
            'overall_status': 'healthy' if all_healthy else 'degraded',
            'checks': checks,
            'timestamp': timezone.now().isoformat(),
        }


class PerformanceMonitor:
    """Monitor system performance metrics"""
    
    @staticmethod
    def get_celery_stats():
        """Get Celery worker statistics - DISABLED FOR MVP"""
        return {
            'message': 'Celery not used in MVP - sync jobs run synchronously'
        }
    
    @staticmethod
    def get_queue_lengths():
        """Get queue lengths - DISABLED FOR MVP"""
        return {
            'message': 'Queues not used in MVP - sync jobs run synchronously'
        }

