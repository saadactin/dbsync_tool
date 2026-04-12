"""
Views for sync jobs
"""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, DatabaseError
from functools import wraps
from datetime import datetime, timedelta
from django.utils import timezone
from connections.models import DatabaseConnection, APIConnection, FileSourceConnection
from metadata.services import load_all_metadata, load_table_columns
from .models import SyncJob, SyncJobTable, SyncSchedule, SyncCheckpoint, SyncExecution, SyncExecutionLog

logger = logging.getLogger(__name__)


def _normalize_job_source_db_type(conn: Optional[DatabaseConnection]) -> str:
    if not conn:
        return ""
    dbt = (getattr(conn, "db_type", "") or "").lower()
    if dbt == "oracle_adw":
        return "oracle"
    return dbt


def _wizard_table_key(table_info: Dict) -> str:
    return f"{table_info['schema_name']}.{table_info['table_name']}"


def _load_columns_for_mapping_step(
    request,
    *,
    source_connection: Optional[DatabaseConnection],
    source_connection_type: str,
    table_info: Dict,
    user,
) -> List[Dict]:
    """Database columns from metadata or synthetic outputs from transform plan."""
    if source_connection_type != "database" or not source_connection:
        return []
    table_key = _wizard_table_key(table_info)
    plans = request.session.get("sync_job_transform_plan") or {}
    plan = plans.get(table_key)
    if isinstance(plan, dict):
        from sync_jobs.services.transform_plan_service import mapping_columns_from_plan

        synthetic = mapping_columns_from_plan(plan)
        if synthetic is not None:
            return synthetic
    return load_table_columns(
        str(source_connection.id),
        table_info["schema_name"],
        table_info["table_name"],
        user,
    )


def viewer_read_only_required(view_func):
    """
    Decorator to prevent Viewer from accessing write operations
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            try:
                profile = request.user.userprofile
                if profile.is_viewer() and request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
                    logger.warning(
                        'Viewer attempted write operation',
                        extra={
                            'event_type': 'viewer_write_blocked',
                            'user_id': request.user.id,
                            'username': request.user.username,
                            'method': request.method,
                            'path': request.path,
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    raise PermissionDenied("Viewers have read-only access. This operation is not allowed.")
            except AttributeError:
                pass  # UserProfile doesn't exist, let other decorators handle it
        
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
def dashboard(request):
    """
    Enhanced dashboard with comprehensive statistics
    Role-based dashboard display
    """
    from sync_jobs.services import DashboardService
    from accounts.models import UserProfile
    
    try:
        # Get user profile for role information
        profile = request.user.userprofile
        
        # Get comprehensive statistics
        stats = DashboardService.get_user_statistics(request.user)
        
        # Get execution trends (last 30 days)
        trends = DashboardService.get_execution_trends(request.user, days=30)
        
        # Get recent activity (last 5 jobs only)
        recent_activity = DashboardService.get_recent_activity(request.user, limit=5)
        
        # Serialize trends data to JSON for JavaScript
        import json
        from django.utils.dateformat import format
        trends_json = json.dumps([
            {
                'day': trend['day'].strftime('%Y-%m-%d') if hasattr(trend['day'], 'strftime') else str(trend['day']),
                'total': trend.get('total', 0),
                'successful': trend.get('successful', 0),
                'failed': trend.get('failed', 0),
                'rows_synced': trend.get('rows_synced', 0) or 0
            }
            for trend in trends
        ])
        
        context = {
            'page_title': 'Dashboard',
            'stats': stats,
            'trends': trends,
            'trends_json': trends_json,  # JSON serialized for JavaScript
            'recent_activity': recent_activity,
            'user_role': profile.role,  # For template display
            'is_super_admin': profile.is_super_admin(),
            'is_admin': profile.is_admin(),
        }
        
        return render(request, 'sync_jobs/dashboard.html', context)
    except Exception as e:
        logger.error(f"Error loading dashboard: {str(e)}", exc_info=True)
        messages.error(request, 'Error loading dashboard. Please try again.')
        return redirect('sync_jobs:list')


@login_required
def job_list(request):
    """
    Enhanced list view with filtering, sorting, and search
    """
    try:
        from accounts.services.tenant_service import TenantService
        # Get jobs with proper relationships
        jobs = SyncJob.objects.all().select_related(
            'source_connection', 'source_api_connection', 'target_connection', 'schedule', 'tenant'
        ).prefetch_related('tables')
        jobs = TenantService.get_queryset_for_user(jobs, request.user)
        
        # Filter by source type (database, api, zoho_crm, sap_b1, azure_devops)
        source_type_filter = request.GET.get('source_type', '')
        if source_type_filter == 'database':
            jobs = jobs.filter(source_connection_type='database')
        elif source_type_filter == 'api':
            jobs = jobs.filter(source_connection_type='api')
        elif source_type_filter == 'zoho_crm':
            jobs = jobs.filter(source_connection_type='api', source_api_connection__api_type='zoho_crm')
        elif source_type_filter == 'sap_b1':
            jobs = jobs.filter(source_connection_type='api', source_api_connection__api_type='sap_b1')
        elif source_type_filter == 'azure_devops':
            jobs = jobs.filter(source_connection_type='api', source_api_connection__api_type='azure_devops')
        
        # Filter by status
        status_filter = request.GET.get('status', '')
        if status_filter and status_filter in ['pending', 'running', 'completed', 'failed', 'paused']:
            jobs = jobs.filter(status=status_filter)
        
        # Filter by sync type
        sync_type_filter = request.GET.get('sync_type', '')
        if sync_type_filter and sync_type_filter in ['full', 'incremental']:
            jobs = jobs.filter(sync_type=sync_type_filter)
        
        # Search by job name
        search_query = request.GET.get('search', '').strip()
        if search_query:
            jobs = jobs.filter(name__icontains=search_query)
        
        # Sorting
        sort_by = request.GET.get('sort', '-created_at')
        valid_sorts = ['name', '-name', 'created_at', '-created_at', 'status', '-status', 'last_run_at', '-last_run_at']
        if sort_by in valid_sorts:
            jobs = jobs.order_by(sort_by)
        else:
            jobs = jobs.order_by('-created_at')
        
        # Convert to list to evaluate query and catch any errors early
        jobs_list = list(jobs)
        
        # Get statistics
        try:
            from accounts.services.tenant_service import TenantService
            all_jobs_qs = SyncJob.objects.all()
            user_jobs_qs = TenantService.get_queryset_for_user(all_jobs_qs, request.user)
            total_jobs = user_jobs_qs.count()
            pending_count = user_jobs_qs.filter(status='pending').count()
            running_count = user_jobs_qs.filter(status='running').count()
            failed_count = user_jobs_qs.filter(status='failed').count()
        except DatabaseError as e:
            logger.error(f"Database error while fetching job statistics: {str(e)}")
            total_jobs = pending_count = running_count = failed_count = 0
            messages.warning(request, 'Unable to load job statistics. Please try again.')
        
        context = {
            'jobs': jobs_list,
            'page_title': 'Sync Jobs',
            'source_type_filter': source_type_filter,
            'status_filter': status_filter,
            'sync_type_filter': sync_type_filter,
            'search_query': search_query,
            'sort_by': sort_by,
            'stats': {
                'total': total_jobs,
                'pending': pending_count,
                'running': running_count,
                'failed': failed_count,
            }
        }
        
        return render(request, 'sync_jobs/job_list.html', context)
    except DatabaseError as e:
        logger.error(f"Database error in job_list view: {str(e)}", exc_info=True)
        messages.error(
            request, 
            'Database error occurred while loading jobs. Please try again or contact support if the problem persists.'
        )
        return render(request, 'sync_jobs/job_list.html', {
            'jobs': [],
            'page_title': 'Sync Jobs',
            'source_type_filter': '',
            'status_filter': '',
            'sync_type_filter': '',
            'search_query': '',
            'sort_by': '-created_at',
            'stats': {'total': 0, 'pending': 0, 'running': 0, 'failed': 0}
        })
    except Exception as e:
        logger.error(f"Error in job_list view: {str(e)}", exc_info=True)
        messages.error(
            request, 
            f'An error occurred while loading jobs: {str(e)}. Please refresh the page or contact support if the problem persists.'
        )
        return render(request, 'sync_jobs/job_list.html', {
            'jobs': [],
            'page_title': 'Sync Jobs',
            'source_type_filter': '',
            'status_filter': '',
            'sync_type_filter': '',
            'search_query': '',
            'sort_by': '-created_at',
            'stats': {'total': 0, 'pending': 0, 'running': 0, 'failed': 0}
        })


@login_required
def create_job_step1_view(request):
    """
    Step 1: Connection selection view
    First step of sync job creation wizard
    Supports database, API, and flat-file connections as source.
    """
    if request.method == 'POST':
        job_name = request.POST.get('job_name', '').strip()
        source_connection_id = request.POST.get('source_connection')
        source_file_connection_id = request.POST.get('source_file_connection')
        source_connection_type = request.POST.get('source_connection_type', '').strip()
        target_connection_id = request.POST.get('target_connection')
        
        # Enhanced validation
        errors = []
        
        # Job name validation
        try:
            from sync_jobs.validators import validate_job_name
            job_name = validate_job_name(job_name)
        except ValidationError as e:
            errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
        
        # Validate source connection type
        if source_connection_type not in ['database', 'api', 'flat_file']:
            errors.append('Invalid source connection type.')
        
        # Source selection validation (exclusive by source type)
        import uuid
        source_connection_uuid = None
        source_file_connection_uuid = None
        if source_connection_type in ['database', 'api']:
            if not source_connection_id:
                errors.append('Source connection is required.')
            if source_file_connection_id:
                errors.append('Only one source can be selected.')
            if source_connection_id:
                try:
                    source_connection_uuid = uuid.UUID(str(source_connection_id))
                except (ValueError, TypeError, AttributeError):
                    errors.append('Invalid source connection ID.')
        elif source_connection_type == 'flat_file':
            if not source_file_connection_id:
                errors.append('File source is required.')
            if source_connection_id:
                errors.append('Only one source can be selected.')
            if source_file_connection_id:
                try:
                    source_file_connection_uuid = uuid.UUID(str(source_file_connection_id))
                except (ValueError, TypeError, AttributeError):
                    errors.append('Invalid file source ID.')
        
        # Target connection validation (must always be database)
        target_connection_uuid = None
        if not target_connection_id:
            errors.append('Target connection is required.')
        else:
            try:
                # Validate UUID format (connection IDs are UUIDs)
                import uuid
                target_connection_uuid = uuid.UUID(str(target_connection_id))
            except (ValueError, TypeError, AttributeError):
                errors.append('Invalid target connection ID.')
        
        # Business rule: API can only be source, not target
        if source_connection_type == 'api':
            # API source is allowed, but target must be database (validated below)
            pass
        
        # Business rule: Source and target must be different (only if both are database)
        if source_connection_type == 'database' and source_connection_uuid and target_connection_uuid:
            if source_connection_uuid == target_connection_uuid:
                errors.append('Source and target connections cannot be the same.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            # Validate connections exist and belong to user
            from accounts.services.tenant_service import TenantService
            try:
                if source_connection_type == 'api':
                    # Source is API connection
                    api_qs = APIConnection.objects.filter(is_active=True)
                    user_api_conns = TenantService.get_queryset_for_user(api_qs, request.user)
                    source_api_connection = user_api_conns.get(id=source_connection_uuid)
                    
                    # Check if source API connection has been tested
                    if not source_api_connection.last_tested_at:
                        messages.error(
                            request,
                            f'API connection "{source_api_connection.name}" has not been tested. '
                            f'Please test the connection before creating a sync job.'
                        )
                        return redirect('sync_jobs:create_step1')
                    
                    # Target must be database connection
                    db_qs = DatabaseConnection.objects.filter(is_active=True)
                    user_db_conns = TenantService.get_queryset_for_user(db_qs, request.user)
                    target_connection = user_db_conns.get(id=target_connection_uuid)
                    
                    # Check if target database connection has been tested
                    if not target_connection.last_tested_at:
                        messages.error(
                            request,
                            f'Database connection "{target_connection.name}" has not been tested. '
                            f'Please test the connection before creating a sync job.'
                        )
                        return redirect('sync_jobs:create_step1')
                    
                    # Store in session for step 2
                    request.session['sync_job_name'] = job_name
                    request.session['sync_job_source_connection_type'] = 'api'
                    request.session['sync_job_source_api_connection_id'] = str(source_api_connection.id)
                    request.session['sync_job_target_connection_id'] = str(target_connection.id)
                    
                elif source_connection_type == 'database':
                    # Source is database connection
                    db_qs = DatabaseConnection.objects.filter(is_active=True)
                    user_db_conns = TenantService.get_queryset_for_user(db_qs, request.user)
                    source_connection = user_db_conns.get(id=source_connection_uuid)
                    target_connection = user_db_conns.get(id=target_connection_uuid)
                    
                    # Check if source database connection has been tested
                    if not source_connection.last_tested_at:
                        messages.error(
                            request,
                            f'Source database connection "{source_connection.name}" has not been tested. '
                            f'Please test the connection before creating a sync job.'
                        )
                        return redirect('sync_jobs:create_step1')
                    
                    # Check if target database connection has been tested
                    if not target_connection.last_tested_at:
                        messages.error(
                            request,
                            f'Target database connection "{target_connection.name}" has not been tested. '
                            f'Please test the connection before creating a sync job.'
                        )
                        return redirect('sync_jobs:create_step1')
                    
                    # Store in session for step 2
                    request.session['sync_job_name'] = job_name
                    request.session['sync_job_source_connection_type'] = 'database'
                    request.session['sync_job_source_connection_id'] = str(source_connection.id)
                    request.session.pop('sync_job_source_api_connection_id', None)
                    request.session.pop('sync_job_source_file_connection_id', None)
                    request.session['sync_job_target_connection_id'] = str(target_connection.id)
                else:
                    file_qs = FileSourceConnection.objects.filter(is_active=True)
                    user_file_sources = TenantService.get_queryset_for_user(file_qs, request.user)
                    source_file_connection = user_file_sources.get(id=source_file_connection_uuid)

                    db_qs = DatabaseConnection.objects.filter(is_active=True)
                    user_db_conns = TenantService.get_queryset_for_user(db_qs, request.user)
                    target_connection = user_db_conns.get(id=target_connection_uuid)

                    if not target_connection.last_tested_at:
                        messages.error(
                            request,
                            f'Target database connection "{target_connection.name}" has not been tested. '
                            f'Please test the connection before creating a sync job.'
                        )
                        return redirect('sync_jobs:create_step1')

                    request.session['sync_job_name'] = job_name
                    request.session['sync_job_source_connection_type'] = 'flat_file'
                    request.session['sync_job_source_file_connection_id'] = str(source_file_connection.id)
                    request.session.pop('sync_job_source_connection_id', None)
                    request.session.pop('sync_job_source_api_connection_id', None)
                    request.session['sync_job_target_connection_id'] = str(target_connection.id)
                
                # Redirect to step 2
                return redirect('sync_jobs:create_step2')
                
            except (DatabaseConnection.DoesNotExist, APIConnection.DoesNotExist, FileSourceConnection.DoesNotExist):
                messages.error(request, 'Selected connection not found or inactive.')
    
    # Get user's active connections
    from accounts.services.tenant_service import TenantService
    db_connections_qs = DatabaseConnection.objects.filter(is_active=True).order_by('name')
    db_connections = TenantService.get_queryset_for_user(db_connections_qs, request.user)
    
    api_connections_qs = APIConnection.objects.filter(is_active=True).order_by('name')
    api_connections = TenantService.get_queryset_for_user(api_connections_qs, request.user)
    file_sources_qs = FileSourceConnection.objects.filter(is_active=True).order_by('name')
    file_sources = TenantService.get_queryset_for_user(file_sources_qs, request.user)
    
    context = {
        'db_connections': db_connections,
        'api_connections': api_connections,
        'file_sources': file_sources,
        'page_title': 'Create Sync Job - Step 1',
        'job_name': request.session.get('sync_job_name', ''),
        'selected_source_id': (
            request.session.get('sync_job_source_connection_id')
            or request.session.get('sync_job_source_api_connection_id')
            or request.session.get('sync_job_source_file_connection_id', '')
        ),
        'selected_source_type': request.session.get('sync_job_source_connection_type', 'database'),
        'selected_target_id': request.session.get('sync_job_target_connection_id', ''),
    }
    
    return render(request, 'sync_jobs/create_step1.html', context)


@login_required
def create_job_step2_view(request):
    """
    Step 2: Table/Module selection view
    Gets source connection from session (set in step 1)
    For API sources: Shows module selection.
    For Database sources: Shows table selection.
    For flat-file sources: Shows preview mode.
    """
    # Get source connection info from session
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    source_api_connection_id = request.session.get('sync_job_source_api_connection_id')
    source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
    source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
    target_connection_id = request.session.get('sync_job_target_connection_id')
    job_name = request.session.get('sync_job_name')
    
    if not target_connection_id:
        messages.error(request, 'Please complete Step 1 first.')
        return redirect('sync_jobs:create_step1')
    
    if source_connection_type == 'api':
        # API source - show module selection
        if not source_api_connection_id:
            messages.error(request, 'Please complete Step 1 first.')
            return redirect('sync_jobs:create_step1')
        
        from accounts.services.tenant_service import TenantService
        try:
            api_qs = APIConnection.objects.filter(is_active=True)
            user_api_conns = TenantService.get_queryset_for_user(api_qs, request.user)
            source_api_connection = user_api_conns.get(id=source_api_connection_id)
            
            # Branch on API type: Zoho (modules) vs SAP (endpoints) vs Azure DevOps (projects)
            api_type = getattr(source_api_connection, 'api_type', None)
            is_sap = api_type == 'sap_b1'
            is_azure_devops = api_type == 'azure_devops'
            available_modules = []
            available_endpoints = []
            if is_sap:
                sap_endpoints_raw = source_api_connection.sap_endpoints or []
                for e in sap_endpoints_raw:
                    if isinstance(e, dict):
                        ep = e.get('endpoint') or e.get('name')
                        name = e.get('name') or ep or str(e)
                        if ep:
                            available_endpoints.append({'endpoint': ep, 'name': name})
                    else:
                        ep = str(e)
                        available_endpoints.append({'endpoint': ep, 'name': ep})
            else:
                available_modules = source_api_connection.selected_modules or []
            
            if is_sap:
                page_title = 'Select SAP Endpoints - Step 2'
            elif is_azure_devops:
                page_title = 'Select Projects - Step 2'
            else:
                page_title = 'Select Modules - Step 2'
            
            context = {
                'source_connection_type': 'api',
                'source_api_connection': source_api_connection,
                'available_modules': available_modules,
                'available_endpoints': available_endpoints,
                'is_sap': is_sap,
                'is_azure_devops': is_azure_devops,
                'job_name': job_name,
                'page_title': page_title,
            }
            
            return render(request, 'sync_jobs/create_step2.html', context)
            
        except APIConnection.DoesNotExist:
            messages.error(request, 'Source API connection not found or inactive.')
            return redirect('sync_jobs:create_step1')
    
    elif source_connection_type == 'database':
        # Database source - show table selection (existing flow)
        if not source_connection_id:
            messages.error(request, 'Please complete Step 1 first.')
            return redirect('sync_jobs:create_step1')
        
        from accounts.services.tenant_service import TenantService
        try:
            conn_qs = DatabaseConnection.objects.filter(is_active=True)
            user_conns = TenantService.get_queryset_for_user(conn_qs, request.user)
            source_connection = user_conns.get(id=source_connection_id)
        except DatabaseConnection.DoesNotExist:
            messages.error(request, 'Source connection not found or inactive.')
            return redirect('sync_jobs:create_step1')
        
        context = {
            'source_connection_type': 'database',
            'source_connection': source_connection,
            'job_name': job_name,
            'page_title': 'Select Tables - Step 2',
        }
        
        return render(request, 'sync_jobs/create_step2.html', context)
    else:
        if not source_file_connection_id:
            messages.error(request, 'Please complete Step 1 first.')
            return redirect('sync_jobs:create_step1')

        from accounts.services.tenant_service import TenantService
        try:
            file_qs = FileSourceConnection.objects.filter(is_active=True)
            user_file_sources = TenantService.get_queryset_for_user(file_qs, request.user)
            source_file_connection = user_file_sources.get(id=source_file_connection_id)
        except FileSourceConnection.DoesNotExist:
            messages.error(request, 'File source not found or inactive.')
            return redirect('sync_jobs:create_step1')

        context = {
            'source_connection_type': 'flat_file',
            'source_file_connection': source_file_connection,
            'job_name': job_name,
            'page_title': 'Select File Preview - Step 2',
        }
        return render(request, 'sync_jobs/create_step2.html', context)


@login_required
@require_http_methods(["GET"])
def create_job_step2_flat_file_preview(request):
    """Preview file metadata for flat-file Step 2."""
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
    if source_connection_type != 'flat_file' or not source_file_connection_id:
        return JsonResponse({'success': False, 'message': 'Please complete Step 1 first.'}, status=400)

    from accounts.services.tenant_service import TenantService
    try:
        file_qs = FileSourceConnection.objects.filter(is_active=True)
        user_file_sources = TenantService.get_queryset_for_user(file_qs, request.user)
        source_file_connection = user_file_sources.get(id=source_file_connection_id)
    except FileSourceConnection.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'File source not found or inactive.'}, status=404)

    from sync_jobs.services.flat_file_preview_service import build_flat_file_preview

    try:
        preview_data = build_flat_file_preview(source_file_connection)
        return JsonResponse({'success': True, **preview_data})
    except ValidationError as exc:
        message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        return JsonResponse({'success': False, 'message': message}, status=400)
    except PermissionError:
        return JsonResponse({'success': False, 'message': 'Server cannot read file. Check file permissions.'}, status=200)
    except UnicodeDecodeError:
        return JsonResponse({'success': False, 'message': 'Encoding mismatch while reading file. Please verify encoding.'}, status=200)
    except FileNotFoundError:
        return JsonResponse({'success': False, 'message': 'File not found under configured source root.'}, status=200)
    except Exception as exc:
        logger.exception('Error generating flat-file preview')
        return JsonResponse({'success': False, 'message': f'Error generating preview: {exc}'}, status=500)


@login_required
def create_job_step2_load_metadata(request):
    """
    AJAX endpoint to load metadata for source connection
    """
    source_connection_id = request.GET.get('connection_id')
    
    if not source_connection_id:
        return JsonResponse({
            'success': False,
            'error': 'Connection ID required'
        }, status=400)
    
    from accounts.services.tenant_service import TenantService
    try:
        conn_qs = DatabaseConnection.objects.filter(is_active=True)
        user_conns = TenantService.get_queryset_for_user(conn_qs, request.user)
        connection = user_conns.get(id=source_connection_id)
    except DatabaseConnection.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Connection not found or inactive'
        }, status=404)
    
    try:
        from metadata.services import load_all_metadata
        metadata = load_all_metadata(str(connection.id), request.user, include_row_counts=False)
        return JsonResponse({
            'success': True,
            'data': metadata
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_table_columns_api(request):
    """
    API endpoint to get table columns for transformation UI
    """
    try:
        connection_id = request.GET.get('connection_id')
        schema = request.GET.get('schema')
        table = request.GET.get('table')
        
        if not all([connection_id, schema, table]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters: connection_id, schema, table'
            }, status=400)
        
        # Get connection
        from accounts.services.tenant_service import TenantService
        conn_qs = DatabaseConnection.objects.filter(is_active=True, id=connection_id)
        user_conns = TenantService.get_queryset_for_user(conn_qs, request.user)
        
        try:
            connection = user_conns.get(id=connection_id)
        except DatabaseConnection.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Connection not found or access denied'
            }, status=404)
        
        # Load columns
        columns = load_table_columns(
            str(connection.id),
            schema,
            table,
            request.user
        )
        
        return JsonResponse({
            'success': True,
            'columns': columns
        })
        
    except Exception as e:
        logger.error(f"Error loading table columns: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error loading columns: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def validate_transformation_query(request):
    """
    API endpoint to validate transformation query syntax
    """
    try:
        connection_id = request.POST.get('connection_id')
        schema = request.POST.get('schema')
        table = request.POST.get('table')
        where_clause = request.POST.get('where_clause', '').strip()
        column_transformations_json = request.POST.get('column_transformations', '{}')
        
        if not all([connection_id, schema, table]):
            return JsonResponse({
                'valid': False,
                'error': 'Missing required parameters: connection_id, schema, table'
            }, status=400)
        
        # Parse column transformations
        import json
        try:
            column_transformations = json.loads(column_transformations_json) if column_transformations_json else {}
        except:
            column_transformations = {}
        
        # Get connection
        from accounts.services.tenant_service import TenantService
        conn_qs = DatabaseConnection.objects.filter(is_active=True, id=connection_id)
        user_conns = TenantService.get_queryset_for_user(conn_qs, request.user)
        
        try:
            connection = user_conns.get(id=connection_id)
        except DatabaseConnection.DoesNotExist:
            return JsonResponse({
                'valid': False,
                'error': 'Connection not found or access denied'
            }, status=404)
        
        # Get connector - use the connection object directly
        from connections.connectors.factory import get_connector
        connector = get_connector(connection)
        
        # Validate transformations
        from sync_engine.transformation_validator import TransformationValidator
        validator = TransformationValidator()
        
        validation_errors = []
        
        # Validate WHERE clause if provided
        if where_clause:
            is_valid, error = validator.validate_where_clause(
                where_clause=where_clause,
                schema=schema,
                table=table,
                connector=connector
            )
            if not is_valid:
                validation_errors.append(f"WHERE clause: {error}")
        
        # Validate column transformations if provided
        if column_transformations:
            is_valid, error = validator.validate_column_transformations(
                transformations=column_transformations,
                schema=schema,
                table=table,
                connector=connector
            )
            if not is_valid:
                validation_errors.append(f"Column transformations: {error}")
        
        connector.close()
        
        if validation_errors:
            return JsonResponse({
                'valid': False,
                'error': '; '.join(validation_errors)
            })
        
        return JsonResponse({
            'valid': True,
            'message': 'Transformation query is valid'
        })
        
    except Exception as e:
        logger.error(f"Error validating transformation query: {str(e)}", exc_info=True)
        return JsonResponse({
            'valid': False,
            'error': f'Validation error: {str(e)}'
        }, status=500)


@login_required
@viewer_read_only_required
def create_job_step2_submit(request):
    """
    Handle Step 2 form submission
    Supports both table selection (database) and module selection (API)
    """
    if request.method != 'POST':
        return redirect('sync_jobs:create_step2')
    
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    
    if source_connection_type == 'api':
        # API source - handle module (Zoho) or endpoint (SAP) selection
        source_api_connection_id = request.session.get('sync_job_source_api_connection_id')
        if not source_api_connection_id:
            messages.error(request, 'Please complete Step 1 first.')
            return redirect('sync_jobs:create_step2')
        from accounts.services.tenant_service import TenantService
        try:
            api_qs = APIConnection.objects.filter(is_active=True)
            user_api_conns = TenantService.get_queryset_for_user(api_qs, request.user)
            source_api_connection = user_api_conns.get(id=source_api_connection_id)
        except APIConnection.DoesNotExist:
            messages.error(request, 'Source API connection not found or inactive.')
            return redirect('sync_jobs:create_step2')

        is_sap = getattr(source_api_connection, 'api_type', None) == 'sap_b1'
        if is_sap:
            selected_endpoints = request.POST.getlist('selected_endpoints')
            if not selected_endpoints:
                messages.error(request, 'Please select at least one endpoint.')
                return redirect('sync_jobs:create_step2')
            tables = [
                {'schema_name': 'sap_api', 'table_name': endpoint_name}
                for endpoint_name in selected_endpoints
            ]
            request.session['sync_job_selected_tables'] = tables
            request.session['sync_job_table_transformations'] = {}
            messages.success(request, f'Selected {len(tables)} endpoint(s).')
        else:
            selected_modules = request.POST.getlist('selected_modules')
            if not selected_modules:
                messages.error(request, 'Please select at least one module.')
                return redirect('sync_jobs:create_step2')
            modules = [
                {'schema_name': 'api', 'table_name': module_name}
                for module_name in selected_modules
            ]
            request.session['sync_job_selected_tables'] = modules
            request.session['sync_job_table_transformations'] = {}
            messages.success(request, f'Selected {len(modules)} module(s).')
        # For API-based jobs we skip the mapping step and go directly to sync configuration
        return redirect('sync_jobs:create_step4')
    
    elif source_connection_type == 'database':
        # Database source - handle table selection (existing flow)
        selected_tables = request.POST.getlist('selected_tables')
        
        if not selected_tables:
            messages.error(request, 'Please select at least one table.')
            return redirect('sync_jobs:create_step2')
        
        # Parse selected tables and store in session
        tables = []
        for table_json in selected_tables:
            try:
                import json
                table_data = json.loads(table_json)
                tables.append({
                    'schema_name': table_data['schema'],
                    'table_name': table_data['table']
                })
            except:
                continue
        
        if not tables:
            messages.error(request, 'Invalid table selection.')
            return redirect('sync_jobs:create_step2')
        
        # Store in session for step 3
        request.session['sync_job_selected_tables'] = tables
        
        # Store transformation data in session if provided
        table_transformations_json = request.POST.get('table_transformations', '{}')
        try:
            import json
            table_transformations = json.loads(table_transformations_json)
            request.session['sync_job_table_transformations'] = table_transformations
        except:
            request.session['sync_job_table_transformations'] = {}
        
        # Clear model-step state when selection changes
        request.session.pop('sync_job_transform_plan', None)
        request.session.pop('sync_job_transform_validated', None)
        request.session.pop('sync_job_transform_preview_cache', None)

        # Redirect to step 3 model (join/union/lookup), then mapping
        messages.success(request, f'Selected {len(tables)} table(s).')
        # MongoDB is document-based; skip model (SQL join/union/lookup) step.
        try:
            from accounts.services.tenant_service import TenantService
            src_id = request.session.get('sync_job_source_connection_id')
            if src_id:
                src_qs = DatabaseConnection.objects.filter(is_active=True)
                user_src = TenantService.get_queryset_for_user(src_qs, request.user)
                src_conn = user_src.get(id=src_id)
                if getattr(src_conn, 'db_type', None) == 'mongodb':
                    request.session['sync_job_skip_model_step'] = True
                    request.session.pop('sync_job_transform_validated', None)
                    request.session.modified = True
                    return redirect('sync_jobs:create_step3')
        except Exception:
            # Fail open to existing flow if anything goes wrong here.
            pass

        request.session['sync_job_skip_model_step'] = False
        request.session.modified = True
        return redirect('sync_jobs:create_step3_model')
    else:
        source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
        if not source_file_connection_id:
            messages.error(request, 'Please complete Step 1 first.')
            return redirect('sync_jobs:create_step1')

        from accounts.services.tenant_service import TenantService
        try:
            file_qs = FileSourceConnection.objects.filter(is_active=True)
            user_file_sources = TenantService.get_queryset_for_user(file_qs, request.user)
            source_file_connection = user_file_sources.get(id=source_file_connection_id)
        except FileSourceConnection.DoesNotExist:
            messages.error(request, 'File source not found or inactive.')
            return redirect('sync_jobs:create_step1')

        target_table_name = (request.POST.get('target_table_name') or '').strip()
        if not target_table_name:
            target_table_name = os.path.splitext(os.path.basename(source_file_connection.relative_path))[0] or 'flat_file_source'
        target_table_name = re.sub(r'[^0-9a-zA-Z_]', '_', target_table_name).strip('_').lower()
        if not target_table_name:
            target_table_name = 'flat_file_source'
        if len(target_table_name) > 63:
            target_table_name = target_table_name[:63]

        request.session['sync_job_selected_tables'] = [{
            'schema_name': 'file',
            'table_name': target_table_name,
        }]
        request.session['sync_job_table_transformations'] = {}
        request.session['sync_job_flat_file_preview_table_name'] = target_table_name
        messages.success(request, 'Flat-file source selected.')
        return redirect('sync_jobs:create_step3')


@login_required
def create_job_step3_model_view(request):
    """
    Step 3a: Model data (single table / join / union / lookup) for database sources.
    """
    job_name = request.session.get("sync_job_name")
    source_connection_type = request.session.get("sync_job_source_connection_type", "database")
    source_connection_id = request.session.get("sync_job_source_connection_id")
    target_connection_id = request.session.get("sync_job_target_connection_id")
    selected_tables = request.session.get("sync_job_selected_tables", [])

    # Defensive: the UI should never render duplicate plan cards.
    # Some navigation flows can accidentally duplicate session entries, so
    # we dedupe by schema+table here (and write back to the session).
    def _dedupe_selected_tables(tables):
        out = []
        seen = set()
        for t in (tables or []):
            if not isinstance(t, dict):
                continue
            schema_name = (t.get("schema_name") or "").strip()
            table_name = (t.get("table_name") or "").strip()
            if not schema_name or not table_name:
                continue
            key = f"{schema_name.lower()}.{table_name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"schema_name": schema_name, "table_name": table_name})
        return out

    selected_tables = _dedupe_selected_tables(selected_tables)
    request.session["sync_job_selected_tables"] = selected_tables
    request.session.modified = True

    if source_connection_type == "api":
        return redirect("sync_jobs:create_step4")
    if source_connection_type == "flat_file":
        messages.info(request, "Model Data step applies to database sources only. Continuing to column mapping.")
        return redirect("sync_jobs:create_step3")
    if not all([job_name, source_connection_id, target_connection_id, selected_tables]):
        messages.error(request, "Please complete previous steps first.")
        return redirect("sync_jobs:create_step1")

    from accounts.services.tenant_service import TenantService
    from sync_jobs.services.transform_plan_service import ensure_default_plans

    try:
        src_qs = DatabaseConnection.objects.filter(is_active=True)
        user_src = TenantService.get_queryset_for_user(src_qs, request.user)
        source_connection = user_src.get(id=source_connection_id)
    except DatabaseConnection.DoesNotExist:
        messages.error(request, "Source connection not found.")
        return redirect("sync_jobs:create_step1")

    if getattr(source_connection, "db_type", None) == "mongodb":
        messages.info(
            request,
            "Model Data step is not available for MongoDB sources. Continuing to column mapping.",
        )
        request.session['sync_job_skip_model_step'] = True
        request.session.pop('sync_job_transform_validated', None)
        request.session.modified = True
        return redirect("sync_jobs:create_step3")
    try:
        tgt_qs = DatabaseConnection.objects.filter(is_active=True)
        user_tgt = TenantService.get_queryset_for_user(tgt_qs, request.user)
        target_connection = user_tgt.get(id=target_connection_id)
    except DatabaseConnection.DoesNotExist:
        messages.error(request, "Target connection not found.")
        return redirect("sync_jobs:create_step1")

    internal_src_type = _normalize_job_source_db_type(source_connection)
    existing = request.session.get("sync_job_transform_plan")
    if not isinstance(existing, dict):
        existing = {}
    transform_plans = ensure_default_plans(selected_tables, internal_src_type, existing)
    request.session["sync_job_transform_plan"] = transform_plans
    request.session.modified = True

    context = {
        "job_name": job_name,
        "source_connection": source_connection,
        "target_connection": target_connection,
        "selected_tables": selected_tables,
        "transform_plans": transform_plans,
        "source_db_type": internal_src_type,
        "allow_custom_sql": bool(
            getattr(getattr(request.user, "userprofile", None), "is_admin", lambda: False)()
            or getattr(getattr(request.user, "userprofile", None), "is_super_admin", lambda: False)()
            or getattr(request.user, "is_staff", False)
        ),
        "page_title": "Model Data - Step 3",
    }
    return render(request, "sync_jobs/create_step3_model.html", context)


def _user_can_use_custom_sql(user) -> bool:
    profile = getattr(user, "userprofile", None)
    if profile is not None:
        if callable(getattr(profile, "is_admin", None)) and profile.is_admin():
            return True
        if callable(getattr(profile, "is_super_admin", None)) and profile.is_super_admin():
            return True
    return bool(getattr(user, "is_staff", False))


@login_required
@viewer_read_only_required
def create_job_step3_model_preview(request):
    """Bounded SELECT preview for transform plan (AJAX JSON)."""
    if request.method != "POST":
        return JsonResponse(
            {"ok": False, "error_code": "method_not_allowed", "message": "POST required."},
            status=405,
        )

    job_name = request.session.get("sync_job_name")
    source_connection_type = request.session.get("sync_job_source_connection_type", "database")
    source_connection_id = request.session.get("sync_job_source_connection_id")
    selected_tables = request.session.get("sync_job_selected_tables", [])

    if source_connection_type != "database":
        return JsonResponse(
            {
                "ok": False,
                "error_code": "unsupported_source",
                "message": "Preview is only available for database sources.",
            },
            status=400,
        )
    if not all([job_name, source_connection_id, selected_tables]):
        return JsonResponse(
            {"ok": False, "error_code": "session_invalid", "message": "Session incomplete. Restart the wizard."},
            status=401,
        )

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"ok": False, "error_code": "invalid_json", "message": "Invalid JSON body."},
            status=400,
        )

    table_key = (body.get("table_key") or "").strip()
    plan = body.get("plan")
    if not table_key or not isinstance(plan, dict):
        return JsonResponse(
            {"ok": False, "error_code": "invalid_payload", "message": "table_key and plan are required."},
            status=400,
        )

    allowed = {_wizard_table_key(t) for t in selected_tables}
    if table_key not in allowed:
        return JsonResponse(
            {"ok": False, "error_code": "unknown_table", "message": "Table is not part of this job."},
            status=400,
        )

    from accounts.services.tenant_service import TenantService
    from connections.connectors import get_connector
    from sync_jobs.services.transform_plan_service import (
        TransformPlanValidationError,
        builder_to_transform_plan,
        compile_preview_select,
        execute_preview_query,
        validate_transform_plan_column_references,
        validate_transform_plan,
        validate_custom_sql_preview,
    )

    try:
        src_qs = DatabaseConnection.objects.filter(is_active=True)
        user_src = TenantService.get_queryset_for_user(src_qs, request.user)
        source_connection = user_src.get(id=source_connection_id)
    except DatabaseConnection.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error_code": "connection_not_found", "message": "Source connection not found."},
            status=404,
        )

    src_type = _normalize_job_source_db_type(source_connection)
    builder_payload = body.get("builder_payload")
    try:
        if isinstance(builder_payload, dict):
            normalized = builder_to_transform_plan(
                builder_payload,
                plan_table_key=table_key,
                allowed_table_keys=allowed,
                source_db_type=source_connection.db_type,
                allow_custom_sql=_user_can_use_custom_sql(request.user),
            )
        else:
            normalized = validate_transform_plan(
                plan,
                plan_table_key=table_key,
                allowed_table_keys=allowed,
                source_db_type=source_connection.db_type,
            )
    except TransformPlanValidationError as e:
        return JsonResponse(
            {"ok": False, "error_code": e.error_code, "message": e.message},
            status=400,
        )

    connector = None
    try:
        connector = get_connector(
            db_type=source_connection.db_type,
            host=source_connection.host,
            port=source_connection.port,
            username=source_connection.username,
            password=source_connection.get_decrypted_password(),
            database_name=source_connection.database_name,
        )
        connector.connect()
        custom_sql = normalized.get("_custom_sql_preview_only")
        warnings = []
        if custom_sql:
            if not _user_can_use_custom_sql(request.user):
                raise TransformPlanValidationError(
                    "custom_sql mode is admin-only.",
                    "custom_sql_not_allowed",
                )
            sql = validate_custom_sql_preview(str(custom_sql))
        else:
            validate_transform_plan_column_references(normalized, connector)
            sql, warnings = compile_preview_select(normalized, limit=50)
        columns, rows = execute_preview_query(connector, sql, max_rows=50)
        return JsonResponse(
            {
                "ok": True,
                "generated_sql": sql,
                "columns": columns,
                "preview_rows": rows,
                "warnings": warnings,
                "source_db_type": src_type,
            }
        )
    except TransformPlanValidationError as e:
        return JsonResponse(
            {"ok": False, "error_code": e.error_code, "message": e.message},
            status=400,
        )
    except Exception as e:
        logger.exception("Transform preview failed for %s: %s", table_key, e)
        safe_msg = "Preview query failed."
        if getattr(request, "user", None) and request.user.is_staff:
            safe_msg = f"Preview query failed: {str(e)}"
        return JsonResponse(
            {"ok": False, "error_code": "preview_failed", "message": safe_msg},
            status=500,
        )
    finally:
        if connector and hasattr(connector, "close"):
            try:
                connector.close()
            except Exception:
                pass


@login_required
@viewer_read_only_required
def create_job_step3_model_submit(request):
    """Validate and store transform plans; continue to column mapping."""
    if request.method != "POST":
        return redirect("sync_jobs:create_step3_model")

    job_name = request.session.get("sync_job_name")
    source_connection_type = request.session.get("sync_job_source_connection_type", "database")
    source_connection_id = request.session.get("sync_job_source_connection_id")
    target_connection_id = request.session.get("sync_job_target_connection_id")
    selected_tables = request.session.get("sync_job_selected_tables", [])

    if source_connection_type != "database":
        messages.error(request, "Invalid step for this source type.")
        return redirect("sync_jobs:create_step1")
    if not all([job_name, source_connection_id, target_connection_id, selected_tables]):
        messages.error(request, "Please complete previous steps first.")
        return redirect("sync_jobs:create_step1")

    raw = (request.POST.get("transform_plans_json") or "").strip()
    try:
        posted = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        messages.error(request, "Invalid transform plan JSON.")
        return redirect("sync_jobs:create_step3_model")

    if not isinstance(posted, dict):
        messages.error(request, "Transform plans must be a JSON object keyed by schema.table.")
        return redirect("sync_jobs:create_step3_model")

    from accounts.services.tenant_service import TenantService
    from sync_jobs.services.transform_plan_service import (
        TransformPlanValidationError,
        builder_to_transform_plan,
        ensure_default_plans,
        validate_transform_plan,
        validate_transform_plan_column_references,
    )

    try:
        src_qs = DatabaseConnection.objects.filter(is_active=True)
        user_src = TenantService.get_queryset_for_user(src_qs, request.user)
        source_connection = user_src.get(id=source_connection_id)
    except DatabaseConnection.DoesNotExist:
        messages.error(request, "Source connection not found.")
        return redirect("sync_jobs:create_step1")

    internal = _normalize_job_source_db_type(source_connection)
    allowed = {_wizard_table_key(t) for t in selected_tables}
    merged = ensure_default_plans(selected_tables, internal, posted)
    builder_by_table = {}
    builder_raw = request.POST.get("transform_builder_json")
    if builder_raw:
        try:
            maybe_builder = json.loads(builder_raw)
            if isinstance(maybe_builder, dict):
                builder_by_table = maybe_builder
        except json.JSONDecodeError:
            messages.error(request, "Invalid builder payload JSON.")
            return redirect("sync_jobs:create_step3_model")
    cleaned: Dict[str, Any] = {}
    errors = []
    for t in selected_tables:
        tk = _wizard_table_key(t)
        plan = merged.get(tk)
        if not isinstance(plan, dict):
            errors.append(f"Missing plan for {tk}")
            continue
        try:
            if isinstance(builder_by_table.get(tk), dict):
                cleaned[tk] = builder_to_transform_plan(
                    builder_by_table.get(tk),
                    plan_table_key=tk,
                    allowed_table_keys=allowed,
                    source_db_type=source_connection.db_type,
                    allow_custom_sql=_user_can_use_custom_sql(request.user),
                )
            else:
                cleaned[tk] = validate_transform_plan(
                    plan,
                    plan_table_key=tk,
                    allowed_table_keys=allowed,
                    source_db_type=source_connection.db_type,
                )
        except TransformPlanValidationError as e:
            errors.append(f"{tk}: {e.message}")

    if errors:
        messages.error(request, " ; ".join(errors))
        return redirect("sync_jobs:create_step3_model")

    # Fail fast: validate that transform-plan column references exist in the source DB.
    # This prevents runtime SQL errors like "Invalid column name ..." during sync.
    connector = None
    try:
        from connections.connectors import get_connector

        connector = get_connector(
            db_type=source_connection.db_type,
            host=source_connection.host,
            port=source_connection.port,
            username=source_connection.username,
            password=source_connection.get_decrypted_password(),
            database_name=source_connection.database_name,
        )
        connector.connect()

        for tk, plan_for_table in cleaned.items():
            if plan_for_table.get("_custom_sql_preview_only"):
                continue
            validate_transform_plan_column_references(plan_for_table, connector)
    except TransformPlanValidationError as e:
        messages.error(request, f"[{e.error_code}] {e.message}")
        return redirect("sync_jobs:create_step3_model")
    finally:
        if connector and hasattr(connector, "close"):
            try:
                connector.close()
            except Exception:
                pass

    request.session["sync_job_transform_plan"] = cleaned
    if builder_by_table:
        request.session["sync_job_transform_builder"] = builder_by_table
    request.session["sync_job_transform_validated"] = True
    request.session.modified = True
    messages.success(request, "Model configuration saved. Review column mapping next.")
    return redirect("sync_jobs:create_step3")


@login_required
@require_http_methods(["GET"])
def create_job_step3_model_builder_metadata(request):
    """Return selected table columns and join-key suggestions for Step 3 builder UI."""
    source_connection_id = request.session.get("sync_job_source_connection_id")
    selected_tables = request.session.get("sync_job_selected_tables", [])
    if not source_connection_id or not selected_tables:
        return JsonResponse({"ok": False, "message": "Session incomplete."}, status=400)

    from accounts.services.tenant_service import TenantService
    from sync_jobs.services.transform_plan_service import suggest_join_keys

    try:
        src_qs = DatabaseConnection.objects.filter(is_active=True)
        user_src = TenantService.get_queryset_for_user(src_qs, request.user)
        source_connection = user_src.get(id=source_connection_id)
    except DatabaseConnection.DoesNotExist:
        return JsonResponse({"ok": False, "message": "Source connection not found."}, status=404)

    by_table: Dict[str, Any] = {}
    for t in selected_tables:
        schema_name = t.get("schema_name")
        table_name = t.get("table_name")
        if not schema_name or not table_name:
            continue
        key = f"{schema_name}.{table_name}"
        try:
            cols = load_table_columns(str(source_connection.id), schema_name, table_name, request.user) or []
        except Exception:
            cols = []
        col_names = [str(c.get("name") or c.get("column_name") or "").strip() for c in cols]
        col_names = [c for c in col_names if c]
        by_table[key] = {"columns": col_names}

    keys = sorted(by_table.keys(), key=lambda s: s.lower())
    suggestions: Dict[str, Any] = {}
    for lk in keys:
        for rk in keys:
            if lk == rk:
                continue
            s_key = f"{lk}__{rk}"
            suggestions[s_key] = suggest_join_keys(
                by_table.get(lk, {}).get("columns", []),
                by_table.get(rk, {}).get("columns", []),
            )

    return JsonResponse({"ok": True, "tables": by_table, "join_suggestions": suggestions})


@login_required
def create_job_step3_mapping_view(request):
    """
    Step 3: Data type mapping preview for database-to-database sync jobs.

    For each selected table/column, show how the source data type maps to the
    target data type. This step is read-only and does not change runtime
    behaviour; the actual mapping is still enforced in the sync engine.
    """
    job_name = request.session.get('sync_job_name')
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    target_connection_id = request.session.get('sync_job_target_connection_id')
    selected_tables = request.session.get('sync_job_selected_tables', [])

    # Defensive: avoid duplicate mapping/plan blocks if session contains dupes.
    # This mirrors create_job_step3_model_view dedupe logic.
    def _dedupe_selected_tables(tables):
        out = []
        seen = set()
        for t in (tables or []):
            if not isinstance(t, dict):
                continue
            schema_name = (t.get("schema_name") or "").strip()
            table_name = (t.get("table_name") or "").strip()
            if not schema_name or not table_name:
                continue
            key = f"{schema_name.lower()}.{table_name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"schema_name": schema_name, "table_name": table_name})
        return out

    selected_tables = _dedupe_selected_tables(selected_tables)
    request.session["sync_job_selected_tables"] = selected_tables
    request.session.modified = True

    if source_connection_type == 'api':
        return redirect('sync_jobs:create_step4')

    source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
    if source_connection_type == 'database' and not all([job_name, source_connection_id, target_connection_id, selected_tables]):
        messages.error(request, 'Please complete previous steps first.')
        return redirect('sync_jobs:create_step1')
    if source_connection_type == 'flat_file' and not all([job_name, source_file_connection_id, target_connection_id, selected_tables]):
        messages.error(request, 'Please complete previous steps first.')
        return redirect('sync_jobs:create_step1')

    if (
        source_connection_type == 'database'
        and not request.session.get('sync_job_skip_model_step')
        and not request.session.get(
        "sync_job_transform_validated"
        )
    ):
        messages.info(
            request, "Configure how source tables are combined, then continue to column mapping."
        )
        return redirect("sync_jobs:create_step3_model")

    from accounts.services.tenant_service import TenantService

    source_connection = None
    source_file_connection = None

    # Load source and target connections
    if source_connection_type == 'database':
        try:
            src_qs = DatabaseConnection.objects.filter(is_active=True)
            user_src_conns = TenantService.get_queryset_for_user(src_qs, request.user)
            source_connection = user_src_conns.get(id=source_connection_id)
        except DatabaseConnection.DoesNotExist:
            messages.error(request, 'Source connection not found.')
            return redirect('sync_jobs:create_step1')
    else:
        try:
            file_qs = FileSourceConnection.objects.filter(is_active=True)
            user_file_sources = TenantService.get_queryset_for_user(file_qs, request.user)
            source_file_connection = user_file_sources.get(id=source_file_connection_id)
        except FileSourceConnection.DoesNotExist:
            messages.error(request, 'File source not found or inactive.')
            return redirect('sync_jobs:create_step2')

    try:
        tgt_qs = DatabaseConnection.objects.filter(is_active=True)
        user_tgt_conns = TenantService.get_queryset_for_user(tgt_qs, request.user)
        target_connection = user_tgt_conns.get(id=target_connection_id)
    except DatabaseConnection.DoesNotExist:
        messages.error(request, 'Target connection not found.')
        return redirect('sync_jobs:create_step1')

    # Build mapping info per table
    from core.type_mapping import normalize_data_type, map_source_to_oracle_type

    # Derive db_type strings compatible with type-mapping helpers
    def _normalize_db_type(conn) -> str:
        dbt = (getattr(conn, "db_type", "") or "").lower()
        # Internal code uses 'oracle' for Oracle ADW
        if dbt == "oracle_adw":
            return "oracle"
        return dbt

    source_db_type = _normalize_db_type(source_connection) if source_connection else "flat_file"
    target_db_type = _normalize_db_type(target_connection)
    is_mongo_source = source_connection_type == "database" and source_db_type == "mongodb"

    def compute_allowed_types(src_db: str, tgt_db: str, src_type: str):
        """
        Return a small list of reasonable target types for a given source type.

        Focus first on MySQL -> Oracle ADW, fall back to simple same-type mapping for others.
        """
        t = (src_type or "").upper()

        # MySQL -> Oracle ADW
        if src_db == "mysql" and tgt_db == "oracle":
            # Integer-like
            if any(kw in t for kw in ["INT", "BIGINT", "SMALLINT", "MEDIUMINT", "TINYINT"]):
                return ["NUMBER(10)", "NUMBER(38)", "BINARY_DOUBLE", "VARCHAR2(50)", "VARCHAR2(100)"]
            # Floating point
            if any(kw in t for kw in ["FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL"]):
                return ["BINARY_FLOAT", "BINARY_DOUBLE", "NUMBER(38,10)", "VARCHAR2(100)"]
            # Textual
            if any(kw in t for kw in ["CHAR", "TEXT", "CLOB", "JSON", "ENUM", "SET"]):
                return ["VARCHAR2(100)", "VARCHAR2(255)", "CLOB"]
            # Date/Time
            if any(kw in t for kw in ["DATE", "TIME", "TIMESTAMP", "YEAR", "DATETIME"]):
                return ["DATE", "TIMESTAMP", "VARCHAR2(50)"]
            # Boolean-ish
            if "TINYINT(1)" in t or t == "BOOLEAN" or t == "BOOL":
                return ["NUMBER(1)", "NUMBER(3)", "VARCHAR2(5)"]

        # Default: offer just the current type
        return [src_type] if src_type else []

    existing_overrides = request.session.get("sync_job_column_type_overrides", {})
    existing_name_overrides = request.session.get("sync_job_column_name_overrides", {}) or {}
    existing_excluded_by_table = request.session.get("sync_job_excluded_columns", {}) or {}
    existing_protected_by_table = request.session.get("sync_job_protected_columns", {}) or {}

    def _is_datetime_like(data_type: str) -> bool:
        dt = (data_type or "").lower()
        return any(token in dt for token in ["timestamp", "datetime", "date", "time"])

    def _is_numeric_like(data_type: str) -> bool:
        dt = (data_type or "").lower()
        return any(
            token in dt
            for token in [
                "int",
                "bigint",
                "serial",
                "number",
                "decimal",
                "numeric",
                "float",
                "double",
                "uint",
            ]
        )

    def _resolve_incremental_column_auto_preview(columns: list, pk_columns: list):
        """
        Mirror IncrementalSyncExecutor._resolve_incremental_column_auto() (preview-only).
        Returns the predicted incremental column name or None.
        """
        by_name = {}
        for c in columns:
            cname = c.get("name") or c.get("column_name")
            if cname:
                by_name[cname.lower()] = c

        preferred_datetime_names = [
            "updated_at",
            "modified_at",
            "last_updated",
            "last_modified",
            "updatedon",
            "modifiedon",
            "update_date",
            "update_time",
            "updated_date",
            "modified_time",
            "modifieddate",
        ]

        for cname in preferred_datetime_names:
            col = by_name.get(cname)
            if col and _is_datetime_like(col.get("data_type", "")):
                return col.get("name") or col.get("column_name")

        for col in columns:
            if _is_datetime_like(col.get("data_type", "")):
                return col.get("name") or col.get("column_name")

        if pk_columns:
            pk_lower = {p.lower() for p in pk_columns if p}
            for col in columns:
                col_name = col.get("name") or col.get("column_name")
                if not col_name:
                    continue
                if col_name.lower() in pk_lower and _is_numeric_like(col.get("data_type", "")):
                    return col_name
            for col in columns:
                col_name = col.get("name") or col.get("column_name")
                if not col_name:
                    continue
                if col_name.lower() in pk_lower:
                    return col_name

        return None

    table_mappings: Dict[str, Any] = {}

    from sync_jobs.validators import resolve_protected_columns

    for table_info in selected_tables:
        schema_name = table_info.get('schema_name')
        table_name = table_info.get('table_name')
        table_key = f"{schema_name}.{table_name}"

        if source_connection_type == 'flat_file':
            from sync_jobs.services.flat_file_preview_service import build_flat_file_preview
            try:
                preview = build_flat_file_preview(source_file_connection)
                headers = preview.get("columns", []) or []
                if not headers:
                    messages.error(request, 'No usable columns found in file preview. Please re-run Step 2.')
                    return redirect('sync_jobs:create_step2')
                columns = []
                for idx, header in enumerate(headers, start=1):
                    safe_target = re.sub(r'[^0-9a-zA-Z_]', '_', (header or '')).strip('_').lower() or f'column_{idx}'
                    columns.append({
                        'name': header,
                        'column_name': header,
                        'data_type': 'string',
                        'is_nullable': True,
                        'is_primary_key': False,
                        'target_column_name': safe_target,
                    })
                request.session['sync_job_flat_file_headers'] = headers
            except Exception as e:
                logger.warning("Failed to preview file columns for %s: %s", table_key, e)
                messages.error(request, 'Unable to load flat-file columns. Please verify Step 2 preview and try again.')
                return redirect('sync_jobs:create_step2')
        else:
            try:
                columns = _load_columns_for_mapping_step(
                    request,
                    source_connection=source_connection,
                    source_connection_type=source_connection_type,
                    table_info=table_info,
                    user=request.user,
                )
            except Exception as e:
                logger.warning("Failed to load columns for %s: %s", table_key, e)
                table_mappings[table_key] = {
                    'columns': [],
                }
                continue

        mapped_columns = []

        pk_columns = []
        for col in columns:
            if col.get("is_primary_key"):
                pk_columns.append(col.get("name") or col.get("column_name"))

        predicted_incremental_column = _resolve_incremental_column_auto_preview(columns, pk_columns)
        computed_protected = set(
            resolve_protected_columns(
                columns=columns,
                predicted_incremental_column=predicted_incremental_column,
                manual_protected=existing_protected_by_table.get(table_key, []) or [],
            )
        )

        for col in columns:
            src_name = col.get('name') or col.get('column_name')
            src_type = col.get('data_type', '')
            nullable = col.get('is_nullable', True)
            is_primary_key = bool(col.get("is_primary_key", False))
            is_incremental_column = (
                bool(predicted_incremental_column)
                and src_name == predicted_incremental_column
            )
            src_lower = (src_name or "").lower()

            # Default: assume same type on target
            target_type_display = src_type

            # Special handling for Oracle targets to match FullSyncExecutor behaviour
            if target_db_type == 'oracle':
                try:
                    _, max_len, prec, scale = normalize_data_type(src_type, source_db_type)
                    target_type_display = map_source_to_oracle_type(
                        src_type,
                        source_db_type,
                        max_length=col.get('max_length') or max_len,
                        precision=prec,
                        scale=scale,
                    )
                except Exception as map_err:
                    logger.warning(
                        "Type mapping preview failed for %s.%s (%s): %s",
                        table_key,
                        src_name,
                        src_type,
                        map_err,
                    )

            # Allowed target type options
            allowed_target_types = compute_allowed_types(source_db_type, target_db_type, src_type)
            if target_type_display and target_type_display not in allowed_target_types:
                allowed_target_types.insert(0, target_type_display)

            # Apply existing override from session, if any (normalize to lowercase for keys)
            override_for_table = existing_overrides.get(table_key, {})
            override_value = override_for_table.get((src_name or "").lower())
            if override_value and override_value in allowed_target_types:
                target_type_display = override_value

            # Prefill target column rename input from session (only for non-protected columns).
            target_column_name = col.get('target_column_name') or src_name
            if not (is_primary_key or is_incremental_column):
                name_override_for_table = existing_name_overrides.get(table_key, {}) or {}
                name_override_value = name_override_for_table.get((src_name or "").lower())
                if name_override_value:
                    target_column_name = name_override_value

            is_protected = bool(is_primary_key or is_incremental_column or (src_lower in computed_protected))
            is_excluded = bool(src_lower in set(existing_excluded_by_table.get(table_key, []) or []))
            if is_protected:
                is_excluded = False

            mapped_columns.append(
                {
                    'name': src_name,
                    'source_type': src_type,
                    'target_type': target_type_display,
                    'nullable': nullable,
                    'allowed_target_types': allowed_target_types,
                    'is_primary_key': is_primary_key,
                    'is_incremental_column': is_incremental_column,
                    'target_column_name': target_column_name,
                    'is_protected': is_protected,
                    'is_excluded': is_excluded,
                }
            )

        table_mappings[table_key] = {
            'columns': mapped_columns,
        }

    context = {
        'job_name': job_name,
        'source_connection': source_connection,
        'source_file_connection': source_file_connection,
        'source_connection_type': source_connection_type,
        'target_connection': target_connection,
        'selected_tables': selected_tables,
        'table_mappings': table_mappings,
        'page_title': 'Review Data Type Mapping - Step 4',
        'is_mongo_source': is_mongo_source,
    }

    return render(request, 'sync_jobs/create_step3_mapping.html', context)


@login_required
@viewer_read_only_required
def create_job_step3_mapping_submit(request):
    """
    Handle Step 3 (mapping) submission.

    Parse per-column overrides, validate them, store in session, and move to Step 4.
    """
    if request.method != 'POST':
        return redirect('sync_jobs:create_step3')

    job_name = request.session.get('sync_job_name')
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
    target_connection_id = request.session.get('sync_job_target_connection_id')
    selected_tables = request.session.get('sync_job_selected_tables', [])

    if source_connection_type == 'api':
        return redirect('sync_jobs:create_step4')
    if source_connection_type == 'database' and not all([job_name, source_connection_id, target_connection_id, selected_tables]):
        messages.error(request, 'Please complete previous steps first.')
        return redirect('sync_jobs:create_step1')
    if source_connection_type == 'flat_file' and not all([job_name, source_file_connection_id, target_connection_id, selected_tables]):
        messages.error(request, 'Please complete previous steps first.')
        return redirect('sync_jobs:create_step1')
    if (
        source_connection_type == 'database'
        and not request.session.get('sync_job_skip_model_step')
        and not request.session.get('sync_job_transform_validated')
    ):
        messages.error(request, 'Complete the Model Data step first.')
        return redirect('sync_jobs:create_step3_model')

    from accounts.services.tenant_service import TenantService
    from core.type_mapping import normalize_data_type, map_source_to_oracle_type

    source_connection = None
    source_file_connection = None
    if source_connection_type == 'database':
        # Load connections again to recompute mappings and allowed types consistently
        try:
            src_qs = DatabaseConnection.objects.filter(is_active=True)
            user_src_conns = TenantService.get_queryset_for_user(src_qs, request.user)
            source_connection = user_src_conns.get(id=source_connection_id)
        except DatabaseConnection.DoesNotExist:
            messages.error(request, 'Source connection not found.')
            return redirect('sync_jobs:create_step1')
    else:
        try:
            file_qs = FileSourceConnection.objects.filter(is_active=True)
            user_file_sources = TenantService.get_queryset_for_user(file_qs, request.user)
            source_file_connection = user_file_sources.get(id=source_file_connection_id)
        except FileSourceConnection.DoesNotExist:
            messages.error(request, 'File source not found or inactive.')
            return redirect('sync_jobs:create_step2')

    try:
        tgt_qs = DatabaseConnection.objects.filter(is_active=True)
        user_tgt_conns = TenantService.get_queryset_for_user(tgt_qs, request.user)
        target_connection = user_tgt_conns.get(id=target_connection_id)
    except DatabaseConnection.DoesNotExist:
        messages.error(request, 'Target connection not found.')
        return redirect('sync_jobs:create_step1')

    def _normalize_db_type(conn) -> str:
        dbt = (getattr(conn, "db_type", "") or "").lower()
        if dbt == "oracle_adw":
            return "oracle"
        return dbt

    source_db_type = _normalize_db_type(source_connection) if source_connection else "flat_file"
    target_db_type = _normalize_db_type(target_connection)
    is_mongo_source = source_connection_type == "database" and source_db_type == "mongodb"

    def compute_allowed_types(src_db: str, tgt_db: str, src_type: str):
        t = (src_type or "").upper()
        if src_db == "mysql" and tgt_db == "oracle":
            if any(kw in t for kw in ["INT", "BIGINT", "SMALLINT", "MEDIUMINT", "TINYINT"]):
                return ["NUMBER(10)", "NUMBER(38)", "BINARY_DOUBLE", "VARCHAR2(50)", "VARCHAR2(100)"]
            if any(kw in t for kw in ["FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL"]):
                return ["BINARY_FLOAT", "BINARY_DOUBLE", "NUMBER(38,10)", "VARCHAR2(100)"]
            if any(kw in t for kw in ["CHAR", "TEXT", "CLOB", "JSON", "ENUM", "SET"]):
                return ["VARCHAR2(100)", "VARCHAR2(255)", "CLOB"]
            if any(kw in t for kw in ["DATE", "TIME", "TIMESTAMP", "YEAR", "DATETIME"]):
                return ["DATE", "TIMESTAMP", "VARCHAR2(50)"]
            if "TINYINT(1)" in t or t == "BOOLEAN" or t == "BOOL":
                return ["NUMBER(1)", "NUMBER(3)", "VARCHAR2(5)"]
        return [src_type] if src_type else []

    def _is_datetime_like(data_type: str) -> bool:
        dt = (data_type or "").lower()
        return any(token in dt for token in ["timestamp", "datetime", "date", "time"])

    def _is_numeric_like(data_type: str) -> bool:
        dt = (data_type or "").lower()
        return any(
            token in dt
            for token in [
                "int",
                "bigint",
                "serial",
                "number",
                "decimal",
                "numeric",
                "float",
                "double",
                "uint",
            ]
        )

    def _resolve_incremental_column_auto_preview(columns: list, pk_columns: list):
        by_name = {}
        for c in columns:
            cname = c.get("name") or c.get("column_name")
            if cname:
                by_name[cname.lower()] = c

        preferred_datetime_names = [
            "updated_at",
            "modified_at",
            "last_updated",
            "last_modified",
            "updatedon",
            "modifiedon",
            "update_date",
            "update_time",
            "updated_date",
            "modified_time",
            "modifieddate",
        ]

        for cname in preferred_datetime_names:
            col = by_name.get(cname)
            if col and _is_datetime_like(col.get("data_type", "")):
                return col.get("name") or col.get("column_name")

        for col in columns:
            if _is_datetime_like(col.get("data_type", "")):
                return col.get("name") or col.get("column_name")

        if pk_columns:
            pk_lower = {p.lower() for p in pk_columns if p}
            for col in columns:
                col_name = col.get("name") or col.get("column_name")
                if not col_name:
                    continue
                if col_name.lower() in pk_lower and _is_numeric_like(col.get("data_type", "")):
                    return col_name
            for col in columns:
                col_name = col.get("name") or col.get("column_name")
                if not col_name:
                    continue
                if col_name.lower() in pk_lower:
                    return col_name

        return None

    from sync_jobs.validators import validate_target_column_name, resolve_protected_columns

    # Build overrides from POST
    overrides: Dict[str, Dict[str, str]] = {}
    name_overrides: Dict[str, Dict[str, str]] = {}
    excluded_by_table: Dict[str, list] = {}
    protected_by_table: Dict[str, list] = {}
    errors = []

    for table_info in selected_tables:
        schema_name = table_info.get('schema_name')
        table_name = table_info.get('table_name')
        table_key = f"{schema_name}.{table_name}"

        if source_connection_type == 'flat_file':
            headers = request.session.get('sync_job_flat_file_headers', []) or []
            if not headers:
                messages.error(request, 'Flat-file header snapshot is missing. Please return to Step 2 preview.')
                return redirect('sync_jobs:create_step2')
            columns = [
                {'name': h, 'column_name': h, 'data_type': 'string', 'is_nullable': True, 'is_primary_key': False}
                for h in headers
            ]
        else:
            try:
                columns = _load_columns_for_mapping_step(
                    request,
                    source_connection=source_connection,
                    source_connection_type=source_connection_type,
                    table_info=table_info,
                    user=request.user,
                )
            except Exception as e:
                logger.warning("Failed to load columns for %s when saving overrides: %s", table_key, e)
                continue

        # For MongoDB sources, the "type override" UI is hidden (inferred logical types
        # are mapped via core.type_mapping at runtime). Ignore any posted override_type_*.
        if not is_mongo_source:
            for col in columns:
                src_name = col.get('name') or col.get('column_name')
                src_type = col.get('data_type', '')
                field_name = f"override_type_{table_key}.{src_name}"
                chosen = (request.POST.get(field_name, "") or "").strip()
                if not chosen:
                    continue

                allowed = compute_allowed_types(source_db_type, target_db_type, src_type)
                # If mapping view had augmented allowed list (e.g. default), also accept that
                if src_type and src_type not in allowed:
                    allowed.append(src_type)

                if chosen not in allowed:
                    errors.append(f"Invalid type '{chosen}' for {table_key}.{src_name}")
                    continue

                col_key = (src_name or "").lower()
                overrides.setdefault(table_key, {})[col_key] = chosen

        # Parse target column name overrides (Step 3 rename).
        pk_columns = []
        for col in columns:
            if col.get("is_primary_key"):
                pk_columns.append(col.get("name") or col.get("column_name"))

        predicted_incremental_column = _resolve_incremental_column_auto_preview(columns, pk_columns)

        manual_protected = []
        for col in columns:
            src_name = col.get('name') or col.get('column_name')
            if not src_name:
                continue
            protected_field_name = f"protect_col_{table_key}.{src_name}"
            if request.POST.get(protected_field_name):
                manual_protected.append(src_name)

        resolved_protected = set(
            resolve_protected_columns(
                columns=columns,
                predicted_incremental_column=predicted_incremental_column,
                manual_protected=manual_protected,
            )
        )
        protected_by_table[table_key] = sorted(resolved_protected)

        final_target_names_by_src_lower = {}
        final_target_names_list_lower = []
        excluded_cols_for_table = set()

        for col in columns:
            src_name = col.get('name') or col.get('column_name')
            src_lower = (src_name or "").lower()
            if not src_lower:
                continue

            is_primary_key = bool(col.get("is_primary_key", False))
            is_incremental_column = bool(predicted_incremental_column) and (src_name == predicted_incremental_column)
            protected = src_lower in resolved_protected

            override_field_name = f"override_colname_{table_key}.{src_name}"
            provided = override_field_name in request.POST

            chosen_colname_raw = request.POST.get(override_field_name, "")
            chosen_colname = (chosen_colname_raw or "").strip()

            if not provided:
                # Field absent (likely disabled).
                final_name = src_name
            elif not chosen_colname:
                # User submitted an empty/whitespace name -> invalid.
                errors.append(f"Target Column Name cannot be empty for {table_key}.{src_name}")
                final_name = src_name
            else:
                if protected:
                    if chosen_colname.lower() != src_name.lower():
                        errors.append(
                            f"Renaming protected column is not allowed: {table_key}.{src_name} -> '{chosen_colname}'"
                        )
                    final_name = src_name
                else:
                    try:
                        validate_target_column_name(chosen_colname)
                    except ValidationError as exc:
                        errors.append(
                            f"Invalid Target Column Name for {table_key}.{src_name}: {str(exc)}"
                        )
                        final_name = src_name
                    else:
                        final_name = chosen_colname

            final_target_names_by_src_lower[src_lower] = final_name
            final_target_names_list_lower.append(final_name.lower())

            migrate_field_name = f"migrate_col_{table_key}.{src_name}"
            migrate_present_name = f"migrate_present_{table_key}.{src_name}"
            if migrate_present_name in request.POST:
                should_migrate = bool(request.POST.get(migrate_field_name))
            else:
                # Backward-compatible fallback for tests/older payloads.
                should_migrate = True
            if protected and not should_migrate:
                errors.append(f"Protected column cannot be excluded: {table_key}.{src_name}")
            if not protected and not should_migrate:
                excluded_cols_for_table.add(src_lower)

        # Duplicate detection (case-insensitive) within the table.
        seen = set()
        duplicates = set()
        for nm_lower in final_target_names_list_lower:
            if nm_lower in seen:
                duplicates.add(nm_lower)
            seen.add(nm_lower)
        if duplicates:
            errors.append(
                f"Duplicate Target Column Names are not allowed for {table_key}: {', '.join(sorted(duplicates))}"
            )

        if len(excluded_cols_for_table) >= len(columns):
            errors.append(f"At least one column must be migrated for {table_key}")
        if not errors:
            excluded_by_table[table_key] = sorted(excluded_cols_for_table)

        # Store only actual changes (change detection).
        if not duplicates and not errors:
            for col in columns:
                src_name = col.get('name') or col.get('column_name')
                if not src_name:
                    continue
                src_lower = src_name.lower()
                final_name = final_target_names_by_src_lower.get(src_lower, src_name)
                if final_name.lower() != src_lower:
                    name_overrides.setdefault(table_key, {})[src_lower] = final_name

    if errors:
        messages.error(request, " ; ".join(errors))
        return redirect('sync_jobs:create_step3')

    request.session['sync_job_column_type_overrides'] = overrides
    request.session['sync_job_column_name_overrides'] = name_overrides
    request.session['sync_job_excluded_columns'] = excluded_by_table
    request.session['sync_job_protected_columns'] = protected_by_table
    return redirect('sync_jobs:create_step4')


@login_required
def create_job_step4_view(request):
    """
    Step 4: Sync type and scheduling configuration
    Supports database, API, and flat-file sources.
    """
    # Get data from session
    job_name = request.session.get('sync_job_name')
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    source_api_connection_id = request.session.get('sync_job_source_api_connection_id')
    source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
    target_connection_id = request.session.get('sync_job_target_connection_id')
    selected_tables = request.session.get('sync_job_selected_tables', [])
    flat_file_headers = request.session.get('sync_job_flat_file_headers', []) or []
    ff_mode_defaults = request.session.get('sync_job_flat_file_incremental_mode', {}) or {}
    ff_hash_cols_defaults = request.session.get('sync_job_flat_file_hash_columns', {}) or {}
    ff_hash_algo_defaults = request.session.get('sync_job_flat_file_hash_algorithm', {}) or {}
    ff_hash_only_defaults = request.session.get('sync_job_flat_file_allow_hash_only_without_key', {}) or {}
    
    # Validate session data based on source type
    if source_connection_type == 'api':
        if not all([job_name, source_api_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Please complete previous steps first.')
            return redirect('sync_jobs:create_step1')
    elif source_connection_type == 'database':
        if not all([job_name, source_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Please complete previous steps first.')
            return redirect('sync_jobs:create_step1')
        if (
            not request.session.get('sync_job_skip_model_step')
            and not request.session.get('sync_job_transform_validated')
        ):
            messages.info(request, 'Complete the Model Data step before scheduling.')
            return redirect('sync_jobs:create_step3_model')
    else:
        if not all([job_name, source_file_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Please complete previous steps first.')
            return redirect('sync_jobs:create_step1')
    
    from accounts.services.tenant_service import TenantService
    
    # Load column information for each table (only for database sources)
    # For API sources, incremental sync uses Modified_Time from API, no column selection needed
    table_columns = {}
    source_connection = None
    source_api_connection = None
    source_file_connection = None
    
    if source_connection_type == 'api':
        # API source - no column loading needed
        try:
            api_qs = APIConnection.objects.filter(is_active=True)
            user_api_conns = TenantService.get_queryset_for_user(api_qs, request.user)
            source_api_connection = user_api_conns.get(id=source_api_connection_id)
        except APIConnection.DoesNotExist:
            messages.error(request, 'Source API connection not found.')
            return redirect('sync_jobs:create_step1')
    elif source_connection_type == 'database':
        # Database source - load column information
        try:
            conn_qs = DatabaseConnection.objects.filter(is_active=True)
            user_conns = TenantService.get_queryset_for_user(conn_qs, request.user)
            source_connection = user_conns.get(id=source_connection_id)
        except DatabaseConnection.DoesNotExist:
            messages.error(request, 'Source connection not found.')
            return redirect('sync_jobs:create_step1')
        
        # Load column information for each table (for incremental column selection)
        if selected_tables:
            for table_info in selected_tables:
                schema_name = table_info.get('schema_name')
                table_name = table_info.get('table_name')
                try:
                    columns = _load_columns_for_mapping_step(
                        request,
                        source_connection=source_connection,
                        source_connection_type=source_connection_type,
                        table_info=table_info,
                        user=request.user,
                    )
                    # Filter to date/timestamp columns and integer columns (for incremental sync)
                    # Supports: PostgreSQL, MySQL, SQL Server, and ClickHouse types
                    incremental_candidates = []
                    for col in columns:
                        data_type_lower = col['data_type'].lower()
                        # Standard types (PostgreSQL, MySQL, SQL Server)
                        if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                            incremental_candidates.append(col)
                        elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                            incremental_candidates.append(col)
                        # ClickHouse-specific types (DateTime64, UInt32, UInt64)
                        # Note: ClickHouse Int32, Int64 are already covered by 'int' check above
                        elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                            incremental_candidates.append(col)
                    
                    table_columns[f"{schema_name}.{table_name}"] = {
                        'all_columns': columns,
                        'incremental_candidates': incremental_candidates
                    }
                except Exception as e:
                    # If column loading fails, continue without it
                    table_columns[f"{schema_name}.{table_name}"] = {
                        'all_columns': [],
                        'incremental_candidates': []
                    }
    else:
        try:
            file_qs = FileSourceConnection.objects.filter(is_active=True)
            user_file_sources = TenantService.get_queryset_for_user(file_qs, request.user)
            source_file_connection = user_file_sources.get(id=source_file_connection_id)
        except FileSourceConnection.DoesNotExist:
            messages.error(request, 'File source not found.')
            return redirect('sync_jobs:create_step1')
    
    is_sap = source_api_connection and source_api_connection.api_type == 'sap_b1'
    
    context = {
        'job_name': job_name,
        'source_connection_type': source_connection_type,
        'source_connection': source_connection,
        'source_api_connection': source_api_connection,
        'source_file_connection': source_file_connection,
        'selected_tables': selected_tables,
        'table_columns': table_columns,
        'flat_file_headers': flat_file_headers,
        'flat_file_incremental_mode_defaults': ff_mode_defaults,
        'flat_file_hash_columns_defaults': ff_hash_cols_defaults,
        'flat_file_hash_algorithm_defaults': ff_hash_algo_defaults,
        'flat_file_allow_hash_only_defaults': ff_hash_only_defaults,
        'is_sap': is_sap,
        'page_title': 'Configure Sync - Step 5',
    }
    
    return render(request, 'sync_jobs/create_step3.html', context)


@login_required
@viewer_read_only_required
def create_job_step4_submit(request):
    """
    Handle Step 3 form submission and create the sync job
    """
    if request.method != 'POST':
        return redirect('sync_jobs:create_step4')
    
    # Get data from session
    job_name = request.session.get('sync_job_name')
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    source_api_connection_id = request.session.get('sync_job_source_api_connection_id')
    source_file_connection_id = request.session.get('sync_job_source_file_connection_id')
    target_connection_id = request.session.get('sync_job_target_connection_id')
    selected_tables = request.session.get('sync_job_selected_tables', [])
    
    # Validate session data based on source type
    if source_connection_type == 'api':
        if not all([job_name, source_api_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Session expired. Please start over.')
            return redirect('sync_jobs:create_step1')
    elif source_connection_type == 'database':
        if not all([job_name, source_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Session expired. Please start over.')
            return redirect('sync_jobs:create_step1')
        if (
            not request.session.get('sync_job_skip_model_step')
            and not request.session.get('sync_job_transform_validated')
        ):
            messages.error(request, 'Complete the Model Data step first.')
            return redirect('sync_jobs:create_step3_model')
    else:
        if not all([job_name, source_file_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Session expired. Please start over.')
            return redirect('sync_jobs:create_step1')
    
    # Get form data
    sync_type = request.POST.get('sync_type', 'full')
    schedule_type = request.POST.get('schedule_type', 'once')
    cron_expression = request.POST.get('cron_expression', '').strip()
    start_datetime = request.POST.get('start_datetime', '').strip()
    start_date = request.POST.get('start_date', '').strip()
    start_time = request.POST.get('start_time', '').strip()
    interval_hours_raw = request.POST.get('interval_hours', '').strip()
    target_table_prefix = request.POST.get('target_table_prefix', '').strip()
    overlap_seconds_raw = request.POST.get('incremental_overlap_seconds', '').strip()
    no_delete_raw = request.POST.get('no_delete_propagation', None)
    flat_file_mode_posted = {}
    flat_file_hash_cols_posted = {}
    flat_file_hash_algo_posted = {}
    # Backward-compatible default when UI control is absent.
    no_delete_propagation = True if no_delete_raw is None else str(no_delete_raw).lower() in (
        '1', 'true', 'yes', 'on'
    )
    
    # Enhanced validation
    errors = []

    # Parse flat-file hybrid incremental options (per table).
    if source_connection_type == 'flat_file':
        for t in selected_tables:
            tk = f"{t.get('schema_name')}.{t.get('table_name')}"
            mode_val = (request.POST.get(f"flat_file_incremental_mode_{tk}", "") or "").strip()
            if mode_val not in ("", "hybrid_hash_control"):
                errors.append(f"Invalid flat-file incremental mode for {tk}: {mode_val}")
                continue
            if not mode_val:
                mode_val = "hybrid_hash_control"
            flat_file_mode_posted[tk] = mode_val

            algo_val = (request.POST.get(f"flat_file_hash_algorithm_{tk}", "") or "").strip().lower()
            if not algo_val:
                algo_val = "sha256"
            if algo_val not in ("md5", "sha1", "sha256", "sha512"):
                errors.append(f"Invalid flat-file hash algorithm for {tk}: {algo_val}")
            flat_file_hash_algo_posted[tk] = algo_val

            cols_raw = (request.POST.get(f"flat_file_hash_columns_{tk}", "") or "").strip()
            parsed_cols = []
            if cols_raw:
                for c in cols_raw.split(","):
                    cs = (c or "").strip()
                    if cs:
                        parsed_cols.append(cs)
            flat_file_hash_cols_posted[tk] = parsed_cols
    
    # Target table prefix validation (optional; if provided: alphanumeric + underscore only, max 64)
    if target_table_prefix:
        if len(target_table_prefix) > 64:
            errors.append('Target table prefix must be at most 64 characters.')
        elif not re.match(r'^[a-zA-Z0-9_]+$', target_table_prefix):
            errors.append('Target table prefix may only contain letters, numbers, and underscores.')
    
    # Sync type validation
    try:
        from sync_jobs.validators import validate_sync_type
        sync_type = validate_sync_type(sync_type)
    except ValidationError as e:
        errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    if source_connection_type == 'database' and sync_type == 'incremental' and not no_delete_propagation:
        errors.append('Incremental database sync requires no-delete propagation policy to be enabled.')
    if source_connection_type == 'flat_file' and sync_type == 'incremental' and not no_delete_propagation:
        errors.append('Incremental flat-file sync requires no-delete propagation policy to be enabled.')
    
    # Schedule type validation
    try:
        from sync_jobs.validators import validate_schedule_type
        schedule_type = validate_schedule_type(schedule_type)
    except ValidationError as e:
        errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    
    interval_hours_val = 1
    if not errors:
        try:
            from sync_jobs.validators import validate_interval_hours
            interval_hours_val = validate_interval_hours(interval_hours_raw, schedule_type)
        except ValidationError as e:
            errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])

    overlap_seconds_val = 120
    if not errors and source_connection_type in ('database', 'flat_file') and sync_type == 'incremental':
        try:
            from sync_jobs.validators import validate_incremental_overlap_seconds
            overlap_seconds_val = validate_incremental_overlap_seconds(overlap_seconds_raw)
        except ValidationError as e:
            errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    
    # Cron expression validation (if custom schedule)
    if schedule_type == 'custom':
        try:
            from sync_jobs.validators import validate_cron_expression
            cron_expression = validate_cron_expression(cron_expression)
        except ValidationError as e:
            errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    
    # Start datetime validation (combined field and/or date + time)
    try:
        from sync_jobs.validators import validate_schedule_start_inputs
        start_datetime_obj = validate_schedule_start_inputs(
            start_datetime, start_date, start_time, schedule_type
        )
    except ValidationError as e:
        errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
        start_datetime_obj = None
    else:
        start_datetime_obj = start_datetime_obj if start_datetime_obj else None
    
    # Incremental columns are auto-resolved at execution time for database sources.
    incremental_columns = {}

    # Source-type-specific incremental contract checks (Day 1 scoped).
    if source_connection_type == 'database' and sync_type == 'incremental':
        plans = request.session.get('sync_job_transform_plan') or {}
        for t in selected_tables:
            tk = f"{t.get('schema_name')}.{t.get('table_name')}"
            p = plans.get(tk)
            if not isinstance(p, dict):
                continue
            mode = (p.get('mode') or 'single_table').strip().lower()
            if mode == 'union':
                errors.append(
                    f"Incremental contract rejected for {tk}: UNION model transforms are not supported in incremental mode."
                )
    if source_connection_type == 'flat_file' and sync_type == 'incremental':
        protected_by_table = request.session.get('sync_job_protected_columns', {}) or {}
        for t in selected_tables:
            tk = f"{t.get('schema_name')}.{t.get('table_name')}"
            stable_keys = protected_by_table.get(tk) or []
            has_stable_keys = isinstance(stable_keys, (list, tuple)) and bool(
                [k for k in stable_keys if str(k).strip()]
            )
            if not has_stable_keys:
                errors.append(
                    f"Incremental contract rejected for {tk}: select at least one Protected column "
                    f"to use as stable upsert key."
                )
    
    if errors:
        for error in errors:
            messages.error(request, error)
        # Validation errors return user to Step 4 (configure) to fix inputs
        request.session['sync_job_flat_file_incremental_mode'] = flat_file_mode_posted
        request.session['sync_job_flat_file_hash_columns'] = flat_file_hash_cols_posted
        request.session['sync_job_flat_file_hash_algorithm'] = flat_file_hash_algo_posted
        return redirect('sync_jobs:create_step4')
    
    try:
        # Get connections based on source type
        from accounts.services.tenant_service import TenantService
        
        # Target connection is always database
        db_qs = DatabaseConnection.objects.filter(is_active=True)
        user_db_conns = TenantService.get_queryset_for_user(db_qs, request.user)
        target_connection = user_db_conns.get(id=target_connection_id)
        
        # Source connection depends on type
        source_connection = None
        source_api_connection = None
        source_file_connection = None
        if source_connection_type == 'api':
            api_qs = APIConnection.objects.filter(is_active=True)
            user_api_conns = TenantService.get_queryset_for_user(api_qs, request.user)
            source_api_connection = user_api_conns.get(id=source_api_connection_id)
        elif source_connection_type == 'database':
            source_connection = user_db_conns.get(id=source_connection_id)
        else:
            file_qs = FileSourceConnection.objects.filter(is_active=True)
            user_file_conns = TenantService.get_queryset_for_user(file_qs, request.user)
            source_file_connection = user_file_conns.get(id=source_file_connection_id)
        
        # Calculate next_run_at based on schedule
        next_run_at = None
        if schedule_type != 'once':
            next_run_at = start_datetime_obj
            # Adjust for schedule type (preserve wall time from Step 4; roll forward until after now)
            from scheduler.utils import normalize_initial_next_run_for_schedule
            if schedule_type == 'hourly':
                next_run_at = normalize_initial_next_run_for_schedule(
                    'hourly', next_run_at, interval_hours=interval_hours_val
                )
            elif schedule_type == 'daily':
                next_run_at = normalize_initial_next_run_for_schedule('daily', next_run_at)
            elif schedule_type == 'weekly':
                next_run_at = normalize_initial_next_run_for_schedule('weekly', next_run_at)
        
        # Get tenant for the job
        from accounts.services.tenant_service import TenantService
        tenant = TenantService.get_user_tenant(request.user)
        
        # Validate tenant is not None (Super Admin shouldn't create data)
        if tenant is None:
            messages.error(
                request,
                "Super Admin cannot create jobs. Please use an Admin account."
            )
            return redirect('sync_jobs:create_step1')
        
        # Create SyncJob
        sync_job = SyncJob.objects.create(
            name=job_name,
            source_connection=source_connection,  # None for API sources
            source_api_connection=source_api_connection,  # None for database sources
            source_file_connection=source_file_connection,  # None for db/api sources
            source_connection_type=source_connection_type,
            target_connection=target_connection,
            sync_type=sync_type,
            no_delete_propagation=no_delete_propagation,
            incremental_overlap_seconds=overlap_seconds_val,
            status='pending',
            created_by=request.user,
            tenant=tenant,
            next_run_at=next_run_at,
            target_table_prefix=target_table_prefix or None
        )
        
        # Get transformation data from session (only for database sources)
        table_transformations = request.session.get('sync_job_table_transformations', {})
        
        # Create SyncJobTable entries
        overrides_by_table = request.session.get('sync_job_column_type_overrides', {})
        name_overrides_by_table = request.session.get('sync_job_column_name_overrides', {}) or {}
        excluded_by_table = request.session.get('sync_job_excluded_columns', {}) or {}
        protected_by_table = request.session.get('sync_job_protected_columns', {}) or {}
        transform_plans_by_table = request.session.get('sync_job_transform_plan') or {}
        for table_info in selected_tables:
            table_key = f"{table_info['schema_name']}.{table_info['table_name']}"
            
            # Incremental column is auto-resolved at runtime (DB) or API-driven (API).
            incremental_column = None
            incremental_key_columns = []
            
            # Get transformation data for this table (only for database sources)
            transformation_query = None
            column_transformations = {}
            if source_connection_type == 'database':
                transformation_data = table_transformations.get(table_key, {})
                transformation_query = transformation_data.get('where_clause', None)
                column_transformations = transformation_data.get('column_transformations', {})
                
                # Ensure column_transformations is a dict or None
                if column_transformations and not isinstance(column_transformations, dict):
                    logger.warning(f"Invalid column_transformations format for {table_key}, converting to dict")
                    column_transformations = {}
                
                # Clean up transformation_query - remove None/empty strings
                if transformation_query:
                    transformation_query = transformation_query.strip()
                    if not transformation_query:
                        transformation_query = None
                # Same stable-key contract as flat-file: persist Step 3 protected columns for upsert.
                if sync_type == 'incremental':
                    stable_keys = protected_by_table.get(table_key) or []
                    if isinstance(stable_keys, (list, tuple)):
                        incremental_key_columns = [
                            str(k).strip() for k in stable_keys if str(k).strip()
                        ]
            elif source_connection_type == 'flat_file' and sync_type == 'incremental':
                stable_keys = protected_by_table.get(table_key) or []
                if isinstance(stable_keys, (list, tuple)):
                    incremental_key_columns = [
                        str(k).strip() for k in stable_keys if str(k).strip()
                    ]
            
            table_key = f"{table_info['schema_name']}.{table_info['table_name']}"
            SyncJobTable.objects.create(
                job=sync_job,
                schema_name=table_info['schema_name'],
                table_name=table_info['table_name'],
                incremental_column=incremental_column,
                incremental_key_columns=incremental_key_columns,
                transformation_query=transformation_query,
                column_transformations=column_transformations if column_transformations else {},
                column_type_overrides=overrides_by_table.get(table_key, {}),
                column_name_overrides=name_overrides_by_table.get(table_key, {}),
                excluded_columns=excluded_by_table.get(table_key, []),
                protected_columns=protected_by_table.get(table_key, []),
                transform_plan=transform_plans_by_table.get(table_key),
                flat_file_incremental_mode=(
                    flat_file_mode_posted.get(table_key, "legacy_mtime")
                    if source_connection_type == "flat_file"
                    else "legacy_mtime"
                ),
                flat_file_hash_columns=(
                    flat_file_hash_cols_posted.get(table_key, [])
                    if source_connection_type == "flat_file"
                    else []
                ),
                flat_file_hash_algorithm=(
                    flat_file_hash_algo_posted.get(table_key, "sha256")
                    if source_connection_type == "flat_file"
                    else "sha256"
                ),
                flat_file_allow_hash_only_without_key=False,
                is_enabled=True
            )
        
        # Create APISyncState entries for API sources with incremental sync
        if source_connection_type == 'api' and sync_type == 'incremental':
            from sync_jobs.models import APISyncState
            for table_info in selected_tables:
                module_name = table_info['table_name']  # For API, table_name is module name
                APISyncState.objects.create(
                    job=sync_job,
                    module_name=module_name,
                    last_sync_time=None,  # Will be set on first sync
                    last_modified_time=None,
                    records_synced=0
                )
        
        # Create SyncSchedule
        try:
            schedule = SyncSchedule.objects.create(
                job=sync_job,
                tenant=sync_job.tenant,  # Inherit from job
                schedule_type=schedule_type,
                cron_expression=cron_expression if schedule_type == 'custom' else None,
                interval_hours=interval_hours_val,
                is_enabled=True,
                next_run_at=next_run_at
            )
            logger.info(f"Created schedule {schedule.id} for job {sync_job.id}")
            
            # Calculate and set next_run_at using scheduler utility
            from scheduler.utils import schedule_job_execution
            try:
                schedule_job_execution(sync_job)
                logger.info(f"Calculated next_run_at for job {sync_job.id}: {sync_job.next_run_at}")
            except Exception as e:
                logger.error(f"Error calculating next_run_at: {str(e)}", exc_info=True)
                # Don't fail job creation, just log error
            
            # Register job with scheduler service
            try:
                from scheduler.service import add_job_schedule
                add_job_schedule(sync_job)
                logger.info(f"Registered job {sync_job.id} with scheduler service")
            except Exception as e:
                logger.error(f"Error registering job with scheduler: {str(e)}", exc_info=True)
                # Don't fail job creation, scheduler will pick it up on next check
        except Exception as e:
            logger.error(f"Error creating schedule for job {sync_job.id}: {str(e)}", exc_info=True)
            # Don't fail the whole job creation if schedule creation fails
            # Schedule can be added later
            pass
        
        # Clear session data
        request.session.pop('sync_job_name', None)
        request.session.pop('sync_job_source_connection_id', None)
        request.session.pop('sync_job_source_api_connection_id', None)
        request.session.pop('sync_job_source_file_connection_id', None)
        request.session.pop('sync_job_target_connection_id', None)
        request.session.pop('sync_job_selected_tables', None)
        request.session.pop('sync_job_column_name_overrides', None)
        request.session.pop('sync_job_excluded_columns', None)
        request.session.pop('sync_job_protected_columns', None)
        request.session.pop('sync_job_transform_plan', None)
        request.session.pop('sync_job_transform_validated', None)
        request.session.pop('sync_job_transform_preview_cache', None)
        request.session.pop('sync_job_flat_file_incremental_mode', None)
        request.session.pop('sync_job_flat_file_hash_columns', None)
        request.session.pop('sync_job_flat_file_hash_algorithm', None)
        
        messages.success(request, f'Sync job "{job_name}" created successfully!')
        logger.info(f"User {request.user.username} created sync job {sync_job.id}: {job_name}")
        
        # If schedule type is 'once', automatically start the sync execution asynchronously
        if schedule_type == 'once':
            try:
                import threading
                from sync_engine.executor import SyncExecutor
                
                logger.info(
                    f"Auto-starting 'once' schedule job {sync_job.id} for user {request.user.username} (async)"
                )
                
                # Execute asynchronously in a background thread
                def run_sync_async():
                    try:
                        executor = SyncExecutor(sync_job)
                        executor.execute()
                        logger.info(f"Async execution completed for job {sync_job.id}")
                    except Exception as e:
                        logger.error(f"Failed to execute job {sync_job.id} in background: {str(e)}", exc_info=True)
                
                # Start the sync in a background thread
                thread = threading.Thread(target=run_sync_async, daemon=True)
                thread.start()
                
                # Immediately redirect to job detail page (don't wait for sync to complete)
                messages.success(
                    request,
                    f'Job "{job_name}" created and started! You can monitor the progress on the job detail page.'
                )
                return redirect('sync_jobs:job_detail', job_id=sync_job.id)
            except Exception as e:
                logger.error(f"Failed to auto-start job execution: {str(e)}", exc_info=True)
                # Don't fail the job creation, just log the error
                messages.warning(request, f'Job "{job_name}" created, but automatic execution failed: {str(e)}. You can run it manually.')
                return redirect('sync_jobs:job_detail', job_id=sync_job.id)
        
        return redirect('sync_jobs:job_detail', job_id=sync_job.id)
        
    except DatabaseConnection.DoesNotExist:
        logger.error(f"Connection not found for user {request.user.username}")
        messages.error(request, 'Connection not found.')
        return redirect('sync_jobs:create_step1')
    except IntegrityError as e:
        logger.error(f"Integrity error creating sync job: {str(e)}", exc_info=True)
        messages.error(request, 'Error creating sync job. A job with this configuration may already exist.')
        return redirect('sync_jobs:create_step3')
    except DatabaseError as e:
        import traceback
        error_detail = str(e)
        logger.error(f"Database error creating sync job: {error_detail}", exc_info=True)
        logger.error(f"Full traceback: {traceback.format_exc()}")
        
        # Check if it's a unique constraint violation
        if 'unique' in error_detail.lower() or 'duplicate' in error_detail.lower():
            messages.error(request, 'A job with this configuration already exists. Please use a different name or configuration.')
        else:
            messages.error(request, f'Database error occurred: {error_detail}. Please check server logs for details.')
        
        return redirect('sync_jobs:create_step3')
    except Exception as e:
        logger.error(f"Unexpected error creating sync job: {str(e)}", exc_info=True)
        messages.error(request, f'Error creating sync job: {str(e)}')
        return redirect('sync_jobs:create_step3')


@login_required
def job_detail(request, job_id):
    """Detailed view for a sync job with execution history"""
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.select_related(
            'source_connection', 'source_api_connection', 'target_connection', 'schedule', 'created_by', 'tenant'
        ).prefetch_related('tables', 'checkpoints')
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        logger.warning(f"User {request.user.username} attempted to access non-existent job {job_id}")
        return redirect('sync_jobs:list')
    except Exception as e:
        logger.error(f"Error loading job detail: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while loading the job.')
        return redirect('sync_jobs:list')
    
    # Get execution history (last 20 executions)
    executions = SyncExecution.objects.filter(
        job=job
    ).select_related('job').prefetch_related('logs').order_by('-started_at')[:20]
    
    # Get latest execution for quick status
    latest_execution = executions.first() if executions else None
    
    # Calculate statistics
    total_executions = SyncExecution.objects.filter(job=job).count()
    successful_executions = SyncExecution.objects.filter(job=job, status='completed').count()
    failed_executions = SyncExecution.objects.filter(job=job, status='failed').count()
    
    # Get total rows synced across all executions
    from django.db.models import Sum
    total_rows_synced_all_time = SyncExecution.objects.filter(
        job=job
    ).aggregate(total=Sum('total_rows_synced'))['total'] or 0
    
    # Get checkpoints and create a mapping for easy template access
    # Use string key format: "schema_name|table_name"
    checkpoints = SyncCheckpoint.objects.filter(job=job)
    checkpoint_map = {
        f"{cp.schema_name}|{cp.table_name}": cp 
        for cp in checkpoints
    }
    
    # Refresh next_run_at if it's outdated or missing (for scheduled jobs)
    try:
        if hasattr(job, 'schedule') and job.schedule and job.schedule.is_enabled:
            now = timezone.now()
            # If next_run_at is in the past or not set, recalculate it
            if not job.next_run_at or job.next_run_at <= now:
                from scheduler.utils import schedule_job_execution
                schedule_job_execution(job)
                job.refresh_from_db()  # Refresh to get updated next_run_at
                logger.debug(f"Refreshed next_run_at for job {job.id}: {job.next_run_at}")
    except Exception as e:
        logger.warning(f"Error refreshing next_run_at in job_detail view: {str(e)}")
    
    context = {
        'job': job,
        'executions': executions,
        'latest_execution': latest_execution,
        'total_executions': total_executions,
        'successful_executions': successful_executions,
        'failed_executions': failed_executions,
        'total_rows_synced_all_time': total_rows_synced_all_time,
        'checkpoint_map': checkpoint_map,
        'page_title': f'Job: {job.name}',
    }
    
    return render(request, 'sync_jobs/job_detail.html', context)


@login_required
@viewer_read_only_required
def job_delete(request, job_id):
    """
    Delete a sync job (with confirmation)
    """
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
        
        # Verify tenant ownership
        if not TenantService.can_user_manage_tenant(request.user, job.tenant):
            raise PermissionDenied("You don't have permission to delete this job.")
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        logger.warning(f"User {request.user.username} attempted to delete non-existent job {job_id}")
        return redirect('sync_jobs:list')
    except PermissionDenied:
        raise
    except Exception as e:
        logger.error(f"Error fetching job for deletion: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while loading the job.')
        return redirect('sync_jobs:list')
    
    if request.method == 'POST':
        try:
            job_name = job.name
            # Remove from scheduler before deleting
            try:
                from scheduler.service import remove_job_schedule
                remove_job_schedule(job)
            except Exception as e:
                logger.warning(f"Error removing job from scheduler before deletion: {str(e)}")
            
            job.delete()
            logger.info(f"User {request.user.username} deleted job {job_id}: {job_name}")
            messages.success(request, f'Sync job "{job_name}" deleted successfully.')
            return redirect('sync_jobs:list')
        except DatabaseError as e:
            logger.error(f"Database error while deleting job {job_id}: {str(e)}", exc_info=True)
            messages.error(request, 'An error occurred while deleting the job. Please try again.')
            return redirect('sync_jobs:job_detail', job_id=job_id)
        except Exception as e:
            logger.error(f"Unexpected error while deleting job {job_id}: {str(e)}", exc_info=True)
            messages.error(request, 'An unexpected error occurred. Please try again.')
            return redirect('sync_jobs:job_detail', job_id=job_id)
    
    context = {
        'job': job,
        'page_title': f'Delete Job: {job.name}',
    }
    return render(request, 'sync_jobs/job_confirm_delete.html', context)


@login_required
@viewer_read_only_required
def job_pause(request, job_id):
    """
    Pause a sync job
    """
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        logger.warning(f"User {request.user.username} attempted to pause non-existent job {job_id}")
        return redirect('sync_jobs:list')
    except Exception as e:
        logger.error(f"Error fetching job for pause: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while loading the job.')
        return redirect('sync_jobs:list')
    
    if job.status == 'running':
        messages.error(request, 'Cannot pause a running job. Please wait for it to complete.')
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    if job.status == 'paused':
        messages.info(request, 'Job is already paused.')
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    try:
        job.status = 'paused'
        job.save()
        
        # Disable schedule
        if hasattr(job, 'schedule') and job.schedule:
            job.schedule.is_enabled = False
            job.schedule.save(update_fields=['is_enabled'])
            logger.info(f"Disabled schedule for paused job {job.id}")
        
        logger.info(f"User {request.user.username} paused job {job_id}: {job.name}")
        messages.success(request, f'Job "{job.name}" paused successfully.')
    except DatabaseError as e:
        logger.error(f"Database error while pausing job {job_id}: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while pausing the job. Please try again.')
    except Exception as e:
        logger.error(f"Unexpected error while pausing job {job_id}: {str(e)}", exc_info=True)
        messages.error(request, 'An unexpected error occurred. Please try again.')
    
    return redirect('sync_jobs:job_detail', job_id=job_id)


@login_required
@viewer_read_only_required
def job_resume(request, job_id):
    """
    Resume a paused sync job
    """
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        logger.warning(f"User {request.user.username} attempted to resume non-existent job {job_id}")
        return redirect('sync_jobs:list')
    except Exception as e:
        logger.error(f"Error fetching job for resume: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while loading the job.')
        return redirect('sync_jobs:list')
    
    if job.status != 'paused':
        messages.error(request, 'Only paused jobs can be resumed.')
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    try:
        job.status = 'pending'
        job.save()
        
        # Re-enable schedule and recalculate next_run_at
        if hasattr(job, 'schedule') and job.schedule:
            from scheduler.utils import schedule_job_execution
            job.schedule.is_enabled = True
            job.schedule.save(update_fields=['is_enabled'])
            # Recalculate next run time
            try:
                schedule_job_execution(job)
                logger.info(f"Re-enabled schedule and recalculated next_run_at for job {job.id}")
            except Exception as e:
                logger.error(f"Error recalculating next_run_at on resume: {str(e)}", exc_info=True)
        
        logger.info(f"User {request.user.username} resumed job {job_id}: {job.name}")
        messages.success(request, f'Job "{job.name}" resumed successfully.')
    except DatabaseError as e:
        logger.error(f"Database error while resuming job {job_id}: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while resuming the job. Please try again.')
    except Exception as e:
        logger.error(f"Unexpected error while resuming job {job_id}: {str(e)}", exc_info=True)
        messages.error(request, 'An unexpected error occurred. Please try again.')
    
    return redirect('sync_jobs:job_detail', job_id=job_id)


@login_required
@viewer_read_only_required
def update_schedule(request, job_id):
    """
    Update schedule for a sync job
    """
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        return redirect('sync_jobs:list')
    
    if not hasattr(job, 'schedule') or not job.schedule:
        messages.error(request, 'Job does not have a schedule.')
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    if request.method == 'POST':
        schedule_type = request.POST.get('schedule_type')
        cron_expression = request.POST.get('cron_expression', '').strip()
        start_datetime = request.POST.get('start_datetime', '').strip()
        interval_hours_raw = request.POST.get('interval_hours', '').strip()
        is_enabled = request.POST.get('is_enabled') == 'on'
        
        # Validation
        errors = []
        if schedule_type not in ['once', 'hourly', 'daily', 'weekly', 'custom']:
            errors.append('Invalid schedule type.')
        
        if schedule_type == 'custom' and not cron_expression:
            errors.append('Cron expression is required for custom schedules.')
        
        interval_hours_val = 1
        if not errors:
            try:
                from sync_jobs.validators import validate_interval_hours
                interval_hours_val = validate_interval_hours(interval_hours_raw, schedule_type)
            except ValidationError as e:
                for msg in e.messages if hasattr(e, 'messages') else [str(e)]:
                    errors.append(msg)
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('sync_jobs:job_detail', job_id=job_id)
        
        # Update schedule
        from django.utils import timezone
        from datetime import timedelta
        from scheduler.utils import schedule_job_execution
        
        try:
            job.schedule.schedule_type = schedule_type
            job.schedule.cron_expression = cron_expression if schedule_type == 'custom' else None
            job.schedule.interval_hours = interval_hours_val
            job.schedule.is_enabled = is_enabled
            
            if start_datetime:
                try:
                    job.schedule.next_run_at = timezone.datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
                except Exception:
                    job.schedule.next_run_at = None
            else:
                job.schedule.next_run_at = None

            from scheduler.utils import normalize_initial_next_run_for_schedule
            if (
                is_enabled
                and job.schedule.next_run_at
                and schedule_type in ('hourly', 'daily')
            ):
                if schedule_type == 'hourly':
                    job.schedule.next_run_at = normalize_initial_next_run_for_schedule(
                        'hourly',
                        job.schedule.next_run_at,
                        interval_hours=job.schedule.interval_hours,
                    )
                else:
                    job.schedule.next_run_at = normalize_initial_next_run_for_schedule(
                        schedule_type, job.schedule.next_run_at
                    )
            
            job.schedule.save()
            
            # Recalculate next_run_at
            if is_enabled:
                schedule_job_execution(job)
            
            messages.success(request, 'Schedule updated successfully.')
            logger.info(f"Updated schedule for job {job.id} by user {request.user.username}")
        except Exception as e:
            logger.error(f"Error updating schedule: {str(e)}", exc_info=True)
            messages.error(request, f'Error updating schedule: {str(e)}')
    
    return redirect('sync_jobs:job_detail', job_id=job_id)


@login_required
@viewer_read_only_required
def job_edit(request, job_id):
    """
    Edit sync job configuration
    Allows editing:
    - Job name
    - Sync type (with validation)
    - Schedule configuration
    - Table incremental columns (if incremental)
    """
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.select_related(
            'source_connection', 'target_connection', 'schedule', 'tenant'
        ).prefetch_related('tables')
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
        
        # Verify tenant ownership
        if not TenantService.can_user_manage_tenant(request.user, job.tenant):
            raise PermissionDenied("You don't have permission to edit this job.")
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        return redirect('sync_jobs:list')
    except PermissionDenied:
        raise
    
    if job.status == 'running':
        messages.error(request, 'Cannot edit a running job. Please wait for it to complete.')
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    if request.method == 'POST':
        # Handle form submission
        job_name = request.POST.get('job_name', '').strip()
        sync_type = request.POST.get('sync_type', 'full')
        schedule_type = request.POST.get('schedule_type', 'once')
        cron_expression = request.POST.get('cron_expression', '').strip()
        start_datetime = request.POST.get('start_datetime', '').strip()
        start_date = request.POST.get('start_date', '').strip()
        start_time = request.POST.get('start_time', '').strip()
        interval_hours_raw = request.POST.get('interval_hours', '').strip()
        target_table_prefix = request.POST.get('target_table_prefix', '').strip()
        
        # Validation
        errors = []
        if not job_name:
            errors.append('Job name is required.')
        
        if sync_type not in ['full', 'incremental']:
            errors.append('Invalid sync type.')
        
        if target_table_prefix:
            if len(target_table_prefix) > 64:
                errors.append('Target table prefix must be at most 64 characters.')
            elif not re.match(r'^[a-zA-Z0-9_]+$', target_table_prefix):
                errors.append('Target table prefix may only contain letters, numbers, and underscores.')
        
        if schedule_type not in ['once', 'hourly', 'daily', 'weekly', 'custom']:
            errors.append('Invalid schedule type.')
        
        if schedule_type == 'custom' and not cron_expression:
            errors.append('Cron expression is required for custom schedules.')
        
        interval_hours_val = 1
        if not errors:
            try:
                from sync_jobs.validators import validate_interval_hours
                interval_hours_val = validate_interval_hours(interval_hours_raw, schedule_type)
            except ValidationError as e:
                for msg in e.messages if hasattr(e, 'messages') else [str(e)]:
                    errors.append(msg)
        
        start_datetime_obj = None
        if not errors:
            try:
                from sync_jobs.validators import validate_schedule_start_inputs
                start_datetime_obj = validate_schedule_start_inputs(
                    start_datetime, start_date, start_time, schedule_type
                )
            except ValidationError as e:
                for msg in e.messages if hasattr(e, 'messages') else [str(e)]:
                    errors.append(msg)
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            # Update job
            job.name = job_name
            job.sync_type = sync_type
            job.target_table_prefix = target_table_prefix or None
            job.save()
            
            # Update schedule
            try:
                schedule = job.schedule
            except SyncSchedule.DoesNotExist:
                schedule = SyncSchedule(job=job)
            
            schedule.schedule_type = schedule_type
            schedule.cron_expression = cron_expression if schedule_type == 'custom' else None
            
            # Calculate next_run_at based on schedule
            next_run_at = None
            if schedule_type != 'once':
                next_run_at = start_datetime_obj
                from scheduler.utils import normalize_initial_next_run_for_schedule
                if schedule_type == 'hourly':
                    next_run_at = normalize_initial_next_run_for_schedule(
                        'hourly', next_run_at, interval_hours=interval_hours_val
                    )
                elif schedule_type == 'daily':
                    next_run_at = normalize_initial_next_run_for_schedule('daily', next_run_at)
                elif schedule_type == 'weekly':
                    next_run_at = normalize_initial_next_run_for_schedule('weekly', next_run_at)
            
            schedule.interval_hours = interval_hours_val
            schedule.next_run_at = next_run_at
            job.next_run_at = next_run_at
            job.save()
            schedule.save()
            
            # Update scheduler with new schedule
            try:
                from scheduler.utils import schedule_job_execution
                schedule_job_execution(job)
                from scheduler.service import add_job_schedule
                add_job_schedule(job)
                logger.info(f"Updated scheduler for job {job.id}")
            except Exception as e:
                logger.error(f"Error updating scheduler for job {job.id}: {str(e)}", exc_info=True)
            
            # Do not require manual incremental columns in edit flow.
            # Keep previously stored values for incremental jobs; clear for full sync.
            if sync_type != 'incremental':
                job.tables.all().update(incremental_column=None)
            
            messages.success(request, f'Job "{job.name}" updated successfully.')
            
            # If schedule type is 'once', automatically start the sync execution synchronously
            if schedule_type == 'once' and job.status != 'running':
                try:
                    import threading
                    from sync_engine.executor import SyncExecutor
                    
                    logger.info(
                        f"Auto-starting 'once' schedule job {job.id} for user {request.user.username} (async)"
                    )
                    
                    # Execute asynchronously in a background thread
                    def run_sync_async():
                        try:
                            executor = SyncExecutor(job)
                            executor.execute()
                            logger.info(f"Async execution completed for job {job.id}")
                        except Exception as e:
                            logger.error(f"Failed to execute job {job.id} in background: {str(e)}", exc_info=True)
                    
                    # Start the sync in a background thread
                    thread = threading.Thread(target=run_sync_async, daemon=True)
                    thread.start()
                    
                    messages.success(
                        request,
                        f'Job "{job.name}" updated and started! You can monitor the progress on this page.'
                    )
                except Exception as e:
                    logger.error(f"Failed to auto-start job execution: {str(e)}", exc_info=True)
                    # Don't fail the job update, just log the error
                    messages.warning(request, f'Job "{job.name}" updated, but automatic execution failed: {str(e)}. You can run it manually.')
            
            return redirect('sync_jobs:job_detail', job_id=job_id)
    
    # Load column information for incremental column selection
    table_columns = {}
    is_sap = job.source_api_connection and job.source_api_connection.api_type == 'sap_b1'
    
    if (job.sync_type == 'incremental' or request.method == 'GET') and job.source_connection_type == 'database':
        for table in job.tables.all():
            try:
                columns = load_table_columns(
                    str(job.source_connection.id),
                    table.schema_name,
                    table.table_name,
                    request.user
                )
                # Filter to date/timestamp columns and integer columns (for incremental sync)
                # Supports: PostgreSQL, MySQL, SQL Server, and ClickHouse types
                incremental_candidates = []
                for col in columns:
                    data_type_lower = col['data_type'].lower()
                    # Standard types (PostgreSQL, MySQL, SQL Server)
                    if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                        incremental_candidates.append(col)
                    elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                        incremental_candidates.append(col)
                    # ClickHouse-specific types (DateTime64, UInt32, UInt64)
                    # Note: ClickHouse Int32, Int64 are already covered by 'int' check above
                    elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                        incremental_candidates.append(col)
                
                table_columns[f"{table.schema_name}.{table.table_name}"] = {
                    'all_columns': columns,
                    'incremental_candidates': incremental_candidates
                }
            except Exception:
                table_columns[f"{table.schema_name}.{table.table_name}"] = {
                    'all_columns': [],
                    'incremental_candidates': []
                }
    
    transform_summary_rows = []
    for table in job.tables.all():
        plan = getattr(table, "transform_plan", None) or {}
        if not isinstance(plan, dict):
            continue
        mode = (plan.get("mode") or "single_table").strip().lower()
        if mode in ("join", "union", "lookup"):
            transform_summary_rows.append(
                {
                    "table_key": f"{table.schema_name}.{table.table_name}",
                    "mode": mode,
                }
            )

    context = {
        'job': job,
        'table_columns': table_columns,
        'transform_summary_rows': transform_summary_rows,
        'is_sap': is_sap,
        'page_title': f'Edit Job: {job.name}',
    }
    
    return render(request, 'sync_jobs/job_edit.html', context)


@login_required
@viewer_read_only_required
def job_run_now(request, job_id):
    """Trigger immediate execution of a sync job"""
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        logger.warning(f"User {request.user.username} attempted to run non-existent job {job_id}")
        return redirect('sync_jobs:list')
    except Exception as e:
        logger.error(f"Error fetching job for run: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while loading the job.')
        return redirect('sync_jobs:list')
    
    if job.status == 'running':
        messages.error(request, 'Job is already running.')
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    if job.status == 'paused':
        messages.error(request, 'Cannot run a paused job. Please resume it first.')
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    # Execute sync asynchronously
    try:
        import threading
        from sync_engine.executor import SyncExecutor
        
        logger.info(
            f"User {request.user.username} triggered run for job {job_id}: {job.name} (async)"
        )
        
        # Execute asynchronously in a background thread
        def run_sync_async():
            try:
                executor = SyncExecutor(job)
                executor.execute()
                logger.info(f"Async execution completed for job {job_id}")
            except Exception as e:
                logger.error(f"Failed to execute job {job_id} in background: {str(e)}", exc_info=True)
        
        # Start the sync in a background thread
        thread = threading.Thread(target=run_sync_async, daemon=True)
        thread.start()
        
        messages.success(
            request,
            f'Job "{job.name}" started! You can monitor the progress on this page.'
        )
    except Exception as e:
        logger.error(f"Failed to start job execution: {str(e)}", exc_info=True)
        messages.error(request, f'Failed to start job: {str(e)}')
    
    return redirect('sync_jobs:job_detail', job_id=job_id)


@login_required
def execution_detail(request, job_id, execution_id):
    """Detailed view for a sync execution with per-table logs"""
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
        execution = SyncExecution.objects.prefetch_related(
            'logs'
        ).select_related('job').get(
            id=execution_id,
            job=job
        )
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        logger.warning(f"User {request.user.username} attempted to access non-existent job {job_id}")
        return redirect('sync_jobs:list')
    except SyncExecution.DoesNotExist:
        messages.error(request, 'Execution not found.')
        logger.warning(f"User {request.user.username} attempted to access non-existent execution {execution_id}")
        return redirect('sync_jobs:job_detail', job_id=job_id)
    except Exception as e:
        logger.error(f"Error loading execution detail: {str(e)}", exc_info=True)
        messages.error(
            request, 
            'An error occurred while loading the execution. Please try again or contact support if the problem persists.'
        )
        return redirect('sync_jobs:job_detail', job_id=job_id)
    
    # Get per-table logs ordered by started_at
    logs = execution.logs.all().order_by('started_at')
    
    # Calculate execution duration
    duration = None
    if execution.completed_at and execution.started_at:
        duration = execution.completed_at - execution.started_at
    elif execution.status == 'running' and execution.started_at:
        duration = timezone.now() - execution.started_at
    
    # Calculate statistics
    completed_logs = logs.filter(status='completed')
    failed_logs = logs.filter(status='failed')
    running_logs = logs.filter(status='running')
    pending_logs = logs.filter(status='pending')
    
    # Get total rows from all completed logs
    from django.db.models import Sum
    total_rows_fetched = logs.aggregate(total=Sum('rows_fetched'))['total'] or 0
    total_rows_inserted = logs.aggregate(total=Sum('rows_inserted'))['total'] or 0
    
    context = {
        'job': job,
        'execution': execution,
        'logs': logs,
        'duration': duration,
        'completed_logs': completed_logs,
        'failed_logs': failed_logs,
        'running_logs': running_logs,
        'pending_logs': pending_logs,
        'total_rows_fetched': total_rows_fetched,
        'total_rows_inserted': total_rows_inserted,
        'page_title': f'Execution: {execution.id}',
    }
    
    return render(request, 'sync_jobs/execution_detail.html', context)


@login_required
@require_http_methods(["GET"])
def execution_status_api(request, job_id, execution_id):
    """API endpoint for real-time execution status updates"""
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
        execution = SyncExecution.objects.prefetch_related('logs').get(
            id=execution_id,
            job=job
        )
    except SyncJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)
    except SyncExecution.DoesNotExist:
        return JsonResponse({'error': 'Execution not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in execution_status_api: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)
    
    # Get all logs ordered by started_at
    logs = execution.logs.all().order_by('started_at')
    
    # Calculate duration
    duration_seconds = None
    if execution.completed_at and execution.started_at:
        duration_seconds = (execution.completed_at - execution.started_at).total_seconds()
    elif execution.status == 'running' and execution.started_at:
        duration_seconds = (timezone.now() - execution.started_at).total_seconds()
    
    # Calculate actual counts from logs (more accurate than model fields)
    completed_logs_count = logs.filter(status='completed').count()
    failed_logs_count = logs.filter(status='failed').count()
    running_logs_count = logs.filter(status='running').count()
    pending_logs_count = logs.filter(status='pending').count()
    total_logs_count = logs.count()
    
    # Prepare response
    response_data = {
        'execution': {
            'id': str(execution.id),
            'status': execution.status,
            'status_display': execution.get_status_display(),
            'total_tables': total_logs_count,  # Use actual count from logs
            'completed_tables': completed_logs_count,  # Use actual count from logs
            'total_rows_synced': execution.total_rows_synced,
            'started_at': execution.started_at.isoformat() if execution.started_at else None,
            'completed_at': execution.completed_at.isoformat() if execution.completed_at else None,
            'duration_seconds': duration_seconds,
            'error_message': execution.error_message,
        },
        'logs': [
            {
                'id': str(log.id),
                'schema_name': log.schema_name,
                'table_name': log.table_name,
                'status': log.status,
                'status_display': log.get_status_display(),
                'batch_number': log.batch_number,
                'rows_fetched': log.rows_fetched or 0,
                'rows_inserted': log.rows_inserted or 0,
                'started_at': log.started_at.isoformat() if log.started_at else None,
                'completed_at': log.completed_at.isoformat() if log.completed_at else None,
                'error_message': log.error_message,
                'verification_summary': log.verification_summary or '',
            }
            for log in logs
        ],
        'statistics': {
            'completed_logs': completed_logs_count,
            'failed_logs': failed_logs_count,
            'running_logs': running_logs_count,
            'pending_logs': pending_logs_count,
            'total_logs': total_logs_count,
            'total_rows_fetched': sum(log.rows_fetched or 0 for log in logs),
            'total_rows_inserted': sum(log.rows_inserted or 0 for log in logs),
        }
    }
    
    return JsonResponse(response_data)


@login_required
@viewer_read_only_required
def reset_checkpoint(request, job_id, schema_name, table_name):
    """Reset checkpoint for a table"""
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        messages.error(request, 'Sync job not found.')
        logger.warning(f"User {request.user.username} attempted to reset checkpoint for non-existent job {job_id}")
        return redirect('sync_jobs:list')
    except Exception as e:
        logger.error(f"Error fetching job for checkpoint reset: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while loading the job.')
        return redirect('sync_jobs:list')
    
    try:
        from sync_engine.checkpoint_manager import CheckpointManager
        checkpoint_manager = CheckpointManager(job)
        deleted = checkpoint_manager.delete_checkpoint(schema_name, table_name)
        
        if deleted:
            logger.info(f"User {request.user.username} reset checkpoint for {schema_name}.{table_name} in job {job_id}")
            messages.success(request, f'Checkpoint reset for {schema_name}.{table_name}')
        else:
            messages.warning(request, f'No checkpoint found for {schema_name}.{table_name}')
    except Exception as e:
        logger.error(f"Error resetting checkpoint: {str(e)}", exc_info=True)
        messages.error(request, f'Failed to reset checkpoint: {str(e)}')
    
    return redirect('sync_jobs:job_detail', job_id=job_id)


@login_required
@require_http_methods(["GET"])
def view_checkpoints(request, job_id):
    """View all checkpoints for a job (API endpoint)"""
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)
    except Exception as e:
        logger.error(f"Error fetching job for checkpoint view: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'An error occurred'}, status=500)
    
    try:
        checkpoints = SyncCheckpoint.objects.filter(job=job).order_by('schema_name', 'table_name')
        
        data = [{
            'schema_name': cp.schema_name,
            'table_name': cp.table_name,
            'last_value': cp.last_value,
            'updated_at': cp.updated_at.isoformat() if cp.updated_at else None
        } for cp in checkpoints]
        
        return JsonResponse({'checkpoints': data})
    except Exception as e:
        logger.error(f"Error retrieving checkpoints: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def job_report(request, job_id):
    """Generate and display job report"""
    from accounts.services.tenant_service import TenantService
    try:
        jobs_qs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
        job = user_jobs.get(id=job_id)
    except SyncJob.DoesNotExist:
        messages.error(request, 'Job not found.')
        return redirect('sync_jobs:list')
    
    # Get date range from request
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        try:
            start_date = timezone.datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except:
            start_date = None
    if end_date:
        try:
            end_date = timezone.datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except:
            end_date = None
    
    from sync_jobs.reports import ReportService
    report = ReportService.generate_job_report(job, start_date, end_date)
    
    # Handle export requests
    export_format = request.GET.get('export')
    if export_format == 'csv':
        return ReportService.export_report_to_csv(report, filename=f'job_{job_id}_report.csv')
    elif export_format == 'json':
        return ReportService.export_report_to_json(report, filename=f'job_{job_id}_report.json')
    
    context = {
        'page_title': f'Report: {job.name}',
        'report': report,
    }
    
    return render(request, 'sync_jobs/job_report.html', context)


@login_required
def user_report(request):
    """Generate and display user report"""
    # Get date range from request
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        try:
            start_date = timezone.datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except:
            start_date = None
    if end_date:
        try:
            end_date = timezone.datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except:
            end_date = None
    
    from sync_jobs.reports import ReportService
    report = ReportService.generate_user_report(request.user, start_date, end_date)
    
    # Handle export requests
    export_format = request.GET.get('export')
    if export_format == 'csv':
        return ReportService.export_report_to_csv(report, filename=f'user_{request.user.username}_report.csv')
    elif export_format == 'json':
        return ReportService.export_report_to_json(report, filename=f'user_{request.user.username}_report.json')
    
    context = {
        'page_title': 'My Reports',
        'report': report,
    }
    
    return render(request, 'sync_jobs/user_report.html', context)


@login_required
@viewer_read_only_required
@require_http_methods(["POST"])
def bulk_pause(request):
    """Pause multiple jobs"""
    job_ids = request.POST.getlist('job_ids')
    if not job_ids:
        messages.error(request, 'No jobs selected.')
        return redirect('sync_jobs:list')
    
    from accounts.services.tenant_service import TenantService
    jobs_qs = SyncJob.objects.filter(id__in=job_ids)
    jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
    count = 0
    for job in jobs:
        if job.status != 'paused' and job.status != 'running':
            job.status = 'paused'
            job.save()
            # Disable schedule if exists
            if hasattr(job, 'schedule') and job.schedule:
                job.schedule.is_enabled = False
                job.schedule.save(update_fields=['is_enabled'])
            count += 1
    
    messages.success(request, f'{count} job(s) paused.')
    return redirect('sync_jobs:list')


@login_required
@viewer_read_only_required
@require_http_methods(["POST"])
def bulk_resume(request):
    """Resume multiple jobs"""
    job_ids = request.POST.getlist('job_ids')
    if not job_ids:
        messages.error(request, 'No jobs selected.')
        return redirect('sync_jobs:list')
    
    from accounts.services.tenant_service import TenantService
    jobs_qs = SyncJob.objects.filter(id__in=job_ids)
    jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
    count = 0
    from scheduler.utils import schedule_job_execution
    for job in jobs:
        if job.status == 'paused':
            job.status = 'pending'
            job.save()
            # Re-enable schedule if exists
            if hasattr(job, 'schedule') and job.schedule:
                job.schedule.is_enabled = True
                job.schedule.save(update_fields=['is_enabled'])
                try:
                    schedule_job_execution(job)
                except Exception as e:
                    logger.error(f"Error recalculating next_run_at on resume: {str(e)}", exc_info=True)
            count += 1
    
    messages.success(request, f'{count} job(s) resumed.')
    return redirect('sync_jobs:list')


@login_required
@viewer_read_only_required
@require_http_methods(["POST"])
def bulk_delete(request):
    """Delete multiple jobs"""
    job_ids = request.POST.getlist('job_ids')
    if not job_ids:
        messages.error(request, 'No jobs selected.')
        return redirect('sync_jobs:list')
    
    from accounts.services.tenant_service import TenantService
    jobs_qs = SyncJob.objects.filter(id__in=job_ids)
    jobs = TenantService.get_queryset_for_user(jobs_qs, request.user)
    count = jobs.count()
    jobs.delete()
    
    messages.success(request, f'{count} job(s) deleted.')
    return redirect('sync_jobs:list')