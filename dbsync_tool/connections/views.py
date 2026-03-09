"""
Views for connection management
"""
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied
from django.utils import timezone
import json
import logging
from accounts.permissions import ViewerReadOnlyMixin, OperatorOrAboveMixin
from .models import DatabaseConnection, APIConnection
from .forms import DatabaseConnectionForm, APIConnectionForm
from .services import test_database_connection
from .connectors import get_connector
from core.exceptions import DatabaseConnectionError, InvalidDatabaseTypeError

logger = logging.getLogger('connections.views')


class ConnectionListView(LoginRequiredMixin, ListView):
    model = DatabaseConnection
    template_name = 'connections/connection_list.html'
    context_object_name = 'connections'
    paginate_by = 20
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = DatabaseConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connections = self.get_queryset()
        
        # Group by db_type with display information
        db_type_info = {
            'postgres': {'name': 'PostgreSQL', 'connections': []},
            'mysql': {'name': 'MySQL', 'connections': []},
            'sqlserver': {'name': 'SQL Server', 'connections': []},
            'clickhouse': {'name': 'ClickHouse', 'connections': []},
            'oracle_adw': {'name': 'Oracle ADW', 'connections': []},
        }
        
        for conn in connections:
            if conn.db_type not in db_type_info:
                # Fallback for any future/unknown DB types
                db_type_info[conn.db_type] = {
                    'name': conn.get_db_type_display() if hasattr(conn, 'get_db_type_display') else conn.db_type,
                    'connections': []
                }
            db_type_info[conn.db_type]['connections'].append(conn)
        
        # Create list of groups for template iteration
        grouped_list = []
        for db_type, info in db_type_info.items():
            grouped_list.append({
                'type': db_type,
                'name': info['name'],
                'connections': info['connections'],
                'count': len(info['connections'])
            })
        
        context['grouped_list'] = grouped_list
        context['total_connections'] = sum(len(info['connections']) for info in db_type_info.values())
        
        # Add API connections count for navigation
        from accounts.services.tenant_service import TenantService
        api_qs = APIConnection.objects.all().select_related('created_by', 'tenant')
        api_qs = TenantService.get_queryset_for_user(api_qs, self.request.user)
        context['api_connections_count'] = api_qs.count()
        
        return context


class ConnectionDetailView(LoginRequiredMixin, DetailView):
    model = DatabaseConnection
    template_name = 'connections/connection_detail.html'
    context_object_name = 'connection'
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = DatabaseConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get recent test logs
        context['test_logs'] = self.object.test_logs.all()[:10]
        # Get last test status
        last_test = self.object.test_logs.first()
        context['last_test_status'] = last_test.status if last_test else None
        return context


class ConnectionCreateView(ViewerReadOnlyMixin, OperatorOrAboveMixin, CreateView):
    model = DatabaseConnection
    form_class = DatabaseConnectionForm
    template_name = 'connections/connection_form.html'
    success_url = reverse_lazy('connections:list')
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def form_valid(self, form):
        from accounts.services.tenant_service import TenantService
        from django.core.exceptions import ValidationError
        
        instance = form.save(commit=False)
        instance.created_by = self.request.user
        instance.tenant = TenantService.get_user_tenant(self.request.user)
        
        # Validate tenant is not None (Super Admin shouldn't create data)
        if instance.tenant is None:
            messages.error(
                self.request,
                "Super Admin cannot create connections. Please use an Admin account."
            )
            return self.form_invalid(form)
        
        instance.save()
        
        logger.info(
            'Connection created',
            extra={
                'event_type': 'connection_created',
                'connection_id': instance.id,
                'connection_name': instance.name,
                'db_type': instance.db_type,
                'tenant_id': instance.tenant.id if instance.tenant else None,
                'tenant_username': instance.tenant.username if instance.tenant else None,
                'created_by_id': self.request.user.id,
                'created_by_username': self.request.user.username,
                'created_by_role': self.request.user.userprofile.role,
                'timestamp': timezone.now().isoformat(),
                'ip_address': self._get_client_ip(self.request),
            }
        )
        
        messages.success(self.request, f'Connection "{form.instance.name}" created successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class ConnectionUpdateView(ViewerReadOnlyMixin, OperatorOrAboveMixin, UpdateView):
    model = DatabaseConnection
    form_class = DatabaseConnectionForm
    template_name = 'connections/connection_form.html'
    success_url = reverse_lazy('connections:list')
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = DatabaseConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)
    
    def dispatch(self, request, *args, **kwargs):
        from accounts.services.tenant_service import TenantService
        obj = self.get_object()
        if not TenantService.can_user_manage_tenant(request.user, obj.tenant):
            logger.warning(
                'Cross-tenant connection update attempt',
                extra={
                    'event_type': 'cross_tenant_update_blocked',
                    'connection_id': obj.id,
                    'connection_name': obj.name,
                    'connection_tenant_id': obj.tenant.id,
                    'user_id': request.user.id,
                    'username': request.user.username,
                    'user_role': request.user.userprofile.role,
                    'path': request.path,
                    'ip_address': self._get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            raise PermissionDenied("You don't have permission to modify this connection.")
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        instance = form.save(commit=False)
        
        # Double-check: Verify tenant hasn't changed
        original_tenant = self.get_object().tenant
        if instance.tenant != original_tenant:
            logger.warning(
                'Tenant change attempt blocked',
                extra={
                    'event_type': 'tenant_change_blocked',
                    'connection_id': instance.id,
                    'original_tenant_id': original_tenant.id,
                    'attempted_tenant_id': instance.tenant.id if instance.tenant else None,
                    'user_id': self.request.user.id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            messages.error(self.request, 'Cannot change tenant of existing connection.')
            instance.tenant = original_tenant
        
        instance.save()
        
        logger.info(
            'Connection updated',
            extra={
                'event_type': 'connection_updated',
                'connection_id': instance.id,
                'connection_name': instance.name,
                'tenant_id': instance.tenant.id if instance.tenant else None,
                'updated_by_id': self.request.user.id,
                'updated_by_username': self.request.user.username,
                'timestamp': timezone.now().isoformat(),
                'ip_address': self._get_client_ip(self.request),
            }
        )
        
        messages.success(self.request, f'Connection "{form.instance.name}" updated successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class ConnectionDeleteView(ViewerReadOnlyMixin, OperatorOrAboveMixin, DeleteView):
    model = DatabaseConnection
    template_name = 'connections/connection_confirm_delete.html'
    success_url = reverse_lazy('connections:list')
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = DatabaseConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)
    
    def dispatch(self, request, *args, **kwargs):
        from accounts.services.tenant_service import TenantService
        obj = self.get_object()
        if not TenantService.can_user_manage_tenant(request.user, obj.tenant):
            logger.warning(
                'Cross-tenant connection delete attempt',
                extra={
                    'event_type': 'cross_tenant_delete_blocked',
                    'connection_id': obj.id,
                    'connection_name': obj.name,
                    'connection_tenant_id': obj.tenant.id,
                    'user_id': request.user.id,
                    'username': request.user.username,
                    'user_role': request.user.userprofile.role,
                    'path': request.path,
                    'ip_address': self._get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            raise PermissionDenied("You don't have permission to delete this connection.")
        return super().dispatch(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        connection = self.get_object()
        connection_id = connection.id
        connection_name = connection.name
        tenant_id = connection.tenant.id if connection.tenant else None
        
        result = super().delete(request, *args, **kwargs)
        
        logger.info(
            'Connection deleted',
            extra={
                'event_type': 'connection_deleted',
                'connection_id': connection_id,
                'connection_name': connection_name,
                'tenant_id': tenant_id,
                'deleted_by_id': request.user.id,
                'deleted_by_username': request.user.username,
                'timestamp': timezone.now().isoformat(),
                'ip_address': self._get_client_ip(request),
            }
        )
        
        messages.success(request, f'Connection "{connection_name}" deleted successfully!')
        return result


class ConnectionTestView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from accounts.services.tenant_service import TenantService
        try:
            qs = DatabaseConnection.objects.filter(pk=pk)
            qs = TenantService.get_queryset_for_user(qs, request.user)
            connection = qs.get()
        except DatabaseConnection.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Connection not found'
            }, status=404)
        
        success, message = test_database_connection(connection, request.user)
        
        # Update last_tested_at if test is successful
        if success:
            from django.utils import timezone
            connection.last_tested_at = timezone.now()
            connection.save(update_fields=['last_tested_at'])
        
        return JsonResponse({
            'success': success,
            'message': message,
            'connection_id': str(connection.id)
        })


class ConnectionTestAndListDatabasesView(LoginRequiredMixin, View):
    """
    View to test database connection and list available databases
    Accepts credentials without database_name and returns list of databases
    """
    def post(self, request):
        connector = None
        try:
            data = json.loads(request.body)
            db_type = data.get('db_type')
            host = data.get('host')
            port = data.get('port')
            username = data.get('username')
            password = data.get('password')
            database_name = (data.get('database_name') or '').strip() or None

            # Validate required fields
            if not all([db_type, host, port, username, password]):
                return JsonResponse({
                    'success': False,
                    'message': 'Missing required fields: db_type, host, port, username, password'
                }, status=400)
            if db_type == 'oracle_adw' and not database_name:
                return JsonResponse({
                    'success': False,
                    'message': 'Service name (Oracle ADW) is required. Use the service name from your JDBC/connection string.'
                }, status=400)
            
            # Validate port
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    return JsonResponse({
                        'success': False,
                        'message': 'Port must be between 1 and 65535'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Port must be a valid number'
                }, status=400)
            
            # Create connector (database_name required for Oracle ADW as service name)
            try:
                connector = get_connector(
                    db_type=db_type,
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    database_name=database_name,
                )
                
                # Try to connect and list databases in one go
                # This tests the connection implicitly
                try:
                    databases = connector.list_databases()
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'Connection successful! Found {len(databases)} database(s).',
                        'databases': databases
                    })
                except DatabaseConnectionError as e:
                    # Connection failed
                    error_msg = str(e)
                    logger.error(f"Connection test failed: {error_msg}")
                    return JsonResponse({
                        'success': False,
                        'message': f'Connection failed: {error_msg}'
                    }, status=200)
                
            except InvalidDatabaseTypeError as e:
                logger.error(f"Invalid database type: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'message': str(e)
                }, status=400)
            except DatabaseConnectionError as e:
                logger.error(f"Database connection error: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'message': f'Connection failed: {str(e)}'
                }, status=200)
            except Exception as e:
                # Log the full error for debugging
                import traceback
                error_trace = traceback.format_exc()
                logger.exception('Error in ConnectionTestAndListDatabasesView')
                logger.error(f'Full traceback: {error_trace}')
                return JsonResponse({
                    'success': False,
                    'message': f'Unexpected error: {str(e)}'
                }, status=500)
            finally:
                if connector:
                    try:
                        connector.close()
                    except Exception:
                        pass  # Ignore errors when closing
                    
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.exception('Unexpected error in ConnectionTestAndListDatabasesView')
            logger.error(f'Full traceback: {error_trace}')
            return JsonResponse({
                'success': False,
                'message': f'Unexpected error: {str(e)}'
            }, status=500)


# API Connection Views

class APIConnectionListView(LoginRequiredMixin, ListView):
    """List view for API connections"""
    model = APIConnection
    template_name = 'connections/api_connection_list.html'
    context_object_name = 'api_connections'
    paginate_by = 20
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = APIConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connections = self.get_queryset()
        
        # Group by api_type (include all known types so SAP and others appear)
        api_type_info = {
            'zoho_crm': {'name': 'Zoho CRM', 'connections': []},
            'sap_b1': {'name': 'SAP Business One', 'connections': []},
        }
        for conn in connections:
            if conn.api_type not in api_type_info:
                api_type_info[conn.api_type] = {'name': conn.api_type, 'connections': []}
            api_type_info[conn.api_type]['connections'].append(conn)
        
        # Create list of groups for template iteration
        grouped_list = []
        for api_type, info in api_type_info.items():
            grouped_list.append({
                'type': api_type,
                'name': info['name'],
                'connections': info['connections'],
                'count': len(info['connections'])
            })
        
        context['grouped_list'] = grouped_list
        context['total_connections'] = sum(len(info['connections']) for info in api_type_info.values())
        
        return context


class APIConnectionDetailView(LoginRequiredMixin, DetailView):
    """Detail view for API connections"""
    model = APIConnection
    template_name = 'connections/api_connection_detail.html'
    context_object_name = 'connection'
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = APIConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)


class APIConnectionCreateView(ViewerReadOnlyMixin, OperatorOrAboveMixin, CreateView):
    """Create view for API connections"""
    model = APIConnection
    form_class = APIConnectionForm
    template_name = 'connections/api_connection_form.html'
    success_url = reverse_lazy('connections:api_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from core.constants import SAP_DOCUMENT_TYPES
        context['sap_document_types'] = json.dumps(SAP_DOCUMENT_TYPES)
        return context

    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def form_valid(self, form):
        from accounts.services.tenant_service import TenantService
        from django.core.exceptions import ValidationError
        
        instance = form.save(commit=False)
        instance.created_by = self.request.user
        instance.tenant = TenantService.get_user_tenant(self.request.user)
        
        # Validate tenant is not None
        if instance.tenant is None:
            messages.error(
                self.request,
                "Super Admin cannot create connections. Please use an Admin account."
            )
            return self.form_invalid(form)
        
        # Check for duplicate name per tenant
        if APIConnection.objects.filter(tenant=instance.tenant, name=instance.name).exists():
            messages.error(
                self.request,
                f'A connection with the name "{instance.name}" already exists for this tenant.'
            )
            return self.form_invalid(form)
        
        instance.save()
        
        logger.info(
            'API Connection created',
            extra={
                'event_type': 'api_connection_created',
                'connection_id': instance.id,
                'connection_name': instance.name,
                'api_type': instance.api_type,
                'tenant_id': instance.tenant.id if instance.tenant else None,
                'created_by_id': self.request.user.id,
                'created_by_username': self.request.user.username,
                'timestamp': timezone.now().isoformat(),
                'ip_address': self._get_client_ip(self.request),
            }
        )
        
        messages.success(self.request, f'API Connection "{form.instance.name}" created successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class APIConnectionUpdateView(ViewerReadOnlyMixin, OperatorOrAboveMixin, UpdateView):
    """Update view for API connections"""
    model = APIConnection
    form_class = APIConnectionForm
    template_name = 'connections/api_connection_form.html'
    success_url = reverse_lazy('connections:api_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from core.constants import SAP_DOCUMENT_TYPES
        context['sap_document_types'] = json.dumps(SAP_DOCUMENT_TYPES)
        return context

    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = APIConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)
    
    def dispatch(self, request, *args, **kwargs):
        from accounts.services.tenant_service import TenantService
        obj = self.get_object()
        if not TenantService.can_user_manage_tenant(request.user, obj.tenant):
            logger.warning(
                'Cross-tenant API connection update attempt',
                extra={
                    'event_type': 'cross_tenant_api_update_blocked',
                    'connection_id': obj.id,
                    'connection_name': obj.name,
                    'connection_tenant_id': obj.tenant.id,
                    'user_id': request.user.id,
                    'username': request.user.username,
                    'path': request.path,
                    'ip_address': self._get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            raise PermissionDenied("You don't have permission to modify this connection.")
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        instance = form.save(commit=False)
        
        # Double-check: Verify tenant hasn't changed
        original_tenant = self.get_object().tenant
        if instance.tenant != original_tenant:
            logger.warning(
                'Tenant change attempt blocked for API connection',
                extra={
                    'event_type': 'tenant_change_blocked',
                    'connection_id': instance.id,
                    'original_tenant_id': original_tenant.id,
                    'attempted_tenant_id': instance.tenant.id if instance.tenant else None,
                    'user_id': self.request.user.id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            messages.error(self.request, 'Cannot change tenant of existing connection.')
            instance.tenant = original_tenant
        
        # Check for duplicate name per tenant (excluding current instance)
        if APIConnection.objects.filter(tenant=instance.tenant, name=instance.name).exclude(pk=instance.pk).exists():
            messages.error(
                self.request,
                f'A connection with the name "{instance.name}" already exists for this tenant.'
            )
            return self.form_invalid(form)
        
        instance.save()
        
        logger.info(
            'API Connection updated',
            extra={
                'event_type': 'api_connection_updated',
                'connection_id': instance.id,
                'connection_name': instance.name,
                'tenant_id': instance.tenant.id if instance.tenant else None,
                'updated_by_id': self.request.user.id,
                'updated_by_username': self.request.user.username,
                'timestamp': timezone.now().isoformat(),
                'ip_address': self._get_client_ip(self.request),
            }
        )
        
        messages.success(self.request, f'API Connection "{form.instance.name}" updated successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class APIConnectionDeleteView(ViewerReadOnlyMixin, OperatorOrAboveMixin, DeleteView):
    """Delete view for API connections"""
    model = APIConnection
    template_name = 'connections/api_connection_confirm_delete.html'
    success_url = reverse_lazy('connections:api_list')
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = APIConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)
    
    def dispatch(self, request, *args, **kwargs):
        from accounts.services.tenant_service import TenantService
        obj = self.get_object()
        if not TenantService.can_user_manage_tenant(request.user, obj.tenant):
            logger.warning(
                'Cross-tenant API connection delete attempt',
                extra={
                    'event_type': 'cross_tenant_api_delete_blocked',
                    'connection_id': obj.id,
                    'connection_name': obj.name,
                    'connection_tenant_id': obj.tenant.id,
                    'user_id': request.user.id,
                    'username': request.user.username,
                    'path': request.path,
                    'ip_address': self._get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            raise PermissionDenied("You don't have permission to delete this connection.")
        return super().dispatch(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        connection = self.get_object()
        connection_id = connection.id
        connection_name = connection.name
        tenant_id = connection.tenant.id if connection.tenant else None
        
        # TODO: Check if connection is used in sync jobs (will be added in Day 5)
        # For now, allow deletion
        
        result = super().delete(request, *args, **kwargs)
        
        logger.info(
            'API Connection deleted',
            extra={
                'event_type': 'api_connection_deleted',
                'connection_id': connection_id,
                'connection_name': connection_name,
                'tenant_id': tenant_id,
                'deleted_by_id': request.user.id,
                'deleted_by_username': request.user.username,
                'timestamp': timezone.now().isoformat(),
                'ip_address': self._get_client_ip(request),
            }
        )
        
        messages.success(request, f'API Connection "{connection_name}" deleted successfully!')
        return result


class APIConnectionTestView(LoginRequiredMixin, View):
    """AJAX endpoint to test API connection and return available modules"""
    
    def post(self, request, pk=None):
        """Test connection for existing connection (pk provided) or new connection (no pk)"""
        from accounts.services.tenant_service import TenantService
        
        try:
            if pk:
                # Test existing connection
                qs = APIConnection.objects.filter(pk=pk)
                qs = TenantService.get_queryset_for_user(qs, request.user)
                connection = qs.get()
            else:
                # Test new connection from form data
                data = json.loads(request.body)
                api_type = data.get('api_type', 'zoho_crm')
                if api_type == 'sap_b1':
                    sap_base_url = (data.get('sap_base_url') or '').strip()
                    sap_user_name = (data.get('sap_user_name') or '').strip()
                    sap_company_db = (data.get('sap_company_db') or '').strip()
                    sap_password = data.get('sap_password') or ''
                    if not sap_base_url or not sap_user_name or not sap_company_db or not sap_password:
                        return JsonResponse({
                            'success': False,
                            'message': 'Missing required SAP fields: sap_base_url, sap_user_name, sap_company_db, sap_password'
                        }, status=400)
                    from core.constants import SAP_DOCUMENT_TYPES
                    from connections.connectors.sap import SAPConnector
                    temp_connection = APIConnection()
                    temp_connection.name = data.get('name', 'Test Connection')
                    temp_connection.api_type = 'sap_b1'
                    temp_connection.sap_base_url = sap_base_url
                    temp_connection.sap_username = {'UserName': sap_user_name, 'CompanyDB': sap_company_db}
                    def get_test_sap_password():
                        return sap_password
                    temp_connection.get_decrypted_sap_password = get_test_sap_password
                    temp_connection.get_sap_connection_params = lambda: {
                        'base_url': sap_base_url.rstrip('/'),
                        'username': {'UserName': sap_user_name, 'CompanyDB': sap_company_db},
                        'password': sap_password,
                    }
                    connector = SAPConnector(temp_connection)
                    if not connector.authenticate():
                        return JsonResponse({
                            'success': False,
                            'message': 'SAP authentication failed. Please check your credentials.'
                        })
                    try:
                        endpoints = connector.get_available_endpoints()
                    except Exception as e:
                        logger.exception('SAP get_available_endpoints failed')
                        return JsonResponse({
                            'success': False,
                            'message': f'Connection authenticated but failed to fetch endpoints: {str(e)}'
                        })
                    return JsonResponse({
                        'success': True,
                        'message': 'Credentials accepted. Select endpoints below (fetched from your server).',
                        'endpoints': endpoints,
                        'modules': endpoints
                    })
                client_id = data.get('client_id', '').strip()
                client_secret = data.get('client_secret', '').strip()
                refresh_token = data.get('refresh_token', '').strip()
                api_domain = data.get('api_domain', '').strip()
                token_url = data.get('token_url', '').strip()
                if not all([client_id, client_secret, refresh_token, api_domain]):
                    return JsonResponse({
                        'success': False,
                        'message': 'Missing required fields: client_id, client_secret, refresh_token, api_domain'
                    }, status=400)
                from connections.connectors.zoho import ZohoConnector
                temp_connection = APIConnection()
                temp_connection.name = data.get('name', 'Test Connection')
                temp_connection.api_type = api_type
                temp_connection.client_id = client_id
                temp_connection.api_domain = api_domain
                temp_connection.token_url = token_url or 'https://accounts.zoho.in/oauth/v2/token'
                temp_connection._test_client_secret = client_secret
                temp_connection._test_refresh_token = refresh_token
                def get_test_client_secret():
                    return client_secret
                def get_test_refresh_token():
                    return refresh_token
                temp_connection.get_decrypted_client_secret = get_test_client_secret
                temp_connection.get_decrypted_refresh_token = get_test_refresh_token
                connector = ZohoConnector(temp_connection)
                if not connector.authenticate():
                    return JsonResponse({
                        'success': False,
                        'message': 'Authentication failed. Please check your credentials.'
                    })
                try:
                    modules = connector.get_available_modules()
                    return JsonResponse({
                        'success': True,
                        'message': f'Connection successful! Found {len(modules)} modules.',
                        'modules': modules
                    })
                except Exception as e:
                    logger.exception('Error getting modules')
                    return JsonResponse({
                        'success': False,
                        'message': f'Connection authenticated but failed to fetch modules: {str(e)}'
                    })
            success, message, modules = connection.test_connection()
            if pk and connection.api_type == 'sap_b1':
                from core.constants import SAP_DOCUMENT_TYPES
                from connections.connectors.sap import SAPConnector
                endpoints = list(SAP_DOCUMENT_TYPES)
                try:
                    sap_connector = SAPConnector(connection)
                    if sap_connector.authenticate():
                        endpoints = sap_connector.get_available_endpoints()
                except Exception:
                    pass
                return JsonResponse({
                    'success': True,
                    'message': message,
                    'modules': endpoints,
                    'endpoints': endpoints,
                    'selected': connection.sap_endpoints or [],
                    'connection_id': str(connection.id),
                    'last_tested_at': connection.last_tested_at.isoformat() if connection.last_tested_at else None
                })
            if success and pk:
                connection.last_tested_at = timezone.now()
                connection.save(update_fields=['last_tested_at'])
                logger.info(f'Updated last_tested_at for API connection {connection.id}')
            return JsonResponse({
                'success': success,
                'message': message,
                'modules': modules if success else [],
                'connection_id': str(connection.id) if pk else None,
                'last_tested_at': connection.last_tested_at.isoformat() if (success and pk and connection.last_tested_at) else None
            })
            
        except APIConnection.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Connection not found'
            }, status=404)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.exception('Error in APIConnectionTestView')
            return JsonResponse({
                'success': False,
                'message': f'Error testing connection: {str(e)}'
            }, status=500)


class APIConnectionModulesView(LoginRequiredMixin, View):
    """AJAX endpoint to get modules (Zoho) or endpoints (SAP) for existing connection"""
    
    def get(self, request, pk):
        from accounts.services.tenant_service import TenantService
        from core.constants import SAP_DOCUMENT_TYPES
        try:
            qs = APIConnection.objects.filter(pk=pk)
            qs = TenantService.get_queryset_for_user(qs, request.user)
            connection = qs.get()
            if connection.api_type == 'sap_b1':
                from connections.connectors.sap import SAPConnector
                endpoints = list(SAP_DOCUMENT_TYPES)
                try:
                    sap_connector = SAPConnector(connection)
                    if sap_connector.authenticate():
                        endpoints = sap_connector.get_available_endpoints()
                except Exception:
                    pass
                return JsonResponse({
                    'success': True,
                    'modules': endpoints,
                    'selected': connection.sap_endpoints or []
                })
            success, message, modules = connection.test_connection()
            if not success:
                return JsonResponse({
                    'success': False,
                    'message': message,
                    'modules': [],
                    'selected': connection.selected_modules or []
                }, status=200)
            return JsonResponse({
                'success': True,
                'modules': modules,
                'selected': connection.selected_modules or []
            })
        except APIConnection.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Connection not found'
            }, status=404)
        except Exception as e:
            logger.exception('Error in APIConnectionModulesView')
            return JsonResponse({
                'success': False,
                'message': f'Error fetching modules: {str(e)}'
            }, status=500)
