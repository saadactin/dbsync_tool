"""
Dashboard statistics and analytics services
"""
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q, F
from django.db.models.functions import TruncDate
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog
from connections.models import DatabaseConnection, APIConnection


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
        
        # API connection statistics
        all_api_connections = APIConnection.objects.all()
        user_api_connections = TenantService.get_queryset_for_user(all_api_connections, user)
        
        api_connections_stats = {
            'total': user_api_connections.count(),
            'active': user_api_connections.filter(is_active=True).count(),
            'inactive': user_api_connections.filter(is_active=False).count(),
            'by_type': list(user_api_connections.values('api_type').annotate(count=Count('id'))),
            'zoho': user_api_connections.filter(api_type='zoho_crm').count(),
            'sap': user_api_connections.filter(api_type='sap_b1').count(),
        }
        
        # API sync job statistics
        api_source_jobs = user_jobs.filter(source_connection_type='api')
        api_jobs_stats = {
            'total': api_source_jobs.count(),
            'running': api_source_jobs.filter(status='running').count(),
            'completed': api_source_jobs.filter(status='completed').count(),
            'failed': api_source_jobs.filter(status='failed').count(),
            'paused': api_source_jobs.filter(status='paused').count(),
            'pending': api_source_jobs.filter(status='pending').count(),
        }
        
        # API vs Database source breakdown
        database_source_jobs = user_jobs.filter(source_connection_type='database')
        source_breakdown = {
            'api': api_source_jobs.count(),
            'database': database_source_jobs.count(),
        }

        # Database usage (which source DBs are used most and how many tables synced)
        db_type_labels = {
            'postgres': 'PostgreSQL',
            'mysql': 'MySQL',
            'sqlserver': 'SQL Server',
            'clickhouse': 'ClickHouse',
            'oracle_adw': 'Oracle ADW',
            'mongodb': 'MongoDB',
        }
        db_logs_30d = SyncExecutionLog.objects.filter(
            execution__job__in=database_source_jobs,
            execution__started_at__gte=last_30d,
            status='completed',
        )
        db_usage_rows = db_logs_30d.values(
            'execution__job__source_connection__db_type'
        ).annotate(
            jobs_count=Count('execution__job', distinct=True),
            tables_synced=Count('table_name', distinct=True),
            runs_count=Count('id'),
            rows_synced=Sum('rows_inserted'),
        ).order_by('-tables_synced', '-runs_count')
        database_usage = []
        for row in db_usage_rows:
            db_type = row.get('execution__job__source_connection__db_type') or 'unknown'
            database_usage.append({
                'db_type': db_type,
                'label': db_type_labels.get(db_type, db_type.replace('_', ' ').title()),
                'jobs_count': row.get('jobs_count', 0) or 0,
                'tables_synced': row.get('tables_synced', 0) or 0,
                'runs_count': row.get('runs_count', 0) or 0,
                'rows_synced': row.get('rows_synced', 0) or 0,
            })
        
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
            'api_connections': api_connections_stats,
            'api_jobs': api_jobs_stats,
            'source_breakdown': source_breakdown,
            'database_usage': database_usage,
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
        Get execution trends over time - returns data for ALL days (including days with 0 executions)

        Returns:
            list: Daily execution counts and success rates for all 30 days
        """
        now = timezone.now()
        start_date = now - timedelta(days=days)

        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)

        # Get all executions and manually group by local date
        # This avoids database timezone issues with TruncDate
        executions_list = SyncExecution.objects.filter(
            job__in=user_jobs,
            started_at__gte=start_date
        ).select_related('job').order_by('started_at')

        # Manually group executions by local date
        execution_data = {}
        for execution in executions_list:
            # Convert UTC to local timezone and extract date
            local_time = timezone.localtime(execution.started_at)
            day = local_time.date()

            # Initialize day if not exists
            if day not in execution_data:
                execution_data[day] = {
                    'total': 0,
                    'successful': 0,
                    'failed': 0,
                    'rows_synced': 0
                }

            # Count execution
            execution_data[day]['total'] += 1
            if execution.status == 'completed':
                execution_data[day]['successful'] += 1
            elif execution.status == 'failed':
                execution_data[day]['failed'] += 1

            # Add rows synced
            execution_data[day]['rows_synced'] += (execution.total_rows_synced or 0)

        # Generate all days in the range (including days with no executions)
        trends = []
        current_date = start_date.date()
        end_date = now.date()

        while current_date <= end_date:
            if current_date in execution_data:
                # Day has execution data
                trends.append({
                    'day': current_date,
                    'total': execution_data[current_date]['total'],
                    'successful': execution_data[current_date]['successful'],
                    'failed': execution_data[current_date]['failed'],
                    'rows_synced': execution_data[current_date]['rows_synced']
                })
            else:
                # Day has no executions - add zeros
                trends.append({
                    'day': current_date,
                    'total': 0,
                    'successful': 0,
                    'failed': 0,
                    'rows_synced': 0
                })
            current_date += timedelta(days=1)

        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Execution trends: {len(trends)} days from {start_date.date()} to {end_date}")
        logger.info(f"Days with data: {len(execution_data)}")
        if execution_data:
            logger.info(f"Sample dates with executions: {list(execution_data.keys())[:5]}")
        total_execs = sum(t['total'] for t in trends)
        logger.info(f"Total executions in range: {total_execs}")

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
    
    @staticmethod
    def get_api_connection_statistics(user):
        """
        Get API connection statistics for a user
        
        Returns:
            dict: API connection statistics
        """
        from accounts.services.tenant_service import TenantService
        all_api_connections = APIConnection.objects.all()
        user_api_connections = TenantService.get_queryset_for_user(all_api_connections, user)
        
        return {
            'total': user_api_connections.count(),
            'active': user_api_connections.filter(is_active=True).count(),
            'inactive': user_api_connections.filter(is_active=False).count(),
            'by_type': list(user_api_connections.values('api_type').annotate(count=Count('id'))),
        }
    
    @staticmethod
    def get_api_sync_job_statistics(user):
        """
        Get API sync job statistics for a user
        
        Returns:
            dict: API sync job statistics
        """
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        api_source_jobs = user_jobs.filter(source_connection_type='api')
        
        # Get execution statistics for API jobs
        api_executions = SyncExecution.objects.filter(job__in=api_source_jobs)
        
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)
        
        api_executions_24h = api_executions.filter(started_at__gte=last_24h)
        api_executions_7d = api_executions.filter(started_at__gte=last_7d)
        api_executions_30d = api_executions.filter(started_at__gte=last_30d)
        
        return {
            'total': api_source_jobs.count(),
            'running': api_source_jobs.filter(status='running').count(),
            'completed': api_source_jobs.filter(status='completed').count(),
            'failed': api_source_jobs.filter(status='failed').count(),
            'paused': api_source_jobs.filter(status='paused').count(),
            'pending': api_source_jobs.filter(status='pending').count(),
            'executions': {
                'last_24h': api_executions_24h.count(),
                'last_7d': api_executions_7d.count(),
                'last_30d': api_executions_30d.count(),
            },
            'success_rate': DashboardService._calculate_success_rate(api_executions_30d),
            'rows_synced': {
                'last_24h': api_executions_24h.aggregate(total=Sum('total_rows_synced'))['total'] or 0,
                'last_7d': api_executions_7d.aggregate(total=Sum('total_rows_synced'))['total'] or 0,
                'last_30d': api_executions_30d.aggregate(total=Sum('total_rows_synced'))['total'] or 0,
            },
        }
    
    @staticmethod
    def get_api_vs_database_breakdown(user):
        """
        Get breakdown of API vs Database source jobs
        
        Returns:
            dict: Source type breakdown
        """
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        
        api_jobs = user_jobs.filter(source_connection_type='api')
        database_jobs = user_jobs.filter(source_connection_type='database')
        
        # Get execution counts
        api_executions = SyncExecution.objects.filter(job__in=api_jobs)
        database_executions = SyncExecution.objects.filter(job__in=database_jobs)
        
        return {
            'jobs': {
                'api': api_jobs.count(),
                'database': database_jobs.count(),
            },
            'executions': {
                'api': api_executions.count(),
                'database': database_executions.count(),
            },
            'rows_synced': {
                'api': api_executions.aggregate(total=Sum('total_rows_synced'))['total'] or 0,
                'database': database_executions.aggregate(total=Sum('total_rows_synced'))['total'] or 0,
            },
        }

