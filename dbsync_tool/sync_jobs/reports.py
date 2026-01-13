"""
Reporting and analytics service
"""
from django.db.models import Count, Sum, Avg, Q, F
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog
import csv
import json
from django.http import HttpResponse


class ReportService:
    """Service for generating reports"""
    
    @staticmethod
    def generate_job_report(job, start_date=None, end_date=None):
        """
        Generate comprehensive report for a job
        
        Returns:
            dict: Report data including statistics, execution history, performance metrics
        """
        executions = SyncExecution.objects.filter(job=job)
        
        if start_date:
            executions = executions.filter(started_at__gte=start_date)
        if end_date:
            executions = executions.filter(started_at__lte=end_date)
        
        total_executions = executions.count()
        successful_executions = executions.filter(status='completed').count()
        failed_executions = executions.filter(status='failed').count()
        
        total_rows_synced = executions.aggregate(
            total=Sum('total_rows_synced')
        )['total'] or 0
        
        avg_duration = executions.filter(
            status='completed',
            completed_at__isnull=False
        ).annotate(
            duration=F('completed_at') - F('started_at')
        ).aggregate(
            avg_duration=Avg('duration')
        )['avg_duration']
        
        # Execution history
        execution_history = executions.order_by('-started_at')[:50]
        
        # Performance by table
        table_performance = SyncExecutionLog.objects.filter(
            execution__job=job,
            execution__in=executions
        ).values('schema_name', 'table_name').annotate(
            total_executions=Count('id'),
            total_rows=Sum('rows_inserted'),
            avg_rows_per_execution=Avg('rows_inserted'),
            failed_count=Count('id', filter=Q(status='failed')),
        ).order_by('-total_rows')
        
        return {
            'job': job,
            'period': {
                'start': start_date,
                'end': end_date,
            },
            'summary': {
                'total_executions': total_executions,
                'successful_executions': successful_executions,
                'failed_executions': failed_executions,
                'success_rate': round((successful_executions / total_executions * 100), 1) if total_executions > 0 else 0,
                'total_rows_synced': total_rows_synced,
                'avg_duration_seconds': avg_duration.total_seconds() if avg_duration else None,
            },
            'execution_history': execution_history,
            'table_performance': table_performance,
        }
    
    @staticmethod
    def generate_user_report(user, start_date=None, end_date=None):
        """
        Generate comprehensive report for all user's jobs
        
        Returns:
            dict: Report data
        """
        jobs = SyncJob.objects.filter(created_by=user)
        executions = SyncExecution.objects.filter(job__created_by=user)
        
        if start_date:
            executions = executions.filter(started_at__gte=start_date)
        if end_date:
            executions = executions.filter(started_at__lte=end_date)
        
        # Overall statistics
        total_jobs = jobs.count()
        total_executions = executions.count()
        successful_executions = executions.filter(status='completed').count()
        
        total_rows_synced = executions.aggregate(
            total=Sum('total_rows_synced')
        )['total'] or 0
        
        # Job-level statistics
        job_stats = []
        for job in jobs:
            job_executions = executions.filter(job=job)
            job_stats.append({
                'job': job,
                'execution_count': job_executions.count(),
                'success_count': job_executions.filter(status='completed').count(),
                'total_rows': job_executions.aggregate(
                    total=Sum('total_rows_synced')
                )['total'] or 0,
            })
        
        return {
            'user': user,
            'period': {
                'start': start_date,
                'end': end_date,
            },
            'summary': {
                'total_jobs': total_jobs,
                'total_executions': total_executions,
                'successful_executions': successful_executions,
                'success_rate': round((successful_executions / total_executions * 100), 1) if total_executions > 0 else 0,
                'total_rows_synced': total_rows_synced,
            },
            'job_statistics': job_stats,
        }
    
    @staticmethod
    def export_report_to_csv(report_data, filename='report.csv'):
        """Export report data to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        writer = csv.writer(response)
        
        # Write summary
        writer.writerow(['Report Summary'])
        if 'summary' in report_data:
            summary = report_data['summary']
            writer.writerow(['Metric', 'Value'])
            for key, value in summary.items():
                writer.writerow([key.replace('_', ' ').title(), value])
        
        writer.writerow([])
        
        # Write execution history if available
        if 'execution_history' in report_data:
            writer.writerow(['Execution History'])
            writer.writerow(['Started At', 'Status', 'Tables', 'Rows Synced', 'Duration'])
            for execution in report_data['execution_history']:
                duration = ''
                if execution.completed_at:
                    duration = str(execution.completed_at - execution.started_at)
                writer.writerow([
                    execution.started_at.strftime('%Y-%m-%d %H:%M:%S'),
                    execution.get_status_display(),
                    f"{execution.completed_tables}/{execution.total_tables}",
                    execution.total_rows_synced or 0,
                    duration
                ])
        
        return response
    
    @staticmethod
    def export_report_to_json(report_data, filename='report.json'):
        """Export report data to JSON"""
        # Convert model instances to dict
        json_data = {}
        
        if 'job' in report_data:
            json_data['job'] = {
                'id': str(report_data['job'].id),
                'name': report_data['job'].name,
                'sync_type': report_data['job'].sync_type,
                'status': report_data['job'].status,
            }
        
        if 'summary' in report_data:
            json_data['summary'] = report_data['summary']
        
        if 'execution_history' in report_data:
            json_data['execution_history'] = [
                {
                    'id': str(e.id),
                    'started_at': e.started_at.isoformat(),
                    'completed_at': e.completed_at.isoformat() if e.completed_at else None,
                    'status': e.status,
                    'total_tables': e.total_tables,
                    'completed_tables': e.completed_tables,
                    'total_rows_synced': e.total_rows_synced or 0,
                }
                for e in report_data['execution_history']
            ]
        
        response = HttpResponse(json.dumps(json_data, indent=2), content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

