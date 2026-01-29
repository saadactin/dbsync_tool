"""
REST API views for sync jobs
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncExecution
from sync_jobs.serializers import (
    SyncJobSerializer,
    SyncExecutionSerializer,
    SyncJobCreateSerializer,
    AnomalyAlertSerializer,
    RecommendationSerializer,
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
    
    @action(detail=False, methods=['get'])
    def health_score(self, request):
        """
        Get current health score for user's tenant
        
        Returns:
            Response with health score data including trend
        """
        from sync_jobs.services import HealthScoreService
        
        try:
            score_data = HealthScoreService.calculate_score(request.user)
            trend_data = HealthScoreService.get_trend(request.user, days=7)
            trend_direction = HealthScoreService.get_trend_direction(request.user)
            
            response_data = {
                'score': score_data['score'],
                'components': score_data['components'],
                'trend': trend_direction,
                'trend_data': trend_data,
                'calculated_at': timezone.now().isoformat()
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error calculating health score: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to calculate health score'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def anomalies(self, request):
        """
        Get active anomalies for user's tenant
        
        Returns:
            Response with list of active anomalies
        """
        from sync_jobs.services import AnomalyDetectionService
        
        try:
            anomalies = AnomalyDetectionService.get_active_anomalies(request.user)
            serializer = AnomalyAlertSerializer(anomalies, many=True)
            
            return Response({
                'count': len(serializer.data),
                'results': serializer.data
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error retrieving anomalies: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to retrieve anomalies'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'], url_path='anomalies/stats')
    def anomaly_stats(self, request):
        """
        Get anomaly statistics for user's tenant
        
        Returns:
            Response with anomaly statistics
        """
        from sync_jobs.services import AnomalyDetectionService
        
        try:
            stats = AnomalyDetectionService.get_anomaly_stats(request.user)
            return Response(stats, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error retrieving anomaly stats: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to retrieve anomaly statistics'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'], url_path='anomalies/acknowledge')
    def acknowledge_anomaly(self, request):
        """
        Acknowledge an anomaly
        
        Returns:
            Response with updated anomaly
        """
        from sync_jobs.services import AnomalyDetectionService
        
        try:
            anomaly_id = request.data.get('anomaly_id') or request.query_params.get('anomaly_id')
            if not anomaly_id:
                return Response(
                    {'error': 'anomaly_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            alert = AnomalyDetectionService.acknowledge_anomaly(anomaly_id, request.user)
            
            if alert is None:
                return Response(
                    {'error': 'Anomaly not found or access denied'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            serializer = AnomalyAlertSerializer(alert)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error acknowledging anomaly: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to acknowledge anomaly'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'], url_path='connections/graph')
    def connection_graph(self, request):
        """
        Get connection relationship graph data
        
        Returns:
            Response with nodes and edges for graph visualization
        """
        from sync_jobs.services import ConnectionGraphService
        
        try:
            graph_data = ConnectionGraphService.build_graph(request.user)
            return Response(graph_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error building connection graph: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to build connection graph', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'], url_path='freshness-map')
    def freshness_map(self, request):
        """
        Get freshness map data for all jobs
        
        Query Parameters:
            time_period: '7d', '30d', or 'all' (default: '7d')
            status: Filter by freshness status ('fresh', 'stale', 'critical', 'never_run')
        
        Returns:
            Response with freshness data for all jobs
        """
        from sync_jobs.services import FreshnessMapService
        
        try:
            time_period = request.query_params.get('time_period', '7d')
            status_filter = request.query_params.get('status', None)
            
            freshness_data = FreshnessMapService.get_freshness_map(
                request.user,
                time_period=time_period,
                status_filter=status_filter
            )
            
            return Response(freshness_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error retrieving freshness map: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to retrieve freshness map', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def recommendations(self, request):
        """
        Get active recommendations for user's tenant
        
        Query Parameters:
            category: Filter by category ('performance', 'reliability', 'schedule', 'configuration', 'health')
            priority: Filter by priority ('high', 'medium', 'low')
            dismissed: Include dismissed recommendations ('true'/'false', default: 'false')
        
        Returns:
            Response with list of recommendations
        """
        from sync_jobs.services import RecommendationsEngine
        
        try:
            category = request.query_params.get('category', None)
            priority = request.query_params.get('priority', None)
            dismissed = request.query_params.get('dismissed', 'false').lower() == 'true'
            
            if dismissed:
                # Get all recommendations including dismissed
                from sync_jobs.models import Recommendation
                from accounts.services.tenant_service import TenantService
                
                tenant = TenantService.get_user_tenant(request.user)
                if tenant is None:
                    tenant = request.user
                
                queryset = Recommendation.objects.filter(tenant=tenant)
                
                if category:
                    queryset = queryset.filter(category=category)
                if priority:
                    queryset = queryset.filter(priority=priority)
                
                queryset = queryset.order_by('-priority', '-created_at')
            else:
                queryset = RecommendationsEngine.get_active_recommendations(
                    request.user,
                    category=category,
                    priority=priority
                )
            
            serializer = RecommendationSerializer(queryset, many=True)
            
            return Response({
                'count': len(serializer.data),
                'results': serializer.data
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error retrieving recommendations: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to retrieve recommendations', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'], url_path='recommendations/(?P<rec_id>[^/.]+)/dismiss')
    def dismiss_recommendation(self, request, rec_id=None):
        """
        Dismiss a recommendation
        
        Returns:
            Response with updated recommendation
        """
        from sync_jobs.services import RecommendationsEngine
        
        try:
            recommendation = RecommendationsEngine.dismiss_recommendation(rec_id, request.user)
            
            if recommendation is None:
                return Response(
                    {'error': 'Recommendation not found or access denied'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            serializer = RecommendationSerializer(recommendation)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error dismissing recommendation: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to dismiss recommendation', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'], url_path='recommendations/stats')
    def recommendation_stats(self, request):
        """
        Get recommendation statistics for user's tenant
        
        Returns:
            Response with recommendation statistics
        """
        from sync_jobs.services import RecommendationsEngine
        
        try:
            stats = RecommendationsEngine.get_recommendation_stats(request.user)
            return Response(stats, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error retrieving recommendation stats: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to retrieve recommendation statistics', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'], url_path='recommendations/refresh')
    def refresh_recommendations(self, request):
        """
        Manually trigger recommendation generation
        
        Returns:
            Response with generation results
        """
        from sync_jobs.services import RecommendationsEngine
        
        try:
            result = RecommendationsEngine.generate_all_recommendations(request.user)
            
            return Response({
                'status': 'success',
                'generated': result['generated'],
                'updated': result['updated'],
                'dismissed_resolved': result['dismissed_resolved']
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error generating recommendations: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to generate recommendations', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

