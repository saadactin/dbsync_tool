"""
Views for sync jobs
"""
import logging
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
from connections.models import DatabaseConnection, APIConnection
from metadata.services import load_all_metadata, load_table_columns
from .models import SyncJob, SyncJobTable, SyncSchedule, SyncCheckpoint, SyncExecution, SyncExecutionLog

logger = logging.getLogger(__name__)


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
        
        # Filter by source type (database, api, zoho_crm, sap_b1)
        source_type_filter = request.GET.get('source_type', '')
        if source_type_filter == 'database':
            jobs = jobs.filter(source_connection_type='database')
        elif source_type_filter == 'api':
            jobs = jobs.filter(source_connection_type='api')
        elif source_type_filter == 'zoho_crm':
            jobs = jobs.filter(source_connection_type='api', source_api_connection__api_type='zoho_crm')
        elif source_type_filter == 'sap_b1':
            jobs = jobs.filter(source_connection_type='api', source_api_connection__api_type='sap_b1')
        
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
    Supports both database and API connections as source
    """
    if request.method == 'POST':
        job_name = request.POST.get('job_name', '').strip()
        source_connection_id = request.POST.get('source_connection')
        source_connection_type = request.POST.get('source_connection_type', 'database')  # 'database' or 'api'
        target_connection_id = request.POST.get('target_connection')
        
        # Enhanced validation
        errors = []
        
        # Job name validation
        try:
            from sync_jobs.validators import validate_job_name
            job_name = validate_job_name(job_name)
        except ValidationError as e:
            errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
        
        # Source connection validation
        source_connection_uuid = None
        if not source_connection_id:
            errors.append('Source connection is required.')
        else:
            try:
                # Validate UUID format (connection IDs are UUIDs)
                import uuid
                source_connection_uuid = uuid.UUID(str(source_connection_id))
            except (ValueError, TypeError, AttributeError):
                errors.append('Invalid source connection ID.')
        
        # Validate source connection type
        if source_connection_type not in ['database', 'api']:
            errors.append('Invalid source connection type.')
        
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
                    
                else:
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
                    request.session['sync_job_target_connection_id'] = str(target_connection.id)
                
                # Redirect to step 2
                return redirect('sync_jobs:create_step2')
                
            except (DatabaseConnection.DoesNotExist, APIConnection.DoesNotExist):
                messages.error(request, 'Selected connection not found or inactive.')
    
    # Get user's active connections
    from accounts.services.tenant_service import TenantService
    db_connections_qs = DatabaseConnection.objects.filter(is_active=True).order_by('name')
    db_connections = TenantService.get_queryset_for_user(db_connections_qs, request.user)
    
    api_connections_qs = APIConnection.objects.filter(is_active=True).order_by('name')
    api_connections = TenantService.get_queryset_for_user(api_connections_qs, request.user)
    
    context = {
        'db_connections': db_connections,
        'api_connections': api_connections,
        'page_title': 'Create Sync Job - Step 1',
        'job_name': request.session.get('sync_job_name', ''),
        'selected_source_id': request.session.get('sync_job_source_connection_id') or request.session.get('sync_job_source_api_connection_id', ''),
        'selected_source_type': request.session.get('sync_job_source_connection_type', 'database'),
        'selected_target_id': request.session.get('sync_job_target_connection_id', ''),
    }
    
    return render(request, 'sync_jobs/create_step1.html', context)


@login_required
def create_job_step2_view(request):
    """
    Step 2: Table/Module selection view
    Gets source connection from session (set in step 1)
    For API sources: Shows module selection
    For Database sources: Shows table selection
    """
    # Get source connection info from session
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    source_api_connection_id = request.session.get('sync_job_source_api_connection_id')
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
            
            # Branch on API type: Zoho (modules) vs SAP (endpoints)
            is_sap = getattr(source_api_connection, 'api_type', None) == 'sap_b1'
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
            
            context = {
                'source_connection_type': 'api',
                'source_api_connection': source_api_connection,
                'available_modules': available_modules,
                'available_endpoints': available_endpoints,
                'is_sap': is_sap,
                'job_name': job_name,
                'page_title': 'Select Modules - Step 2' if not is_sap else 'Select SAP Endpoints - Step 2',
            }
            
            return render(request, 'sync_jobs/create_step2.html', context)
            
        except APIConnection.DoesNotExist:
            messages.error(request, 'Source API connection not found or inactive.')
            return redirect('sync_jobs:create_step1')
    
    else:
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
        return redirect('sync_jobs:create_step3')
    
    else:
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
        
        # Redirect to step 3
        messages.success(request, f'Selected {len(tables)} table(s).')
        return redirect('sync_jobs:create_step3')


@login_required
def create_job_step3_view(request):
    """
    Step 3: Sync type and scheduling configuration
    Supports both database and API sources
    """
    # Get data from session
    job_name = request.session.get('sync_job_name')
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    source_api_connection_id = request.session.get('sync_job_source_api_connection_id')
    target_connection_id = request.session.get('sync_job_target_connection_id')
    selected_tables = request.session.get('sync_job_selected_tables', [])
    
    # Validate session data based on source type
    if source_connection_type == 'api':
        if not all([job_name, source_api_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Please complete previous steps first.')
            return redirect('sync_jobs:create_step1')
    else:
        if not all([job_name, source_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Please complete previous steps first.')
            return redirect('sync_jobs:create_step1')
    
    from accounts.services.tenant_service import TenantService
    
    # Load column information for each table (only for database sources)
    # For API sources, incremental sync uses Modified_Time from API, no column selection needed
    table_columns = {}
    source_connection = None
    source_api_connection = None
    
    if source_connection_type == 'api':
        # API source - no column loading needed
        try:
            api_qs = APIConnection.objects.filter(is_active=True)
            user_api_conns = TenantService.get_queryset_for_user(api_qs, request.user)
            source_api_connection = user_api_conns.get(id=source_api_connection_id)
        except APIConnection.DoesNotExist:
            messages.error(request, 'Source API connection not found.')
            return redirect('sync_jobs:create_step1')
    else:
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
                    columns = load_table_columns(
                        str(source_connection.id),
                        schema_name,
                        table_name,
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
    
    context = {
        'job_name': job_name,
        'source_connection_type': source_connection_type,
        'source_connection': source_connection,
        'source_api_connection': source_api_connection,
        'selected_tables': selected_tables,
        'table_columns': table_columns,
        'page_title': 'Configure Sync - Step 3',
    }
    
    return render(request, 'sync_jobs/create_step3.html', context)


@login_required
@viewer_read_only_required
def create_job_step3_submit(request):
    """
    Handle Step 3 form submission and create the sync job
    """
    if request.method != 'POST':
        return redirect('sync_jobs:create_step3')
    
    # Get data from session
    job_name = request.session.get('sync_job_name')
    source_connection_type = request.session.get('sync_job_source_connection_type', 'database')
    source_connection_id = request.session.get('sync_job_source_connection_id')
    source_api_connection_id = request.session.get('sync_job_source_api_connection_id')
    target_connection_id = request.session.get('sync_job_target_connection_id')
    selected_tables = request.session.get('sync_job_selected_tables', [])
    
    # Validate session data based on source type
    if source_connection_type == 'api':
        if not all([job_name, source_api_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Session expired. Please start over.')
            return redirect('sync_jobs:create_step1')
    else:
        if not all([job_name, source_connection_id, target_connection_id, selected_tables]):
            messages.error(request, 'Session expired. Please start over.')
            return redirect('sync_jobs:create_step1')
    
    # Get form data
    sync_type = request.POST.get('sync_type', 'full')
    schedule_type = request.POST.get('schedule_type', 'once')
    cron_expression = request.POST.get('cron_expression', '').strip()
    start_datetime = request.POST.get('start_datetime', '').strip()
    
    # Enhanced validation
    errors = []
    
    # Sync type validation
    try:
        from sync_jobs.validators import validate_sync_type
        sync_type = validate_sync_type(sync_type)
    except ValidationError as e:
        errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    
    # Schedule type validation
    try:
        from sync_jobs.validators import validate_schedule_type
        schedule_type = validate_schedule_type(schedule_type)
    except ValidationError as e:
        errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    
    # Cron expression validation (if custom schedule)
    if schedule_type == 'custom':
        try:
            from sync_jobs.validators import validate_cron_expression
            cron_expression = validate_cron_expression(cron_expression)
        except ValidationError as e:
            errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    
    # Start datetime validation
    try:
        from sync_jobs.validators import validate_start_datetime
        start_datetime_obj = validate_start_datetime(start_datetime, schedule_type)
    except ValidationError as e:
        errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
        start_datetime_obj = None
    else:
        start_datetime_obj = start_datetime_obj if start_datetime_obj else None
    
    # Validate incremental columns if incremental sync
    incremental_columns = {}
    if sync_type == 'incremental':
        for table_info in selected_tables:
            table_key = f"{table_info['schema_name']}.{table_info['table_name']}"
            inc_col = request.POST.get(f'incremental_column_{table_key}', '').strip()
            try:
                from sync_jobs.validators import validate_incremental_column
                inc_col = validate_incremental_column(inc_col, table_key)
                incremental_columns[table_key] = inc_col
            except ValidationError as e:
                errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])
    
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect('sync_jobs:create_step3')
    
    try:
        # Get connections based on source type
        from accounts.services.tenant_service import TenantService
        
        # Target connection is always database
        db_qs = DatabaseConnection.objects.filter(is_active=True)
        user_db_conns = TenantService.get_queryset_for_user(db_qs, request.user)
        target_connection = user_db_conns.get(id=target_connection_id)
        
        # Source connection depends on type
        if source_connection_type == 'api':
            api_qs = APIConnection.objects.filter(is_active=True)
            user_api_conns = TenantService.get_queryset_for_user(api_qs, request.user)
            source_api_connection = user_api_conns.get(id=source_api_connection_id)
            source_connection = None
        else:
            source_connection = user_db_conns.get(id=source_connection_id)
            source_api_connection = None
        
        # Calculate next_run_at based on schedule
        next_run_at = None
        if schedule_type != 'once':
            # Use validated datetime object if available
            if start_datetime_obj:
                next_run_at = start_datetime_obj
            elif start_datetime:
                try:
                    # Parse datetime-local format (YYYY-MM-DDTHH:mm)
                    dt_str = start_datetime.replace('T', ' ')
                    if ':' in dt_str:
                        # Ensure we have seconds
                        if dt_str.count(':') == 1:
                            dt_str += ':00'
                    next_run_at = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                    if timezone.is_naive(next_run_at):
                        next_run_at = timezone.make_aware(next_run_at)
                except Exception as e:
                    # If parsing fails, use current time
                    next_run_at = timezone.now()
            else:
                next_run_at = timezone.now()
            
            # Adjust for schedule type
            if schedule_type == 'hourly':
                next_run_at = next_run_at.replace(minute=0, second=0, microsecond=0)
                if next_run_at <= timezone.now():
                    next_run_at += timedelta(hours=1)
            elif schedule_type == 'daily':
                next_run_at = next_run_at.replace(hour=0, minute=0, second=0, microsecond=0)
                if next_run_at <= timezone.now():
                    next_run_at += timedelta(days=1)
            elif schedule_type == 'weekly':
                next_run_at = next_run_at.replace(hour=0, minute=0, second=0, microsecond=0)
                # Set to next Monday
                days_until_monday = (7 - next_run_at.weekday()) % 7 or 7
                if days_until_monday == 7 and next_run_at.hour == 0:
                    days_until_monday = 0
                next_run_at += timedelta(days=days_until_monday)
        
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
            source_connection_type=source_connection_type,
            target_connection=target_connection,
            sync_type=sync_type,
            status='pending',
            created_by=request.user,
            tenant=tenant,
            next_run_at=next_run_at
        )
        
        # Get transformation data from session (only for database sources)
        table_transformations = request.session.get('sync_job_table_transformations', {})
        
        # Create SyncJobTable entries
        for table_info in selected_tables:
            table_key = f"{table_info['schema_name']}.{table_info['table_name']}"
            
            # For API sources, incremental_column is not applicable (uses Modified_Time from API)
            # For database sources, use incremental_column from form
            incremental_column = None
            if source_connection_type == 'database':
                incremental_column = incremental_columns.get(table_key)
            
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
            
            SyncJobTable.objects.create(
                job=sync_job,
                schema_name=table_info['schema_name'],
                table_name=table_info['table_name'],
                incremental_column=incremental_column,
                transformation_query=transformation_query,
                column_transformations=column_transformations if column_transformations else {},
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
        request.session.pop('sync_job_target_connection_id', None)
        request.session.pop('sync_job_selected_tables', None)
        
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
        is_enabled = request.POST.get('is_enabled') == 'on'
        
        # Validation
        errors = []
        if schedule_type not in ['once', 'hourly', 'daily', 'weekly', 'custom']:
            errors.append('Invalid schedule type.')
        
        if schedule_type == 'custom' and not cron_expression:
            errors.append('Cron expression is required for custom schedules.')
        
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
            job.schedule.is_enabled = is_enabled
            
            if start_datetime:
                try:
                    job.schedule.next_run_at = timezone.datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
                except:
                    job.schedule.next_run_at = None
            else:
                job.schedule.next_run_at = None
            
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
        
        # Validation
        errors = []
        if not job_name:
            errors.append('Job name is required.')
        
        if sync_type not in ['full', 'incremental']:
            errors.append('Invalid sync type.')
        
        if schedule_type not in ['once', 'hourly', 'daily', 'weekly', 'custom']:
            errors.append('Invalid schedule type.')
        
        if schedule_type == 'custom' and not cron_expression:
            errors.append('Cron expression is required for custom schedules.')
        
        # Validate incremental columns if changing to incremental
        if sync_type == 'incremental':
            for table in job.tables.all():
                table_key = f"{table.schema_name}.{table.table_name}"
                inc_col = request.POST.get(f'incremental_column_{table_key}', '').strip()
                if not inc_col:
                    errors.append(f'Incremental column is required for table {table_key}.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            # Update job
            job.name = job_name
            job.sync_type = sync_type
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
                if start_datetime:
                    try:
                        dt_str = start_datetime.replace('T', ' ')
                        if ':' in dt_str:
                            if dt_str.count(':') == 1:
                                dt_str += ':00'
                        next_run_at = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                        if timezone.is_naive(next_run_at):
                            next_run_at = timezone.make_aware(next_run_at)
                    except Exception:
                        next_run_at = timezone.now()
                else:
                    next_run_at = timezone.now()
                
                # Adjust for schedule type
                if schedule_type == 'hourly':
                    next_run_at = next_run_at.replace(minute=0, second=0, microsecond=0)
                    if next_run_at <= timezone.now():
                        next_run_at += timedelta(hours=1)
                elif schedule_type == 'daily':
                    next_run_at = next_run_at.replace(hour=0, minute=0, second=0, microsecond=0)
                    if next_run_at <= timezone.now():
                        next_run_at += timedelta(days=1)
                elif schedule_type == 'weekly':
                    next_run_at = next_run_at.replace(hour=0, minute=0, second=0, microsecond=0)
                    days_until_monday = (7 - next_run_at.weekday()) % 7 or 7
                    if days_until_monday == 7 and next_run_at.hour == 0:
                        days_until_monday = 0
                    next_run_at += timedelta(days=days_until_monday)
            
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
            
            # Update incremental columns
            if sync_type == 'incremental':
                for table in job.tables.all():
                    table_key = f"{table.schema_name}.{table.table_name}"
                    inc_col = request.POST.get(f'incremental_column_{table_key}', '').strip()
                    table.incremental_column = inc_col
                    table.save()
            else:
                # Clear incremental columns for full sync
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
    if job.sync_type == 'incremental' or request.method == 'GET':
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
    
    context = {
        'job': job,
        'table_columns': table_columns,
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