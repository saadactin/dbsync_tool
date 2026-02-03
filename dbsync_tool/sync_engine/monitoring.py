"""
Monitoring utilities for API sync job execution and state
"""
from typing import Dict, Optional, List
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Q
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog, APISyncState
import logging

logger = logging.getLogger(__name__)


class APISyncMonitor:
    """Monitor API sync job execution and state"""
    
    @staticmethod
    def get_job_metrics(job: SyncJob) -> Dict:
        """
        Get metrics for a sync job
        
        Args:
            job: SyncJob instance
            
        Returns:
            Dictionary with job metrics
        """
        try:
            # Get execution statistics
            executions = SyncExecution.objects.filter(job=job).order_by('-started_at')
            total_executions = executions.count()
            successful_executions = executions.filter(status='completed').count()
            failed_executions = executions.filter(status='failed').count()
            
            # Get total records synced
            total_records = APISyncState.objects.filter(job=job).aggregate(
                total=Sum('records_synced')
            )['total'] or 0
            
            # Get average execution time
            completed_executions = executions.filter(status='completed')
            avg_execution_time = None
            if completed_executions.exists():
                execution_times = []
                for exec in completed_executions:
                    if exec.started_at and exec.completed_at:
                        duration = (exec.completed_at - exec.started_at).total_seconds()
                        execution_times.append(duration)
                if execution_times:
                    avg_execution_time = sum(execution_times) / len(execution_times)
            
            # Get last execution info
            last_execution = executions.first()
            last_execution_time = None
            last_execution_status = None
            if last_execution:
                last_execution_time = last_execution.started_at
                last_execution_status = last_execution.status
            
            # Get module count
            module_count = APISyncState.objects.filter(job=job).count()
            
            # Calculate success rate
            success_rate = None
            if total_executions > 0:
                success_rate = (successful_executions / total_executions) * 100
            
            return {
                'job_id': str(job.id),
                'job_name': job.name,
                'total_executions': total_executions,
                'successful_executions': successful_executions,
                'failed_executions': failed_executions,
                'success_rate': success_rate,
                'total_records_synced': total_records,
                'module_count': module_count,
                'avg_execution_time_seconds': avg_execution_time,
                'last_execution_time': last_execution_time,
                'last_execution_status': last_execution_status,
            }
        except Exception as e:
            logger.error(f"Error getting job metrics for {job.id}: {str(e)}", exc_info=True)
            return {
                'job_id': str(job.id),
                'job_name': job.name,
                'error': str(e)
            }
    
    @staticmethod
    def get_module_metrics(job: SyncJob, module_name: str) -> Dict:
        """
        Get metrics for a specific module
        
        Args:
            job: SyncJob instance
            module_name: Module name
            
        Returns:
            Dictionary with module metrics
        """
        try:
            sync_state = APISyncState.get_for_module(job, module_name)
            
            if not sync_state:
                return {
                    'module_name': module_name,
                    'status': 'not_synced',
                    'message': 'Module has not been synced yet'
                }
            
            # Get data freshness
            data_freshness = sync_state.get_data_freshness()
            freshness_hours = None
            if data_freshness:
                freshness_hours = data_freshness.total_seconds() / 3600
            
            # Get execution logs for this module
            module_logs = SyncExecutionLog.objects.filter(
                execution__job=job,
                schema_name='api',
                table_name=module_name
            ).order_by('-started_at')
            
            total_runs = module_logs.count()
            successful_runs = module_logs.filter(status='completed').count()
            failed_runs = module_logs.filter(status='failed').count()
            
            # Get last run info
            last_log = module_logs.first()
            last_run_time = None
            last_run_status = None
            last_run_records = None
            if last_log:
                last_run_time = last_log.started_at
                last_run_status = last_log.status
                last_run_records = last_log.rows_inserted
            
            # Calculate success rate
            success_rate = None
            if total_runs > 0:
                success_rate = (successful_runs / total_runs) * 100
            
            return {
                'module_name': module_name,
                'status': 'synced',
                'last_sync_time': sync_state.last_sync_time,
                'last_modified_time': sync_state.last_modified_time,
                'records_synced': sync_state.records_synced,
                'data_freshness_hours': freshness_hours,
                'total_runs': total_runs,
                'successful_runs': successful_runs,
                'failed_runs': failed_runs,
                'success_rate': success_rate,
                'last_run_time': last_run_time,
                'last_run_status': last_run_status,
                'last_run_records': last_run_records,
            }
        except Exception as e:
            logger.error(f"Error getting module metrics for {job.id}/{module_name}: {str(e)}", exc_info=True)
            return {
                'module_name': module_name,
                'status': 'error',
                'error': str(e)
            }
    
    @staticmethod
    def get_health_status(job: SyncJob) -> str:
        """
        Get health status of sync job (healthy, warning, error)
        
        Args:
            job: SyncJob instance
            
        Returns:
            Health status string: 'healthy', 'warning', or 'error'
        """
        try:
            # Check if job is paused
            if job.status == 'paused':
                return 'warning'
            
            # Get recent executions
            recent_executions = SyncExecution.objects.filter(
                job=job,
                started_at__gte=timezone.now() - timedelta(days=7)
            )
            
            if not recent_executions.exists():
                return 'warning'  # No recent activity
            
            # Check failure rate
            failed_count = recent_executions.filter(status='failed').count()
            total_count = recent_executions.count()
            failure_rate = (failed_count / total_count) * 100 if total_count > 0 else 0
            
            if failure_rate > 50:
                return 'error'
            elif failure_rate > 20:
                return 'warning'
            
            # Check data freshness
            sync_states = APISyncState.objects.filter(job=job)
            if sync_states.exists():
                for state in sync_states:
                    freshness = state.get_data_freshness()
                    if freshness:
                        # If data is older than 7 days, it's a warning
                        if freshness > timedelta(days=7):
                            return 'warning'
                        # If data is older than 30 days, it's an error
                        if freshness > timedelta(days=30):
                            return 'error'
            
            return 'healthy'
        except Exception as e:
            logger.error(f"Error getting health status for {job.id}: {str(e)}", exc_info=True)
            return 'error'
    
    @staticmethod
    def get_all_jobs_summary() -> Dict:
        """
        Get summary metrics for all API sync jobs
        
        Returns:
            Dictionary with summary metrics
        """
        try:
            api_jobs = SyncJob.objects.filter(source_connection_type='api')
            
            total_jobs = api_jobs.count()
            total_modules = APISyncState.objects.filter(job__in=api_jobs).count()
            total_records = APISyncState.objects.filter(job__in=api_jobs).aggregate(
                total=Sum('records_synced')
            )['total'] or 0
            
            # Get health status counts
            healthy_count = 0
            warning_count = 0
            error_count = 0
            
            for job in api_jobs:
                health = APISyncMonitor.get_health_status(job)
                if health == 'healthy':
                    healthy_count += 1
                elif health == 'warning':
                    warning_count += 1
                else:
                    error_count += 1
            
            return {
                'total_jobs': total_jobs,
                'total_modules': total_modules,
                'total_records_synced': total_records,
                'healthy_jobs': healthy_count,
                'warning_jobs': warning_count,
                'error_jobs': error_count,
            }
        except Exception as e:
            logger.error(f"Error getting all jobs summary: {str(e)}", exc_info=True)
            return {
                'error': str(e)
            }
