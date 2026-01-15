"""
REST API views for sync jobs
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError, PermissionDenied
from sync_jobs.models import SyncJob, SyncExecution
from sync_jobs.serializers import (
    SyncJobSerializer,
    SyncExecutionSerializer,
    SyncJobCreateSerializer,
)
from core.exceptions import BusinessLogicException, DatabaseException
from core.error_responses import error_response_from_exception, ErrorCode, create_error_response
from core.error_handler import ErrorHandler
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
        trace_id = ErrorHandler.get_trace_id(request)
        
        try:
            job = self.get_object()
        except Exception as e:
            return error_response_from_exception(
                e,
                trace_id=trace_id
            )
        
        # State validation
        if job.status == 'running':
            return create_error_response(
                code=ErrorCode.INVALID_STATE,
                message="Job is already running. Please wait for the current execution to complete.",
                trace_id=trace_id,
                status_code=400
            )
        
        if job.status == 'paused':
            return create_error_response(
                code=ErrorCode.INVALID_STATE,
                message="Cannot run a paused job. Please resume the job first.",
                trace_id=trace_id,
                status_code=400
            )
        
        # Connection validation
        if not job.source_connection.is_active or not job.target_connection.is_active:
            return create_error_response(
                code=ErrorCode.DEPENDENCY_ERROR,
                message="Source or target connection is inactive. Please activate the connections first.",
                trace_id=trace_id,
                status_code=400
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
                'success': True,
                'message': 'Job execution completed',
                'data': {
                    'execution_id': str(latest_execution.id),
                    'status': latest_execution.status,
                    'rows_synced': latest_execution.total_rows_synced or 0,
                }
            })
        except DatabaseException as e:
            ErrorHandler.log_error(request, e, trace_id)
            return error_response_from_exception(
                e,
                trace_id=trace_id
            )
        except Exception as e:
            ErrorHandler.log_error(request, e, trace_id)
            return error_response_from_exception(
                e,
                trace_id=trace_id
            )
    
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pause a job"""
        trace_id = ErrorHandler.get_trace_id(request)
        
        try:
            job = self.get_object()
        except Exception as e:
            return error_response_from_exception(
                e,
                trace_id=trace_id
            )
        
        # State validation
        if job.status == 'paused':
            return create_error_response(
                code=ErrorCode.INVALID_STATE,
                message="Job is already paused.",
                trace_id=trace_id,
                status_code=400
            )
        
        if job.status == 'running':
            return create_error_response(
                code=ErrorCode.INVALID_STATE,
                message="Cannot pause a running job. Please wait for the current execution to complete.",
                trace_id=trace_id,
                status_code=400
            )
        
        try:
            job.status = 'paused'
            job.save()
            
            # Disable schedule if exists
            if hasattr(job, 'schedule') and job.schedule:
                job.schedule.is_enabled = False
                job.schedule.save(update_fields=['is_enabled'])
            
            return Response({
                'success': True,
                'message': 'Job paused'
            })
        except Exception as e:
            ErrorHandler.log_error(request, e, trace_id)
            return error_response_from_exception(
                e,
                trace_id=trace_id
            )
    
    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Resume a paused job"""
        trace_id = ErrorHandler.get_trace_id(request)
        
        try:
            job = self.get_object()
        except Exception as e:
            return error_response_from_exception(
                e,
                trace_id=trace_id
            )
        
        # State validation
        if job.status != 'paused':
            return create_error_response(
                code=ErrorCode.INVALID_STATE,
                message="Job is not paused. Only paused jobs can be resumed.",
                trace_id=trace_id,
                status_code=400
            )
        
        try:
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
            
            return Response({
                'success': True,
                'message': 'Job resumed'
            })
        except Exception as e:
            ErrorHandler.log_error(request, e, trace_id)
            return error_response_from_exception(
                e,
                trace_id=trace_id
            )
    
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

