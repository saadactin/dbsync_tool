"""
REST API views for sync jobs
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from sync_jobs.models import SyncJob, SyncExecution
from sync_jobs.serializers import (
    SyncJobSerializer,
    SyncExecutionSerializer,
    SyncJobCreateSerializer,
)
import logging

logger = logging.getLogger(__name__)


class SyncJobViewSet(viewsets.ModelViewSet):
    """
    ViewSet for SyncJob CRUD operations
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SyncJobSerializer
    
    def get_queryset(self):
        """Return jobs for authenticated user"""
        return SyncJob.objects.filter(created_by=self.request.user)
    
    def get_serializer_class(self):
        """Use different serializer for create"""
        if self.action == 'create':
            return SyncJobCreateSerializer
        return SyncJobSerializer
    
    def perform_create(self, serializer):
        """Set created_by to current user"""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def run_now(self, request, pk=None):
        """Trigger immediate execution of a job"""
        job = self.get_object()
        
        if job.status == 'running':
            return Response(
                {'error': 'Job is already running'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if job.status == 'paused':
            return Response(
                {'error': 'Cannot run a paused job'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from sync_engine.executor import SyncExecutor
            
            # Execute synchronously
            executor = SyncExecutor(job)
            executor.execute()
            
            # Refresh job to get latest status
            job.refresh_from_db()
            
            # Get latest execution
            from sync_jobs.models import SyncExecution
            latest_execution = SyncExecution.objects.filter(job=job).latest('started_at')
            
            return Response({
                'message': 'Job execution completed',
                'execution_id': str(latest_execution.id),
                'status': latest_execution.status,
                'rows_synced': latest_execution.total_rows_synced or 0,
            })
        except Exception as e:
            logger.error(f"Error executing job: {str(e)}", exc_info=True)
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pause a job"""
        job = self.get_object()
        
        if job.status == 'paused':
            return Response(
                {'error': 'Job is already paused'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if job.status == 'running':
            return Response(
                {'error': 'Cannot pause a running job'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        job.status = 'paused'
        job.save()
        
        # Disable schedule if exists
        if hasattr(job, 'schedule') and job.schedule:
            job.schedule.is_enabled = False
            job.schedule.save(update_fields=['is_enabled'])
        
        return Response({'message': 'Job paused'})
    
    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Resume a paused job"""
        job = self.get_object()
        
        if job.status != 'paused':
            return Response(
                {'error': 'Job is not paused'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        job.status = 'pending'
        job.save()
        
        # Re-enable schedule if exists
        from scheduler.utils import schedule_job_execution
        if hasattr(job, 'schedule') and job.schedule:
            job.schedule.is_enabled = True
            job.schedule.save(update_fields=['is_enabled'])
            try:
                schedule_job_execution(job)
            except Exception as e:
                logger.error(f"Error recalculating next_run_at on resume: {str(e)}", exc_info=True)
        
        return Response({'message': 'Job resumed'})
    
    @action(detail=True, methods=['get'])
    def executions(self, request, pk=None):
        """Get executions for a job"""
        job = self.get_object()
        executions = SyncExecution.objects.filter(job=job).order_by('-started_at')
        serializer = SyncExecutionSerializer(executions, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get user statistics"""
        from sync_jobs.services import DashboardService
        stats = DashboardService.get_user_statistics(request.user)
        return Response(stats)

