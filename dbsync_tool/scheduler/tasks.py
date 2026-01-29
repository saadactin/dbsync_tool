"""
Job execution functions (formerly Celery tasks)
Now executed directly via threading or scheduler service
"""
from django.utils import timezone
from sync_jobs.models import SyncExecution
from scheduler.utils import execute_sync_job_direct
import logging

logger = logging.getLogger(__name__)


def cleanup_old_executions():
    """
    Cleanup old execution records (older than 90 days)
    Can be called periodically by scheduler
    """
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=90)
    
    deleted_count = SyncExecution.objects.filter(
        started_at__lt=cutoff_date,
        status__in=['completed', 'failed']
    ).delete()[0]
    
    logger.info(f"Cleaned up {deleted_count} old execution records")
    return deleted_count


# Note: execute_sync_job is now execute_sync_job_direct in scheduler.utils
# trigger_scheduled_jobs_task is now handled by APScheduler in scheduler.service


def detect_anomalies_task():
    """
    Background task to detect anomalies in sync jobs
    Runs every 15 minutes via APScheduler
    """
    from sync_jobs.services import AnomalyDetectionService
    
    try:
        logger.info("Starting anomaly detection task")
        result = AnomalyDetectionService.detect_all_anomalies()
        logger.info(
            f"Anomaly detection completed: "
            f"detected={result['detected']}, "
            f"updated={result['updated']}, "
            f"resolved={result['resolved']}"
        )
        return result
    except Exception as e:
        logger.error(f"Error in anomaly detection task: {str(e)}", exc_info=True)
        return None


def generate_recommendations_task():
    """
    Background task to generate recommendations for all users
    Runs every hour via APScheduler
    """
    from sync_jobs.services import RecommendationsEngine
    from django.contrib.auth.models import User
    from accounts.services.tenant_service import TenantService
    
    try:
        logger.info("Starting recommendation generation task")
        
        # Get all admin users (tenants)
        admin_users = User.objects.filter(
            userprofile__role='admin'
        ).select_related('userprofile')
        
        total_generated = 0
        total_updated = 0
        total_dismissed = 0
        
        for user in admin_users:
            try:
                result = RecommendationsEngine.generate_all_recommendations(user)
                total_generated += result.get('generated', 0)
                total_updated += result.get('updated', 0)
                total_dismissed += result.get('dismissed_resolved', 0)
            except Exception as e:
                logger.error(f"Error generating recommendations for user {user.username}: {str(e)}", exc_info=True)
        
        logger.info(
            f"Recommendation generation completed: "
            f"generated={total_generated}, "
            f"updated={total_updated}, "
            f"dismissed_resolved={total_dismissed}"
        )
        
        return {
            'generated': total_generated,
            'updated': total_updated,
            'dismissed_resolved': total_dismissed
        }
    except Exception as e:
        logger.error(f"Error in recommendation generation task: {str(e)}", exc_info=True)
        return None