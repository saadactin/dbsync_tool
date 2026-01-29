"""
Dashboard statistics and analytics services
"""
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q, F
from django.db.models.functions import TruncDate
from django.db import models
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog, HealthScoreSnapshot, AnomalyAlert, FreshnessMetric
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


class HealthScoreService:
    """
    Service for calculating and managing sync health scores
    """
    
    @staticmethod
    def calculate_score(user):
        """
        Calculate current health score for user's tenant
        
        Returns:
            dict: {
                'score': int (0-100),
                'components': {
                    'success_rate': int,
                    'connection_health': int,
                    'schedule_adherence': int,
                    'error_frequency': int
                }
            }
        """
        from accounts.services.tenant_service import TenantService
        
        # Get tenant for user
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            # Super admin - use user as tenant for calculation
            tenant = user
        
        # Get user's jobs and connections
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        
        all_connections = DatabaseConnection.objects.all()
        user_connections = TenantService.get_queryset_for_user(all_connections, user)
        
        # Calculate components
        success_rate = HealthScoreService._calculate_success_rate(user_jobs, user)
        connection_health = HealthScoreService._calculate_connection_health(user_connections)
        schedule_adherence = HealthScoreService._calculate_schedule_adherence(user_jobs, user)
        error_frequency = HealthScoreService._calculate_error_frequency(user_jobs, user)
        
        # Calculate weighted score
        score = round(
            success_rate * 0.40 +
            connection_health * 0.20 +
            schedule_adherence * 0.20 +
            error_frequency * 0.20
        )
        
        # Ensure score is between 0-100
        score = max(0, min(100, score))
        
        return {
            'score': score,
            'components': {
                'success_rate': success_rate,
                'connection_health': connection_health,
                'schedule_adherence': schedule_adherence,
                'error_frequency': error_frequency
            }
        }
    
    @staticmethod
    def _calculate_success_rate(jobs_queryset, user):
        """Calculate success rate component (0-100)"""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        last_30d = now - timedelta(days=30)
        
        executions = SyncExecution.objects.filter(
            job__in=jobs_queryset,
            started_at__gte=last_30d
        )
        
        total = executions.count()
        if total == 0:
            return 100  # No executions = perfect (no failures)
        
        successful = executions.filter(status='completed').count()
        rate = (successful / total) * 100
        return round(rate, 1)
    
    @staticmethod
    def _calculate_connection_health(connections_queryset):
        """Calculate connection health component (0-100)"""
        total = connections_queryset.count()
        if total == 0:
            return 0  # No connections = 0 health
        
        active = connections_queryset.filter(is_active=True).count()
        rate = (active / total) * 100
        return round(rate, 1)
    
    @staticmethod
    def _calculate_schedule_adherence(jobs_queryset, user):
        """Calculate schedule adherence component (0-100)"""
        from django.utils import timezone
        from datetime import timedelta
        
        scheduled_jobs = jobs_queryset.filter(
            schedule__is_enabled=True
        )
        
        total_scheduled = scheduled_jobs.count()
        if total_scheduled == 0:
            return 100  # No scheduled jobs = perfect adherence
        
        now = timezone.now()
        last_30d = now - timedelta(days=30)
        
        # Count jobs that ran on time (within 5 minutes of scheduled time)
        on_time_count = 0
        for job in scheduled_jobs:
            if job.next_run_at:
                # Check if job ran within 5 minutes of next_run_at
                executions = SyncExecution.objects.filter(
                    job=job,
                    started_at__gte=last_30d,
                    status='completed'
                ).order_by('-started_at')[:1]
                
                if executions.exists():
                    exec_time = executions.first().started_at
                    expected_time = job.next_run_at
                    if abs((exec_time - expected_time).total_seconds()) <= 300:  # 5 minutes
                        on_time_count += 1
        
        rate = (on_time_count / total_scheduled) * 100 if total_scheduled > 0 else 100
        return round(rate, 1)
    
    @staticmethod
    def _calculate_error_frequency(jobs_queryset, user):
        """Calculate error frequency component (0-100, higher = fewer errors)"""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        last_30d = now - timedelta(days=30)
        
        executions = SyncExecution.objects.filter(
            job__in=jobs_queryset,
            started_at__gte=last_30d
        )
        
        total = executions.count()
        if total == 0:
            return 100  # No executions = no errors
        
        failed = executions.filter(status='failed').count()
        error_rate = (failed / total) * 100
        
        # Inverse: lower error rate = higher score
        score = max(0, 100 - error_rate)
        return round(score, 1)
    
    @staticmethod
    def get_trend(user, days=7):
        """
        Get historical health scores for trend analysis
        
        Returns:
            list: [{'date': date, 'score': int}, ...]
        """
        from accounts.services.tenant_service import TenantService
        from django.utils import timezone
        from datetime import timedelta
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        now = timezone.now()
        start_date = now - timedelta(days=days)
        
        snapshots = HealthScoreSnapshot.objects.filter(
            tenant=tenant,
            calculated_at__gte=start_date
        ).order_by('calculated_at')
        
        # Group by date (one per day)
        trend_data = []
        seen_dates = set()
        
        for snapshot in snapshots:
            date_key = snapshot.calculated_at.date()
            if date_key not in seen_dates:
                trend_data.append({
                    'date': date_key.isoformat(),
                    'score': snapshot.score
                })
                seen_dates.add(date_key)
        
        return trend_data
    
    @staticmethod
    def get_trend_direction(user):
        """
        Determine if health score is improving, degrading, or stable
        
        Returns:
            str: 'improving', 'degrading', or 'stable'
        """
        trend = HealthScoreService.get_trend(user, days=7)
        
        if len(trend) < 2:
            return 'stable'
        
        # Compare latest with average of previous 3 days
        latest_score = trend[-1]['score']
        previous_scores = [t['score'] for t in trend[:-1][-3:]]
        
        if not previous_scores:
            return 'stable'
        
        avg_previous = sum(previous_scores) / len(previous_scores)
        
        if latest_score > avg_previous + 2:
            return 'improving'
        elif latest_score < avg_previous - 2:
            return 'degrading'
        else:
            return 'stable'
    
    @staticmethod
    def save_snapshot(user):
        """
        Save current score as snapshot (for historical tracking)
        Should be called daily via scheduled task
        """
        from accounts.services.tenant_service import TenantService
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        score_data = HealthScoreService.calculate_score(user)
        
        # Check if snapshot already exists for today
        from django.utils import timezone
        today = timezone.now().date()
        
        existing = HealthScoreSnapshot.objects.filter(
            tenant=tenant,
            calculated_at__date=today
        ).first()
        
        if existing:
            # Update existing snapshot
            existing.score = score_data['score']
            existing.components = score_data['components']
            existing.save()
        else:
            # Create new snapshot
            HealthScoreSnapshot.objects.create(
                tenant=tenant,
                score=score_data['score'],
                components=score_data['components']
            )


class AnomalyDetectionService:
    """
    Service for detecting anomalies in sync jobs
    """
    
    @staticmethod
    def detect_all_anomalies(user=None):
        """
        Detect anomalies for all jobs (or user's jobs if user provided)
        Called by background task
        
        Args:
            user: Optional user to filter jobs by tenant
        
        Returns:
            dict: {
                'detected': int,
                'updated': int,
                'resolved': int
            }
        """
        from accounts.services.tenant_service import TenantService
        import logging
        
        logger = logging.getLogger(__name__)
        
        detected_count = 0
        updated_count = 0
        resolved_count = 0
        
        # Get all jobs or user's jobs
        all_jobs = SyncJob.objects.all()
        if user:
            jobs = TenantService.get_queryset_for_user(all_jobs, user)
        else:
            # For background task, process all tenants
            jobs = all_jobs
        
        # Process each job
        for job in jobs.select_related('tenant'):
            try:
                tenant = TenantService.get_user_tenant(job.created_by) if job.created_by else None
                if tenant is None:
                    tenant = job.tenant if job.tenant else job.created_by
                
                if not tenant:
                    continue
                
                anomalies = AnomalyDetectionService.detect_job_anomalies(job, tenant)
                
                for anomaly_data in anomalies:
                    # Check if alert already exists for this job and type
                    existing = AnomalyAlert.objects.filter(
                        job=job,
                        anomaly_type=anomaly_data['type'],
                        is_acknowledged=False
                    ).first()
                    
                    if existing:
                        # Update existing alert
                        existing.severity = anomaly_data['severity']
                        existing.description = anomaly_data['description']
                        existing.detected_at = timezone.now()
                        existing.save()
                        updated_count += 1
                    else:
                        # Create new alert
                        AnomalyAlert.objects.create(
                            job=job,
                            tenant=tenant,
                            anomaly_type=anomaly_data['type'],
                            severity=anomaly_data['severity'],
                            description=anomaly_data['description']
                        )
                        detected_count += 1
                
                # Check for resolved anomalies (no longer detected)
                active_alerts = AnomalyAlert.objects.filter(
                    job=job,
                    is_acknowledged=False
                )
                
                detected_types = {a['type'] for a in anomalies}
                for alert in active_alerts:
                    if alert.anomaly_type not in detected_types:
                        # Anomaly resolved, but don't auto-acknowledge
                        # Just mark as resolved in stats
                        resolved_count += 1
                        
            except Exception as e:
                logger.error(f"Error detecting anomalies for job {job.id}: {str(e)}", exc_info=True)
                continue
        
        return {
            'detected': detected_count,
            'updated': updated_count,
            'resolved': resolved_count
        }
    
    @staticmethod
    def detect_job_anomalies(job, user):
        """
        Detect anomalies for a specific job
        
        Returns:
            list: List of detected anomaly dicts with keys: type, severity, description
        """
        anomalies = []
        
        # Detect each type of anomaly
        duration_anomaly = AnomalyDetectionService._detect_duration_anomaly(job)
        if duration_anomaly:
            anomalies.append(duration_anomaly)
        
        failure_anomaly = AnomalyDetectionService._detect_failure_pattern(job)
        if failure_anomaly:
            anomalies.append(failure_anomaly)
        
        row_count_anomaly = AnomalyDetectionService._detect_row_count_anomaly(job)
        if row_count_anomaly:
            anomalies.append(row_count_anomaly)
        
        timeout_anomaly = AnomalyDetectionService._detect_connection_timeout(job)
        if timeout_anomaly:
            anomalies.append(timeout_anomaly)
        
        return anomalies
    
    @staticmethod
    def _detect_duration_anomaly(job):
        """Detect if execution duration is anomalously high"""
        # Get last 10 completed executions
        executions = SyncExecution.objects.filter(
            job=job,
            status='completed',
            completed_at__isnull=False
        ).order_by('-started_at')[:10]
        
        if executions.count() < 3:
            # Need at least 3 executions for comparison
            return None
        
        # Calculate durations
        durations = []
        for exec in executions:
            if exec.completed_at and exec.started_at:
                duration = (exec.completed_at - exec.started_at).total_seconds()
                durations.append(duration)
        
        if len(durations) < 3:
            return None
        
        # Get average duration (excluding most recent)
        if len(durations) > 1:
            avg_duration = sum(durations[1:]) / (len(durations) - 1)
            latest_duration = durations[0]
        else:
            return None
        
        if avg_duration == 0:
            return None
        
        # Check if latest is > 2x average
        multiplier = latest_duration / avg_duration if avg_duration > 0 else 0
        
        if multiplier >= 2.0:
            severity = 'critical' if multiplier > 3.0 else 'warning'
            description = f"Execution duration increased by {multiplier:.1f}x (from {avg_duration:.1f}s to {latest_duration:.1f}s)"
            
            return {
                'type': 'duration_spike',
                'severity': severity,
                'description': description
            }
        
        return None
    
    @staticmethod
    def _detect_failure_pattern(job):
        """Detect failure patterns (consecutive failures or high failure rate)"""
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        
        # Get last 10 executions or last 24 hours, whichever is more
        recent_executions = SyncExecution.objects.filter(
            job=job,
            started_at__gte=last_24h
        ).order_by('-started_at')[:10]
        
        if recent_executions.count() < 3:
            return None
        
        # Count consecutive failures from most recent
        consecutive_failures = 0
        for exec in recent_executions:
            if exec.status == 'failed':
                consecutive_failures += 1
            else:
                break
        
        # Check for consecutive failures
        if consecutive_failures >= 3:
            return {
                'type': 'failure_pattern',
                'severity': 'critical',
                'description': f"{consecutive_failures} consecutive failures detected"
            }
        
        # Calculate failure rate
        total_count = recent_executions.count()
        failed_count = recent_executions.filter(status='failed').count()
        failure_rate = failed_count / total_count if total_count > 0 else 0
        
        if failure_rate > 0.5 and total_count >= 3:
            return {
                'type': 'failure_pattern',
                'severity': 'critical',
                'description': f"High failure rate: {failure_rate:.1%} ({failed_count}/{total_count} failures in last 24 hours)"
            }
        
        return None
    
    @staticmethod
    def _detect_row_count_anomaly(job):
        """Detect if row count dropped significantly"""
        # Get last 10 completed executions with row counts
        executions = SyncExecution.objects.filter(
            job=job,
            status='completed',
            total_rows_synced__gt=0
        ).order_by('-started_at')[:10]
        
        if executions.count() < 3:
            return None
        
        # Get row counts
        row_counts = [exec.total_rows_synced for exec in executions]
        
        if len(row_counts) < 3:
            return None
        
        # Calculate average (excluding most recent)
        if len(row_counts) > 1:
            avg_rows = sum(row_counts[1:]) / (len(row_counts) - 1)
            latest_rows = row_counts[0]
        else:
            return None
        
        if avg_rows == 0:
            return None
        
        # Check for drop
        drop_ratio = latest_rows / avg_rows if avg_rows > 0 else 1.0
        
        if drop_ratio < 0.5:
            # >50% drop - critical
            return {
                'type': 'row_count_drop',
                'severity': 'critical',
                'description': f"Row count dropped by {(1-drop_ratio)*100:.1f}% (from {avg_rows:,.0f} to {latest_rows:,.0f} rows)"
            }
        elif drop_ratio < 0.7:
            # 30-50% drop - warning
            return {
                'type': 'row_count_drop',
                'severity': 'warning',
                'description': f"Row count dropped by {(1-drop_ratio)*100:.1f}% (from {avg_rows:,.0f} to {latest_rows:,.0f} rows)"
            }
        
        return None
    
    @staticmethod
    def _detect_connection_timeout(job):
        """Detect connection timeout patterns"""
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        
        # Get last 24 hours of executions
        executions = SyncExecution.objects.filter(
            job=job,
            started_at__gte=last_24h
        )
        
        # Check for timeout errors in error messages
        timeout_keywords = ['timeout', 'timed out', 'connection timeout', 'read timeout', 'connection reset']
        timeout_count = 0
        
        for exec in executions:
            if exec.error_message:
                error_lower = exec.error_message.lower()
                if any(keyword in error_lower for keyword in timeout_keywords):
                    timeout_count += 1
        
        if timeout_count >= 3:
            return {
                'type': 'connection_timeout',
                'severity': 'critical',
                'description': f"{timeout_count} connection timeout errors detected in last 24 hours"
            }
        
        return None
    
    @staticmethod
    def get_active_anomalies(user):
        """
        Get active (unacknowledged) anomalies for user's tenant
        
        Returns:
            QuerySet: AnomalyAlert queryset
        """
        from accounts.services.tenant_service import TenantService
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        return AnomalyAlert.objects.filter(
            tenant=tenant,
            is_acknowledged=False
        ).select_related('job', 'tenant').order_by('-detected_at')
    
    @staticmethod
    def acknowledge_anomaly(anomaly_id, user):
        """
        Acknowledge an anomaly
        
        Returns:
            AnomalyAlert: Updated alert
        """
        from accounts.services.tenant_service import TenantService
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        try:
            alert = AnomalyAlert.objects.get(
                id=anomaly_id,
                tenant=tenant
            )
            
            alert.is_acknowledged = True
            alert.acknowledged_at = timezone.now()
            alert.acknowledged_by = user
            alert.save()
            
            return alert
        except AnomalyAlert.DoesNotExist:
            return None
    
    @staticmethod
    def get_anomaly_stats(user):
        """
        Get anomaly statistics for user's tenant
        
        Returns:
            dict: Statistics with total, critical, warning, acknowledged, unacknowledged
        """
        from accounts.services.tenant_service import TenantService
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        all_anomalies = AnomalyAlert.objects.filter(tenant=tenant)
        
        return {
            'total': all_anomalies.count(),
            'critical': all_anomalies.filter(severity='critical').count(),
            'warning': all_anomalies.filter(severity='warning').count(),
            'acknowledged': all_anomalies.filter(is_acknowledged=True).count(),
            'unacknowledged': all_anomalies.filter(is_acknowledged=False).count()
        }


class ConnectionGraphService:
    """
    Service for building connection relationship graph
    """
    
    @staticmethod
    def build_graph(user):
        """
        Build graph data structure from connections and jobs
        
        Returns:
            dict: {
                'nodes': list of node dicts,
                'edges': list of edge dicts
            }
        """
        from accounts.services.tenant_service import TenantService
        from sync_jobs.models import SyncJob, SyncExecution
        from connections.models import DatabaseConnection
        from django.db import models
        
        # Get tenant-filtered connections
        all_connections = DatabaseConnection.objects.filter(is_active=True)
        user_connections = TenantService.get_queryset_for_user(all_connections, user)
        
        # Get tenant-filtered jobs
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        
        # Build nodes
        nodes = []
        connection_map = {}  # id -> node index
        
        for idx, conn in enumerate(user_connections):
            # Count jobs using this connection (as source or target)
            job_count = user_jobs.filter(
                models.Q(source_connection=conn) | models.Q(target_connection=conn)
            ).count()
            
            node = {
                'id': str(conn.id),
                'name': conn.name,
                'type': conn.db_type,
                'job_count': job_count,
                'is_active': conn.is_active
            }
            nodes.append(node)
            connection_map[str(conn.id)] = idx
        
        # Build edges - group jobs by (source, target) pairs
        edges = []
        edge_map = {}  # (source_id, target_id) -> list of jobs
        
        # Group jobs by edge
        for job in user_jobs.select_related('source_connection', 'target_connection'):
            source_id = str(job.source_connection.id)
            target_id = str(job.target_connection.id)
            
            # Skip self-loops (if source == target)
            if source_id == target_id:
                continue
            
            edge_key = (source_id, target_id)
            
            if edge_key not in edge_map:
                edge_map[edge_key] = []
            
            edge_map[edge_key].append(job)
        
        # Build edges from grouped jobs
        for edge_key, edge_jobs_list in edge_map.items():
            source_id, target_id = edge_key
            
            # Calculate edge health
            edge_jobs_queryset = user_jobs.filter(
                source_connection_id=source_id,
                target_connection_id=target_id
            )
            health_data = ConnectionGraphService._calculate_edge_health(edge_jobs_queryset)
            
            # Build jobs list for edge
            jobs_list = []
            for edge_job in edge_jobs_list:
                jobs_list.append({
                    'id': str(edge_job.id),
                    'name': edge_job.name
                })
            
            edge = {
                'source': source_id,
                'target': target_id,
                'jobs': jobs_list,
                'job_count': len(jobs_list),
                'status': health_data['status'],
                'success_rate': health_data['success_rate']
            }
            edges.append(edge)
        
        return {
            'nodes': nodes,
            'edges': edges
        }
    
    @staticmethod
    def _calculate_edge_health(jobs_queryset):
        """
        Calculate health status for edge between two connections
        
        Args:
            jobs_queryset: QuerySet of jobs between source and target connections
        
        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'success_rate': float (0-100)
            }
        """
        from sync_jobs.models import SyncExecution
        from django.utils import timezone
        from datetime import timedelta
        
        if not jobs_queryset.exists():
            return {
                'status': 'healthy',
                'success_rate': 100.0
            }
        
        # Get last 50 executions for all jobs on this edge
        all_executions = SyncExecution.objects.filter(
            job__in=jobs_queryset
        ).order_by('-started_at')[:50]  # Get more to ensure we have enough data
        
        if not all_executions.exists():
            return {
                'status': 'healthy',
                'success_rate': 100.0
            }
        
        # Convert to list to avoid queryset slicing issues
        executions_list = list(all_executions)
        
        # Calculate success rate
        total_executions = len(executions_list)
        successful_executions = sum(1 for e in executions_list if e.status == 'completed')
        
        if total_executions == 0:
            success_rate = 100.0
        else:
            success_rate = (successful_executions / total_executions) * 100
        
        # Determine status
        if success_rate >= 80:
            status = 'healthy'
        elif success_rate >= 50:
            status = 'warning'
        else:
            status = 'critical'
        
        return {
            'status': status,
            'success_rate': round(success_rate, 1)
        }


class FreshnessMapService:
    """
    Service for calculating and managing data freshness metrics
    """
    
    @staticmethod
    def calculate_freshness(job, user):
        """
        Calculate freshness for a specific job
        
        Returns:
            dict: {
                'last_successful_sync': datetime or None,
                'freshness_minutes': int or None,
                'expected_freshness_minutes': int,
                'freshness_status': 'fresh' | 'stale' | 'critical' | 'never_run'
            }
        """
        from django.utils import timezone
        
        # Get expected interval
        expected_minutes = FreshnessMapService._get_expected_interval_minutes(job)
        
        # Get last successful execution
        last_execution = FreshnessMapService._get_last_successful_execution(job)
        
        if not last_execution or not last_execution.completed_at:
            return {
                'last_successful_sync': None,
                'freshness_minutes': None,
                'expected_freshness_minutes': expected_minutes,
                'freshness_status': 'never_run'
            }
        
        # Calculate freshness
        now = timezone.now()
        freshness_minutes = int((now - last_execution.completed_at).total_seconds() / 60)
        
        # Determine status
        if freshness_minutes < expected_minutes:
            status = 'fresh'
        elif freshness_minutes < (2 * expected_minutes):
            status = 'stale'
        else:
            status = 'critical'
        
        return {
            'last_successful_sync': last_execution.completed_at,
            'freshness_minutes': freshness_minutes,
            'expected_freshness_minutes': expected_minutes,
            'freshness_status': status
        }
    
    @staticmethod
    def _get_expected_interval_minutes(job):
        """
        Get expected freshness interval in minutes based on schedule
        
        Returns:
            int: Minutes (default 1440 = 24 hours)
        """
        # Check if job has a schedule
        if hasattr(job, 'schedule') and job.schedule:
            schedule = job.schedule
            if schedule.is_enabled:
                schedule_type = schedule.schedule_type
                # Map schedule types to minutes
                schedule_map = {
                    'hourly': 60,
                    'daily': 1440,
                    'weekly': 10080,
                    'monthly': 43200,  # ~30 days
                    'once': None,  # Manual, no expected interval
                }
                
                if schedule_type in schedule_map:
                    interval = schedule_map[schedule_type]
                    if interval:
                        return interval
                
                # TODO: Parse cron_expression if needed (future enhancement)
                # For now, default to daily
                return 1440
        
        # Default: 24 hours for jobs without schedules
        return 1440
    
    @staticmethod
    def _get_last_successful_execution(job):
        """
        Get last successful execution for job
        
        Returns:
            SyncExecution or None
        """
        from sync_jobs.models import SyncExecution
        
        return SyncExecution.objects.filter(
            job=job,
            status='completed'
        ).order_by('-completed_at').first()
    
    @staticmethod
    def update_freshness_metric(job, user):
        """
        Update or create freshness metric for a job
        Called after successful sync execution
        
        Args:
            job: SyncJob instance
            user: User instance (for tenant)
        """
        from accounts.services.tenant_service import TenantService
        from sync_jobs.models import FreshnessMetric
        
        # Get tenant
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        # Calculate freshness
        freshness_data = FreshnessMapService.calculate_freshness(job, user)
        
        # Update or create metric
        metric, created = FreshnessMetric.objects.get_or_create(
            job=job,
            defaults={
                'tenant': tenant,
                'last_successful_sync': freshness_data['last_successful_sync'],
                'freshness_minutes': freshness_data['freshness_minutes'] or 0,
                'expected_freshness_minutes': freshness_data['expected_freshness_minutes'],
                'freshness_status': freshness_data['freshness_status']
            }
        )
        
        if not created:
            # Update existing metric
            metric.last_successful_sync = freshness_data['last_successful_sync']
            metric.freshness_minutes = freshness_data['freshness_minutes'] or 0
            metric.expected_freshness_minutes = freshness_data['expected_freshness_minutes']
            metric.freshness_status = freshness_data['freshness_status']
            metric.save()
    
    @staticmethod
    def get_freshness_map(user, time_period='7d', status_filter=None):
        """
        Get freshness data for all jobs (for heatmap)
        
        Args:
            user: User instance
            time_period: '7d', '30d', or 'all' (for future historical data)
            status_filter: Optional filter by freshness status
        
        Returns:
            dict: {
                'jobs': [
                    {
                        'id': uuid,
                        'name': str,
                        'freshness_status': str,
                        'freshness_minutes': int,
                        'expected_freshness_minutes': int,
                        'last_successful_sync': datetime or None,
                    },
                    ...
                ],
                'summary': {
                    'total': int,
                    'fresh': int,
                    'stale': int,
                    'critical': int,
                    'never_run': int
                }
            }
        """
        from accounts.services.tenant_service import TenantService
        from sync_jobs.models import SyncJob
        
        # Get tenant-filtered jobs
        all_jobs = SyncJob.objects.all().select_related('schedule', 'tenant')
        user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
        
        # Calculate freshness for each job
        jobs_data = []
        summary = {
            'total': 0,
            'fresh': 0,
            'stale': 0,
            'critical': 0,
            'never_run': 0
        }
        
        for job in user_jobs:
            freshness_data = FreshnessMapService.calculate_freshness(job, user)
            
            # Apply status filter if provided
            if status_filter and freshness_data['freshness_status'] != status_filter:
                continue
            
            job_data = {
                'id': str(job.id),
                'name': job.name,
                'freshness_status': freshness_data['freshness_status'],
                'freshness_minutes': freshness_data['freshness_minutes'] if freshness_data['freshness_minutes'] is not None else 0,
                'expected_freshness_minutes': freshness_data['expected_freshness_minutes'],
                'last_successful_sync': freshness_data['last_successful_sync'].isoformat() if freshness_data['last_successful_sync'] else None,
            }
            
            jobs_data.append(job_data)
            summary['total'] += 1
            summary[freshness_data['freshness_status']] += 1
        
        return {
            'jobs': jobs_data,
            'summary': summary
        }


class RecommendationsEngine:
    """
    Service for generating actionable recommendations
    Analyzes data from Health Score, Anomaly Detection, Freshness Map, and job metrics
    """
    
    @staticmethod
    def generate_all_recommendations(user=None):
        """
        Generate recommendations for all jobs (or user's jobs if user provided)
        Called by background task
        
        Args:
            user: Optional user to filter jobs by tenant
        
        Returns:
            dict: {
                'generated': int,
                'updated': int,
                'dismissed_resolved': int
            }
        """
        from accounts.services.tenant_service import TenantService
        from sync_jobs.models import SyncJob, Recommendation
        
        generated = 0
        updated = 0
        dismissed_resolved = 0
        
        # Get tenant for user
        if user:
            tenant = TenantService.get_user_tenant(user)
            if tenant is None:
                tenant = user
            
            # Get user's jobs
            all_jobs = SyncJob.objects.all().select_related('schedule', 'source_connection', 'target_connection')
            user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
            
            # Generate recommendations for each job
            for job in user_jobs:
                recommendations = RecommendationsEngine.generate_job_recommendations(job, user)
                for rec_data in recommendations:
                    result = RecommendationsEngine._create_or_update_recommendation(
                        tenant=tenant,
                        category=rec_data['category'],
                        priority=rec_data['priority'],
                        title=rec_data['title'],
                        description=rec_data['description'],
                        action_url=rec_data.get('action_url'),
                        related_job=rec_data.get('related_job'),
                        related_connection=rec_data.get('related_connection'),
                        metadata=rec_data.get('metadata', {})
                    )
                    if result['created']:
                        generated += 1
                    elif result['updated']:
                        updated += 1
            
            # Generate health score recommendations
            health_recs = RecommendationsEngine._check_health_score_recommendations(user)
            for rec_data in health_recs:
                result = RecommendationsEngine._create_or_update_recommendation(
                    tenant=tenant,
                    category=rec_data['category'],
                    priority=rec_data['priority'],
                    title=rec_data['title'],
                    description=rec_data['description'],
                    action_url=rec_data.get('action_url'),
                    metadata=rec_data.get('metadata', {})
                )
                if result['created']:
                    generated += 1
                elif result['updated']:
                    updated += 1
            
            # Check for configuration recommendations (unused connections, etc.)
            config_recs = RecommendationsEngine._check_configuration_recommendations(user)
            for rec_data in config_recs:
                result = RecommendationsEngine._create_or_update_recommendation(
                    tenant=tenant,
                    category=rec_data['category'],
                    priority=rec_data['priority'],
                    title=rec_data['title'],
                    description=rec_data['description'],
                    action_url=rec_data.get('action_url'),
                    related_connection=rec_data.get('related_connection'),
                    metadata=rec_data.get('metadata', {})
                )
                if result['created']:
                    generated += 1
                elif result['updated']:
                    updated += 1
            
            # Auto-dismiss resolved recommendations
            active_recs = Recommendation.objects.filter(
                tenant=tenant,
                is_dismissed=False
            )
            for rec in active_recs:
                if RecommendationsEngine._is_recommendation_resolved(rec, user):
                    rec.is_dismissed = True
                    rec.save()
                    dismissed_resolved += 1
        
        return {
            'generated': generated,
            'updated': updated,
            'dismissed_resolved': dismissed_resolved
        }
    
    @staticmethod
    def generate_job_recommendations(job, user):
        """
        Generate recommendations for a specific job
        
        Returns:
            list: List of recommendation dicts
        """
        recommendations = []
        
        # Check performance recommendations
        perf_recs = RecommendationsEngine._check_performance_recommendations(job, user)
        recommendations.extend(perf_recs)
        
        # Check reliability recommendations
        rel_recs = RecommendationsEngine._check_reliability_recommendations(job, user)
        recommendations.extend(rel_recs)
        
        # Check schedule recommendations
        sched_recs = RecommendationsEngine._check_schedule_recommendations(job, user)
        recommendations.extend(sched_recs)
        
        return recommendations
    
    @staticmethod
    def _check_performance_recommendations(job, user):
        """Check for performance-related recommendations"""
        recommendations = []
        from sync_jobs.models import SyncExecution
        from django.utils import timezone
        from datetime import timedelta
        
        # Get last 10 completed executions
        executions = SyncExecution.objects.filter(
            job=job,
            status='completed',
            completed_at__isnull=False
        ).order_by('-completed_at')[:10]
        
        # Lower threshold: need at least 1 execution for basic analysis
        # Calculate average duration
        total_duration = 0
        total_count = 0
        total_rows = 0
        
        for exec in executions:
            if exec.completed_at and exec.started_at:
                duration = (exec.completed_at - exec.started_at).total_seconds() / 60  # minutes
                total_duration += duration
                total_count += 1
                if exec.total_rows_synced:
                    total_rows += exec.total_rows_synced
        
        if total_count > 0:
            avg_duration = total_duration / total_count
            avg_rows = total_rows / total_count if total_rows > 0 else 0
            
            # Check if incremental sync should be recommended (lowered threshold to 30 minutes)
            if avg_duration > 30 and job.sync_type != 'incremental':
                priority = 'high' if avg_duration > 120 else 'medium'
                recommendations.append({
                    'category': 'performance',
                    'priority': priority,
                    'title': 'Enable Incremental Sync for Long-Running Job',
                    'description': f"Job '{job.name}' averages {avg_duration:.1f} minutes per execution. Consider enabling incremental sync to reduce execution time significantly.",
                    'action_url': f'/sync-jobs/{job.id}/edit/',
                    'related_job': job,
                    'metadata': {
                        'avg_duration_minutes': round(avg_duration, 1),
                        'threshold': 60
                    }
                })
            
            # Check for batch size optimization
            if avg_rows > 1000000:  # 1M rows
                recommendations.append({
                    'category': 'performance',
                    'priority': 'medium',
                    'title': 'Optimize Batch Size for Large Data Volume',
                    'description': f"Job '{job.name}' syncs an average of {avg_rows:,.0f} rows per execution. Consider optimizing batch size for better performance.",
                    'action_url': f'/sync-jobs/{job.id}/edit/',
                    'related_job': job,
                    'metadata': {
                        'avg_rows': int(avg_rows),
                        'threshold': 1000000
                    }
                })
        
        # Check for duration spike anomalies
        from sync_jobs.models import AnomalyAlert
        duration_anomalies = AnomalyAlert.objects.filter(
            job=job,
            anomaly_type='duration_spike',
            is_acknowledged=False
        ).exists()
        
        if duration_anomalies:
            recommendations.append({
                'category': 'performance',
                'priority': 'high',
                'title': 'Optimize Query Performance',
                'description': f"Job '{job.name}' has detected duration spikes. Review and optimize query performance, check for missing indexes, or consider query transformations.",
                'action_url': f'/sync-jobs/{job.id}/edit/',
                'related_job': job,
                'metadata': {
                    'anomaly_type': 'duration_spike'
                }
            })
        
        return recommendations
    
    @staticmethod
    def _check_reliability_recommendations(job, user):
        """Check for reliability-related recommendations"""
        recommendations = []
        from sync_jobs.models import SyncExecution, AnomalyAlert
        from django.utils import timezone
        from datetime import timedelta
        
        # Get last 30 executions
        now = timezone.now()
        last_30d = now - timedelta(days=30)
        
        executions = SyncExecution.objects.filter(
            job=job,
            started_at__gte=last_30d
        )
        
        total = executions.count()
        # Lower threshold: need at least 1 execution for basic analysis
        if total < 1:
            return recommendations
        
        failed = executions.filter(status='failed').count()
        failure_rate = failed / total if total > 0 else 0
        
        # Check failure rate (lowered threshold to 5% for more sensitive detection)
        if failure_rate > 0.05:  # 5%
            priority = 'high' if failure_rate > 0.25 else 'medium'
            recommendations.append({
                'category': 'reliability',
                'priority': priority,
                'title': 'Review Connection/Query Settings',
                'description': f"Job '{job.name}' has a {failure_rate*100:.1f}% failure rate ({failed} of {total} executions). Review connection settings, query syntax, and error logs.",
                'action_url': f'/sync-jobs/{job.id}/edit/',
                'related_job': job,
                'metadata': {
                    'failure_rate': round(failure_rate, 3),
                    'failed_count': failed,
                    'total_count': total
                }
            })
        
        # Check for failure pattern anomalies
        failure_anomalies = AnomalyAlert.objects.filter(
            job=job,
            anomaly_type='failure_pattern',
            is_acknowledged=False
        ).exists()
        
        if failure_anomalies:
            recommendations.append({
                'category': 'reliability',
                'priority': 'high',
                'title': 'Investigate Root Cause of Failures',
                'description': f"Job '{job.name}' shows a failure pattern. Investigate the root cause by reviewing error messages, connection health, and recent changes.",
                'action_url': f'/sync-jobs/{job.id}/',
                'related_job': job,
                'metadata': {
                    'anomaly_type': 'failure_pattern'
                }
            })
        
        # Check for connection timeout anomalies
        timeout_anomalies = AnomalyAlert.objects.filter(
            job=job,
            anomaly_type='connection_timeout',
            is_acknowledged=False
        ).exists()
        
        if timeout_anomalies:
            recommendations.append({
                'category': 'reliability',
                'priority': 'high',
                'title': 'Optimize Network/Connection Settings',
                'description': f"Job '{job.name}' experiences connection timeouts. Check network connectivity, connection pool settings, and timeout configurations.",
                'action_url': f'/connections/{job.source_connection.id}/edit/' if job.source_connection else None,
                'related_job': job,
                'related_connection': job.source_connection,
                'metadata': {
                    'anomaly_type': 'connection_timeout'
                }
            })
        
        return recommendations
    
    @staticmethod
    def _check_schedule_recommendations(job, user):
        """Check for schedule-related recommendations"""
        recommendations = []
        from sync_jobs.models import SyncExecution
        
        # Check if schedule is enabled
        has_schedule = hasattr(job, 'schedule') and job.schedule and job.schedule.is_enabled
        
        # Check if job has ever run
        has_run = SyncExecution.objects.filter(job=job).exists()
        
        # If no schedule - recommend enabling it
        if not has_schedule:
            if not has_run:
                recommendations.append({
                    'category': 'schedule',
                    'priority': 'medium',
                    'title': 'Enable Schedule for Job',
                    'description': f"Job '{job.name}' has never been executed and has no schedule enabled. Enable a schedule to automate sync execution.",
                    'action_url': f'/sync-jobs/{job.id}/edit/',
                    'related_job': job,
                    'metadata': {}
                })
            else:
                recommendations.append({
                    'category': 'schedule',
                    'priority': 'low',
                    'title': 'Enable Schedule for Automated Execution',
                    'description': f"Job '{job.name}' has been run manually but has no schedule enabled. Enable a schedule to automate regular sync execution.",
                    'action_url': f'/sync-jobs/{job.id}/edit/',
                    'related_job': job,
                    'metadata': {}
                })
        
        # Check freshness status
        from sync_jobs.services import FreshnessMapService
        try:
            freshness_data = FreshnessMapService.calculate_freshness(job, user)
            freshness_status = freshness_data.get('freshness_status')
            
            if freshness_status == 'critical':
                recommendations.append({
                    'category': 'schedule',
                    'priority': 'high',
                    'title': 'Run Job Immediately',
                    'description': f"Job '{job.name}' has critical freshness status. Data is significantly stale. Run the job immediately to update data.",
                    'action_url': f'/sync-jobs/{job.id}/run/',
                    'related_job': job,
                    'metadata': {
                        'freshness_status': freshness_status,
                        'freshness_minutes': freshness_data.get('freshness_minutes')
                    }
                })
            elif freshness_status == 'stale':
                recommendations.append({
                    'category': 'schedule',
                    'priority': 'medium',
                    'title': 'Increase Schedule Frequency',
                    'description': f"Job '{job.name}' has stale data. Consider increasing the schedule frequency to maintain fresher data.",
                    'action_url': f'/sync-jobs/{job.id}/edit/',
                    'related_job': job,
                    'metadata': {
                        'freshness_status': freshness_status,
                        'freshness_minutes': freshness_data.get('freshness_minutes')
                    }
                })
        except Exception:
            pass  # Skip if freshness calculation fails
        
        return recommendations
    
    @staticmethod
    def _check_configuration_recommendations(job, user):
        """Check for configuration-related recommendations"""
        recommendations = []
        
        # This method is called for connections, not jobs
        # Check for unused connections
        from accounts.services.tenant_service import TenantService
        from connections.models import DatabaseConnection
        from sync_jobs.models import SyncJob
        
        all_connections = DatabaseConnection.objects.filter(is_active=True)
        user_connections = TenantService.get_queryset_for_user(all_connections, user)
        
        for conn in user_connections:
            # Check if connection has any jobs
            all_jobs = SyncJob.objects.all()
            user_jobs = TenantService.get_queryset_for_user(all_jobs, user)
            job_count = user_jobs.filter(
                models.Q(source_connection=conn) | models.Q(target_connection=conn)
            ).count()
            
            if job_count == 0:
                recommendations.append({
                    'category': 'configuration',
                    'priority': 'low',
                    'title': 'Clean Up Unused Connection',
                    'description': f"Connection '{conn.name}' has no active jobs. Consider removing if no longer needed.",
                    'action_url': f'/connections/{conn.id}/edit/',
                    'related_connection': conn,
                    'metadata': {
                        'job_count': 0
                    }
                })
        
        return recommendations
    
    @staticmethod
    def _check_health_score_recommendations(user):
        """Check for health score-based recommendations"""
        recommendations = []
        from sync_jobs.services import HealthScoreService
        
        try:
            score_data = HealthScoreService.calculate_score(user)
            trend_direction = HealthScoreService.get_trend_direction(user)
            score = score_data.get('score', 0)
            components = score_data.get('components', {})
            
            # Low health score
            if score < 50:
                recommendations.append({
                    'category': 'health',
                    'priority': 'high',
                    'title': 'Review System Health - Low Health Score',
                    'description': f"Your sync system health score is {score}/100, which is below the recommended threshold. Review all components (success rate: {components.get('success_rate', 0)}%, connections: {components.get('connection_health', 0)}%, schedule: {components.get('schedule_adherence', 0)}%, errors: {components.get('error_frequency', 0)}%).",
                    'action_url': '/sync-jobs/dashboard/',
                    'metadata': {
                        'health_score': score,
                        'components': components
                    }
                })
            
            # Degrading trend
            if trend_direction == 'degrading':
                recommendations.append({
                    'category': 'health',
                    'priority': 'medium',
                    'title': 'Investigate Degrading Health Trend',
                    'description': f"Your sync system health score is showing a degrading trend. Investigate recent changes, connection issues, or schedule problems.",
                    'action_url': '/sync-jobs/dashboard/',
                    'metadata': {
                        'trend': trend_direction,
                        'health_score': score
                    }
                })
            
            # Low connection health
            connection_health = components.get('connection_health', 100)
            if connection_health < 70:
                recommendations.append({
                    'category': 'health',
                    'priority': 'medium',
                    'title': 'Review Connection Health',
                    'description': f"Connection health is {connection_health}%. Review and update connection settings, test connections, and ensure all connections are active.",
                    'action_url': '/connections/',
                    'metadata': {
                        'connection_health': connection_health
                    }
                })
            
            # Low schedule adherence
            schedule_adherence = components.get('schedule_adherence', 100)
            if schedule_adherence < 70:
                recommendations.append({
                    'category': 'health',
                    'priority': 'medium',
                    'title': 'Review Schedule Adherence',
                    'description': f"Schedule adherence is {schedule_adherence}%. Review job schedules, ensure schedules are enabled, and check for conflicts.",
                    'action_url': '/sync-jobs/',
                    'metadata': {
                        'schedule_adherence': schedule_adherence
                    }
                })
        except Exception:
            pass  # Skip if health score calculation fails
        
        return recommendations
    
    @staticmethod
    def get_active_recommendations(user, category=None, priority=None):
        """
        Get active (non-dismissed) recommendations for user's tenant
        
        Returns:
            QuerySet: Recommendation queryset
        """
        from accounts.services.tenant_service import TenantService
        from sync_jobs.models import Recommendation
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        queryset = Recommendation.objects.filter(
            tenant=tenant,
            is_dismissed=False
        )
        
        if category:
            queryset = queryset.filter(category=category)
        
        if priority:
            queryset = queryset.filter(priority=priority)
        
        return queryset.order_by('-priority', '-created_at')
    
    @staticmethod
    def dismiss_recommendation(recommendation_id, user):
        """
        Dismiss a recommendation
        
        Returns:
            Recommendation: Updated recommendation or None if not found
        """
        from accounts.services.tenant_service import TenantService
        from sync_jobs.models import Recommendation
        from django.utils import timezone
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        try:
            recommendation = Recommendation.objects.get(
                id=recommendation_id,
                tenant=tenant
            )
            
            recommendation.is_dismissed = True
            recommendation.dismissed_at = timezone.now()
            recommendation.dismissed_by = user
            recommendation.save()
            
            return recommendation
        except Recommendation.DoesNotExist:
            return None
    
    @staticmethod
    def _create_or_update_recommendation(tenant, category, priority, title, description, 
                                        action_url=None, related_job=None, 
                                        related_connection=None, metadata=None):
        """
        Create or update a recommendation (avoid duplicates)
        
        Returns:
            dict: {'created': bool, 'updated': bool, 'recommendation': Recommendation}
        """
        from sync_jobs.models import Recommendation
        
        # Try to find existing recommendation with same characteristics
        existing = Recommendation.objects.filter(
            tenant=tenant,
            category=category,
            title=title,
            is_dismissed=False
        ).first()
        
        if existing:
            # Update existing recommendation
            existing.priority = priority
            existing.description = description
            if action_url:
                existing.action_url = action_url
            if related_job:
                existing.related_job = related_job
            if related_connection:
                existing.related_connection = related_connection
            if metadata:
                existing.metadata = metadata
            existing.save()
            return {'created': False, 'updated': True, 'recommendation': existing}
        else:
            # Create new recommendation
            recommendation = Recommendation.objects.create(
                tenant=tenant,
                category=category,
                priority=priority,
                title=title,
                description=description,
                action_url=action_url,
                related_job=related_job,
                related_connection=related_connection,
                metadata=metadata or {}
            )
            return {'created': True, 'updated': False, 'recommendation': recommendation}
    
    @staticmethod
    def _is_recommendation_resolved(recommendation, user):
        """
        Check if a recommendation is resolved (issue is fixed)
        
        Returns:
            bool: True if recommendation should be auto-dismissed
        """
        # For now, we'll keep recommendations until manually dismissed
        # In the future, we can add logic to check if the underlying issue is resolved
        return False
    
    @staticmethod
    def get_recommendation_stats(user):
        """
        Get recommendation statistics for user's tenant
        
        Returns:
            dict: Statistics about recommendations
        """
        from accounts.services.tenant_service import TenantService
        from sync_jobs.models import Recommendation
        
        tenant = TenantService.get_user_tenant(user)
        if tenant is None:
            tenant = user
        
        all_recs = Recommendation.objects.filter(tenant=tenant)
        
        return {
            'total': all_recs.filter(is_dismissed=False).count(),
            'high_priority': all_recs.filter(is_dismissed=False, priority='high').count(),
            'medium_priority': all_recs.filter(is_dismissed=False, priority='medium').count(),
            'low_priority': all_recs.filter(is_dismissed=False, priority='low').count(),
            'by_category': {
                'performance': all_recs.filter(is_dismissed=False, category='performance').count(),
                'reliability': all_recs.filter(is_dismissed=False, category='reliability').count(),
                'schedule': all_recs.filter(is_dismissed=False, category='schedule').count(),
                'configuration': all_recs.filter(is_dismissed=False, category='configuration').count(),
                'health': all_recs.filter(is_dismissed=False, category='health').count(),
            },
            'dismissed': all_recs.filter(is_dismissed=True).count()
        }