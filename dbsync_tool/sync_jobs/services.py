"""
Dashboard statistics and analytics services
"""
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q, F
from django.db.models.functions import TruncDate
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog
from connections.models import DatabaseConnection


class DashboardService:
    """Service for calculating dashboard statistics"""
    
    @staticmethod
    def get_user_statistics(user):
        """
        Get comprehensive statistics for a user
        
        Returns:
            dict: Statistics including jobs, executions, success rates, etc.
        """
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        
        # Basic counts
        total_jobs = user_jobs.count()
        running_jobs = user_jobs.filter(status='running').count()
        completed_jobs = user_jobs.filter(status='completed').count()
        failed_jobs = user_jobs.filter(status='failed').count()
        paused_jobs = user_jobs.filter(status='paused').count()
        pending_jobs = user_jobs.filter(status='pending').count()
        
        # Time-based statistics (last 24 hours, 7 days, 30 days)
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)
        
        # Executions in last 24 hours (filtered by tenant)
        executions_24h = SyncExecution.objects.filter(
            job__in=user_jobs,
            started_at__gte=last_24h
        )
        
        # Executions in last 7 days
        executions_7d = SyncExecution.objects.filter(
            job__in=user_jobs,
            started_at__gte=last_7d
        )
        
        # Executions in last 30 days
        executions_30d = SyncExecution.objects.filter(
            job__in=user_jobs,
            started_at__gte=last_30d
        )
        
        # Success rates
        success_rate_24h = DashboardService._calculate_success_rate(executions_24h)
        success_rate_7d = DashboardService._calculate_success_rate(executions_7d)
        success_rate_30d = DashboardService._calculate_success_rate(executions_30d)
        
        # Total rows synced
        total_rows_24h = executions_24h.aggregate(
            total=Sum('total_rows_synced')
        )['total'] or 0
        
        total_rows_7d = executions_7d.aggregate(
            total=Sum('total_rows_synced')
        )['total'] or 0
        
        total_rows_30d = executions_30d.aggregate(
            total=Sum('total_rows_synced')
        )['total'] or 0
        
        # Average execution duration
        avg_duration_30d = executions_30d.filter(
            status='completed',
            completed_at__isnull=False
        ).annotate(
            duration=F('completed_at') - F('started_at')
        ).aggregate(
            avg_duration=Avg('duration')
        )['avg_duration']
        
        # Failed executions in last 24h
        failed_24h = executions_24h.filter(status='failed').count()
        
        # Failed executions in last 30d (for Success Rate chart)
        failed_30d = executions_30d.filter(status='failed').count()
        successful_30d = executions_30d.filter(status='completed').count()
        
        # Scheduled jobs count
        scheduled_jobs = user_jobs.filter(
            schedule__is_enabled=True
        ).count()
        
        # Connections count (filtered by tenant)
        from accounts.services.tenant_service import TenantService
        all_connections = DatabaseConnection.objects.all()
        user_connections = TenantService.get_queryset_for_user(all_connections, user)
        total_connections = user_connections.count()
        
        return {
            'jobs': {
                'total': total_jobs,
                'running': running_jobs,
                'completed': completed_jobs,
                'failed': failed_jobs,
                'paused': paused_jobs,
                'pending': pending_jobs,
                'scheduled': scheduled_jobs,
            },
            'executions': {
                'last_24h': executions_24h.count(),
                'last_7d': executions_7d.count(),
                'last_30d': executions_30d.count(),
                'failed_24h': failed_24h,
                'failed_30d': failed_30d,
                'successful_30d': successful_30d,
            },
            'success_rates': {
                'last_24h': success_rate_24h,
                'last_7d': success_rate_7d,
                'last_30d': success_rate_30d,
            },
            'rows_synced': {
                'last_24h': total_rows_24h,
                'last_7d': total_rows_7d,
                'last_30d': total_rows_30d,
            },
            'performance': {
                'avg_duration_30d': avg_duration_30d.total_seconds() if avg_duration_30d else None,
            },
            'connections': {
                'total': total_connections,
            },
        }
    
    @staticmethod
    def _calculate_success_rate(executions):
        """Calculate success rate for executions"""
        total = executions.count()
        if total == 0:
            return 0.0
        successful = executions.filter(status='completed').count()
        return round((successful / total) * 100, 1)
    
    @staticmethod
    def get_execution_trends(user, days=30):
        """
        Get execution trends over time
        
        Returns:
            list: Daily execution counts and success rates
        """
        now = timezone.now()
        start_date = now - timedelta(days=days)
        
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        
        # Use TruncDate for database-agnostic date extraction
        executions = SyncExecution.objects.filter(
            job__in=user_jobs,
            started_at__gte=start_date
        ).annotate(
            day=TruncDate('started_at')
        ).values('day').annotate(
            total=Count('id'),
            successful=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed')),
            rows_synced=Sum('total_rows_synced')
        ).order_by('day')
        
        # Convert to list and ensure dates are properly formatted
        trends = []
        for trend in executions:
            day = trend['day']
            if day:
                # Ensure day is a date object
                if isinstance(day, str):
                    from datetime import datetime
                    day = datetime.strptime(day, '%Y-%m-%d').date()
                trends.append({
                    'day': day,
                    'total': trend.get('total', 0) or 0,
                    'successful': trend.get('successful', 0) or 0,
                    'failed': trend.get('failed', 0) or 0,
                    'rows_synced': trend.get('rows_synced', 0) or 0
                })
        
        return trends
    
    @staticmethod
    def get_top_jobs_by_rows(user, limit=10):
        """Get top jobs by rows synced"""
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        jobs = user_jobs.annotate(
            total_rows=Sum('executions__total_rows_synced')
        ).order_by('-total_rows')[:limit]
        
        return jobs
    
    @staticmethod
    def get_recent_activity(user, limit=20):
        """Get recent activity across all jobs"""
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        executions = SyncExecution.objects.filter(
            job__in=user_jobs
        ).select_related('job').order_by('-started_at')[:limit]
        
        return executions

