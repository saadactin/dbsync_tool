"""
Views for connection management
"""
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import OperationalError
from django.utils import timezone
import json
import logging
import time
import os
import re
from pathlib import Path
from accounts.permissions import ViewerReadOnlyMixin, OperatorOrAboveMixin
from .models import DatabaseConnection, APIConnection, FileSourceConnection
from .forms import DatabaseConnectionForm, APIConnectionForm, FileSourceConnectionForm
from .mongo_local import normalize_mongo_credentials
from .services import test_database_connection
from .timing import elapsed_ms_since
from .connectors import get_connector
from .file_source_paths import resolve_safe_source_path
from core.exceptions import DatabaseConnectionError, InvalidDatabaseTypeError

logger = logging.getLogger('connections.views')


def _save_uploaded_file_source(uploaded_file, relative_path_hint: str) -> str:
    """
    Save uploaded file inside FILE_SYNC_ROOT and return relative path.
    """
    from django.conf import settings

    root = Path(getattr(settings, 'FILE_SYNC_ROOT'))
    root.mkdir(parents=True, exist_ok=True)

    filename = os.path.basename(uploaded_file.name or 'uploaded.csv')
    filename = re.sub(r'[^0-9a-zA-Z._-]', '_', filename)
    if not filename:
        filename = 'uploaded.csv'

    hint = (relative_path_hint or '').strip().replace('\\', '/')
    rel_dir = ''
    if hint:
        rel_dir = os.path.dirname(hint).strip('/').strip()
    if not rel_dir:
        rel_dir = 'uploads'

    target_dir = root / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    stem, ext = os.path.splitext(filename)
    ext = ext or '.csv'
    candidate = target_dir / f"{stem}{ext}"
    counter = 1
    while candidate.exists():
        candidate = target_dir / f"{stem}_{counter}{ext}"
        counter += 1

    with candidate.open('wb+') as dest:
        for chunk in uploaded_file.chunks():
            dest.write(chunk)

    return str(Path(rel_dir) / candidate.name).replace('\\', '/')


def _api_connection_test_details_existing(connection: APIConnection) -> dict:
    """Non-secret metadata for API test JSON responses."""
    d = {'api_type': connection.api_type, 'name': connection.name}
    if connection.api_type == 'zoho_crm':
        d['api_domain'] = connection.api_domain or ''
    elif connection.api_type == 'sap_b1':
        d['sap_base_url'] = (connection.sap_base_url or '').strip()
    elif connection.api_type == 'azure_devops':
        d['organization'] = (connection.organization or '').strip()
    return d


class FileSourceListView(LoginRequiredMixin, ListView):
    model = FileSourceConnection
    template_name = 'connections/file_source_list.html'
    context_object_name = 'file_sources'
    paginate_by = 20

    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = FileSourceConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from accounts.services.tenant_service import TenantService
        db_qs = TenantService.get_queryset_for_user(
            DatabaseConnection.objects.all(), self.request.user
        )
        api_qs = TenantService.get_queryset_for_user(
            APIConnection.objects.all(), self.request.user
        )
        context['db_connections_count'] = db_qs.count()
        context['api_connections_count'] = api_qs.count()
        context['file_sources_count'] = self.get_queryset().count()
        context['active_tab'] = 'flatfiles'
        return context


class FileSourceDetailView(LoginRequiredMixin, DetailView):
    model = FileSourceConnection
    template_name = 'connections/file_source_detail.html'
    context_object_name = 'file_source'

    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = FileSourceConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)


class FileSourceCreateView(ViewerReadOnlyMixin, OperatorOrAboveMixin, CreateView):
    model = FileSourceConnection
    form_class = FileSourceConnectionForm
    template_name = 'connections/file_source_form.html'
    success_url = reverse_lazy('connections:file_source_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        from accounts.services.tenant_service import TenantService
        kwargs['tenant'] = TenantService.get_user_tenant(self.request.user)
        return kwargs

    def form_valid(self, form):
        from accounts.services.tenant_service import TenantService
        instance = form.save(commit=False)
        instance.created_by = self.request.user
        instance.tenant = TenantService.get_user_tenant(self.request.user)
        if instance.tenant is None:
            messages.error(
                self.request,
                "Super Admin cannot create file sources. Please use an Admin account."
            )
            return self.form_invalid(form)
        uploaded_file = self.request.FILES.get('upload_file')
        if uploaded_file:
            instance.relative_path = _save_uploaded_file_source(
                uploaded_file,
                form.cleaned_data.get('relative_path', '')
            )
        instance.save()
        messages.success(self.request, f'File Source "{instance.name}" created successfully!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class FileSourceUpdateView(ViewerReadOnlyMixin, OperatorOrAboveMixin, UpdateView):
    model = FileSourceConnection
    form_class = FileSourceConnectionForm
    template_name = 'connections/file_source_form.html'
    success_url = reverse_lazy('connections:file_source_list')

    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = FileSourceConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['tenant'] = self.get_object().tenant
        return kwargs

    def form_valid(self, form):
        instance = form.save(commit=False)
        uploaded_file = self.request.FILES.get('upload_file')
        if uploaded_file:
            instance.relative_path = _save_uploaded_file_source(
                uploaded_file,
                form.cleaned_data.get('relative_path', '')
            )
        messages.success(self.request, f'File Source "{form.instance.name}" updated successfully!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class FileSourceDeleteView(ViewerReadOnlyMixin, OperatorOrAboveMixin, DeleteView):
    model = FileSourceConnection
    template_name = 'connections/file_source_confirm_delete.html'
    success_url = reverse_lazy('connections:file_source_list')

    def get_queryset(self):
        from accounts.services.tenant_service import TenantService
        qs = FileSourceConnection.objects.all().select_related('created_by', 'tenant')
        return TenantService.get_queryset_for_user(qs, self.request.user)

    def delete(self, request, *args, **kwargs):
        source = self.get_object()
        name = source.name
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'File Source "{name}" deleted successfully!')
        return response


class FileSourceTestView(LoginRequiredMixin, View):
    """AJAX endpoint to validate file source path/readability and sample content."""

    def post(self, request, pk):
        from accounts.services.tenant_service import TenantService
        try:
            qs = FileSourceConnection.objects.filter(pk=pk)
            qs = TenantService.get_queryset_for_user(qs, request.user)
            file_source = qs.get()
        except FileSourceConnection.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'File source not found',
                'latency_ms': 0,
                'details': {},
            }, status=404)

        t0 = time.perf_counter()
        details = {
            'name': file_source.name,
            'relative_path': file_source.relative_path,
            'encoding': file_source.encoding,
            'delimiter': file_source.delimiter,
            'has_header': file_source.has_header,
        }

        try:
            resolved_path = resolve_safe_source_path(file_source.relative_path)
        except ValidationError as exc:
            msg = exc.messages[0] if getattr(exc, 'messages', None) else str(exc)
            return JsonResponse({
                'success': False,
                'message': msg,
                'latency_ms': elapsed_ms_since(t0),
                'details': details,
            }, status=400)

        try:
            if not resolved_path.exists() or not resolved_path.is_file():
                return JsonResponse({
                    'success': False,
                    'message': 'File not found under configured source root.',
                    'latency_ms': elapsed_ms_since(t0),
                    'details': details,
                }, status=200)
            if resolved_path.stat().st_size == 0:
                details['file_size_bytes'] = 0
                return JsonResponse({
                    'success': False,
                    'message': 'File is empty.',
                    'latency_ms': elapsed_ms_since(t0),
                    'details': details,
                }, status=200)

            sample_rows = 0
            with open(resolved_path, 'r', encoding=file_source.encoding, newline='') as fh:
                for _ in range(5):
                    line = fh.readline()
                    if not line:
                        break
                    sample_rows += 1
            details['file_size_bytes'] = resolved_path.stat().st_size
            details['sample_rows_read'] = sample_rows
            return JsonResponse({
                'success': True,
                'message': f'File source test successful. Sampled {sample_rows} row(s).',
                'latency_ms': elapsed_ms_since(t0),
                'details': details,
            }, status=200)
        except PermissionError:
            return JsonResponse({
                'success': False,
                'message': 'Server cannot read file. Check file permissions.',
                'latency_ms': elapsed_ms_since(t0),
                'details': details,
            }, status=200)
        except UnicodeDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Encoding mismatch while reading file. Please verify encoding.',
                'latency_ms': elapsed_ms_since(t0),
                'details': details,
            }, status=200)
        except Exception as exc:
            logger.exception('Error in FileSourceTestView')
            return JsonResponse({
                'success': False,
                'message': f'Error testing file source: {str(exc)}',
                'latency_ms': elapsed_ms_since(t0),
                'details': details,
            }, status=500)


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
            'mongodb': {'name': 'MongoDB', 'connections': []},
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
        context['db_connections_count'] = context['total_connections']
        
        # Add API connections count for navigation
        from accounts.services.tenant_service import TenantService
        api_qs = APIConnection.objects.all().select_related('created_by', 'tenant')
        api_qs = TenantService.get_queryset_for_user(api_qs, self.request.user)
        context['api_connections_count'] = api_qs.count()
        file_qs = FileSourceConnection.objects.all().select_related('created_by', 'tenant')
        file_qs = TenantService.get_queryset_for_user(file_qs, self.request.user)
        context['file_sources_count'] = file_qs.count()
        context['active_tab'] = 'databases'
        
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
        # Log detailed form errors for debugging API connection creation issues
        logger.error("APIConnectionCreateView form_invalid errors: %s", form.errors.as_json())
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

        def _do_delete():
            return super(ConnectionDeleteView, self).delete(request, *args, **kwargs)

        try:
            result = _do_delete()
        except OperationalError as exc:
            # CASCADE delete touches sync_jobs → mongo_cdc_checkpoints; if migrations
            # were never applied locally, the table is missing. Apply migrations once
            # and retry so deletes work without relying on a manual migrate step.
            if "mongo_cdc_checkpoints" not in str(exc).lower():
                raise
            logger.warning(
                "Connection delete failed (likely missing mongo_cdc_checkpoints); "
                "running migrate and retrying once.",
                extra={"error": str(exc), "connection_id": str(connection_id)},
                exc_info=True,
            )
            try:
                call_command("migrate", verbosity=0, interactive=False)
            except Exception as mig_exc:
                logger.exception("migrate during connection delete failed")
                raise exc from mig_exc
            result = _do_delete()

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
        
        result = test_database_connection(connection, request.user)
        success = result["success"]

        # Update last_tested_at if test is successful
        if success:
            from django.utils import timezone
            connection.last_tested_at = timezone.now()
            connection.save(update_fields=['last_tested_at'])

        return JsonResponse({
            'success': success,
            'message': result['message'],
            'latency_ms': result['latency_ms'],
            'details': result.get('details') or {},
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
            username = (data.get('username') or '').strip()
            # JSON may send null; treat as empty (same as an empty password field).
            password = data.get('password')
            if password is None:
                password = ''
            database_name = (data.get('database_name') or '').strip() or None

            if not all([db_type, host, port]):
                return JsonResponse({
                    'success': False,
                    'message': 'Missing required fields: db_type, host, port',
                    'latency_ms': 0,
                    'details': {},
                }, status=400)

            # Align JSON test endpoint with `DatabaseConnectionForm` rules for MongoDB localhost.
            if db_type == 'mongodb':
                try:
                    username, password = normalize_mongo_credentials(host, username, password)
                except ValueError as e:
                    return JsonResponse({
                        'success': False,
                        'message': str(e),
                        'latency_ms': 0,
                        'details': {'db_type': db_type, 'host': host or '', 'port': port},
                    }, status=400)
            else:
                if not username or not password:
                    return JsonResponse({
                        'success': False,
                        'message': 'Missing required fields: username, password',
                        'latency_ms': 0,
                        'details': {},
                    }, status=400)
            if db_type == 'oracle_adw' and not database_name:
                return JsonResponse({
                    'success': False,
                    'message': 'Service name (Oracle ADW) is required. Use the service name from your JDBC/connection string.',
                    'latency_ms': 0,
                    'details': {'db_type': db_type, 'host': host or '', 'port': port},
                }, status=400)

            try:
                port = int(port)
                if port < 1 or port > 65535:
                    return JsonResponse({
                        'success': False,
                        'message': 'Port must be between 1 and 65535',
                        'latency_ms': 0,
                        'details': {'db_type': db_type, 'host': host or '', 'port': port},
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Port must be a valid number',
                    'latency_ms': 0,
                    'details': {'db_type': db_type, 'host': host or '', 'port': str(port)},
                }, status=400)

            details = {
                'db_type': db_type,
                'host': host,
                'port': port,
                'database_name': database_name or '',
            }
            t0 = time.perf_counter()
            try:
                connector = get_connector(
                    db_type=db_type,
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    database_name=database_name,
                )
                databases = connector.list_databases()
                return JsonResponse({
                    'success': True,
                    'message': f'Connection successful! Found {len(databases)} database(s).',
                    'databases': databases,
                    'latency_ms': elapsed_ms_since(t0),
                    'details': details,
                })
            except DatabaseConnectionError as e:
                error_msg = str(e)
                logger.error(f"Connection test failed: {error_msg}")
                return JsonResponse({
                    'success': False,
                    'message': f'Connection failed: {error_msg}',
                    'latency_ms': elapsed_ms_since(t0),
                    'details': details,
                }, status=200)
            except InvalidDatabaseTypeError as e:
                logger.error(f"Invalid database type: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'message': str(e),
                    'latency_ms': elapsed_ms_since(t0),
                    'details': details,
                }, status=400)
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.exception('Error in ConnectionTestAndListDatabasesView')
                logger.error(f'Full traceback: {error_trace}')
                return JsonResponse({
                    'success': False,
                    'message': f'Unexpected error: {str(e)}',
                    'latency_ms': elapsed_ms_since(t0),
                    'details': details,
                }, status=500)
            finally:
                if connector:
                    try:
                        connector.close()
                    except Exception:
                        pass

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': 'Invalid JSON in request body',
                'latency_ms': 0,
                'details': {},
            }, status=400)
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.exception('Unexpected error in ConnectionTestAndListDatabasesView')
            logger.error(f'Full traceback: {error_trace}')
            return JsonResponse({
                'success': False,
                'message': f'Unexpected error: {str(e)}',
                'latency_ms': 0,
                'details': {},
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
        
        # Group by api_type (include all known types so SAP, Azure DevOps, and others appear)
        api_type_info = {
            'zoho_crm': {'name': 'Zoho CRM', 'connections': []},
            'sap_b1': {'name': 'SAP Business One', 'connections': []},
            'azure_devops': {'name': 'Azure DevOps', 'connections': []},
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
        context['api_connections_count'] = context['total_connections']
        from accounts.services.tenant_service import TenantService
        db_qs = TenantService.get_queryset_for_user(
            DatabaseConnection.objects.all().select_related('created_by', 'tenant'),
            self.request.user,
        )
        file_qs = TenantService.get_queryset_for_user(
            FileSourceConnection.objects.all().select_related('created_by', 'tenant'),
            self.request.user,
        )
        context['db_connections_count'] = db_qs.count()
        context['file_sources_count'] = file_qs.count()
        context['active_tab'] = 'apis'
        
        return context


class ConnectionCreateHubView(LoginRequiredMixin, TemplateView):
    template_name = 'connections/connection_create_hub.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from accounts.services.tenant_service import TenantService
        db_qs = TenantService.get_queryset_for_user(
            DatabaseConnection.objects.all().select_related('created_by', 'tenant'),
            self.request.user,
        )
        api_qs = TenantService.get_queryset_for_user(
            APIConnection.objects.all().select_related('created_by', 'tenant'),
            self.request.user,
        )
        file_qs = TenantService.get_queryset_for_user(
            FileSourceConnection.objects.all().select_related('created_by', 'tenant'),
            self.request.user,
        )
        context['db_connections_count'] = db_qs.count()
        context['api_connections_count'] = api_qs.count()
        context['file_sources_count'] = file_qs.count()
        context['active_tab'] = 'add'
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
                qs = APIConnection.objects.filter(pk=pk)
                qs = TenantService.get_queryset_for_user(qs, request.user)
                connection = qs.get()
            else:
                data = json.loads(request.body)
                api_type = data.get('api_type', 'zoho_crm')
                if api_type == 'sap_b1':
                    sap_base_url = (data.get('sap_base_url') or '').strip()
                    sap_user_name = (data.get('sap_user_name') or '').strip()
                    sap_company_db = (data.get('sap_company_db') or '').strip()
                    sap_password = data.get('sap_password') or ''
                    details = {'api_type': 'sap_b1', 'sap_base_url': sap_base_url}
                    if not sap_base_url or not sap_user_name or not sap_company_db or not sap_password:
                        return JsonResponse({
                            'success': False,
                            'message': 'Missing required SAP fields: sap_base_url, sap_user_name, sap_company_db, sap_password',
                            'latency_ms': 0,
                            'details': details,
                        }, status=400)
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
                    t0 = time.perf_counter()
                    connector = SAPConnector(temp_connection)
                    if not connector.authenticate():
                        return JsonResponse({
                            'success': False,
                            'message': 'SAP authentication failed. Please check your credentials.',
                            'latency_ms': elapsed_ms_since(t0),
                            'details': details,
                        })
                    try:
                        endpoints = connector.get_available_endpoints()
                    except Exception as e:
                        logger.exception('SAP get_available_endpoints failed')
                        return JsonResponse({
                            'success': False,
                            'message': f'Connection authenticated but failed to fetch endpoints: {str(e)}',
                            'latency_ms': elapsed_ms_since(t0),
                            'details': details,
                        })
                    return JsonResponse({
                        'success': True,
                        'message': 'Credentials accepted. Select endpoints below (fetched from your server).',
                        'endpoints': endpoints,
                        'modules': endpoints,
                        'latency_ms': elapsed_ms_since(t0),
                        'details': details,
                    })
                if api_type == 'azure_devops':
                    organization = (data.get('organization') or '').strip()
                    azure_tenant_id = (data.get('azure_tenant_id') or '').strip()
                    azure_client_id = (data.get('azure_client_id') or '').strip()
                    azure_client_secret = data.get('azure_client_secret') or ''
                    details = {
                        'api_type': 'azure_devops',
                        'organization': organization,
                    }
                    if not all([organization, azure_tenant_id, azure_client_id, azure_client_secret]):
                        return JsonResponse({
                            'success': False,
                            'message': 'Missing required Azure DevOps fields: organization, azure_tenant_id, azure_client_id, azure_client_secret',
                            'latency_ms': 0,
                            'details': details,
                        }, status=400)
                    from connections.connectors.azure_devops import AzureDevOpsConnector
                    temp_connection = APIConnection()
                    temp_connection.name = data.get('name', 'Test Connection')
                    temp_connection.api_type = 'azure_devops'
                    temp_connection.organization = organization
                    temp_connection.azure_tenant_id = azure_tenant_id
                    temp_connection.azure_client_id = azure_client_id

                    def get_test_connection_params():
                        return {
                            'tenant_id': azure_tenant_id,
                            'client_id': azure_client_id,
                            'client_secret': azure_client_secret,
                            'organization': organization,
                        }

                    temp_connection.get_connection_params = get_test_connection_params  # type: ignore[attr-defined]
                    t0 = time.perf_counter()
                    connector = AzureDevOpsConnector(temp_connection)
                    if not connector.authenticate():
                        return JsonResponse({
                            'success': False,
                            'message': 'Azure DevOps authentication failed. Please check your credentials.',
                            'modules': [],
                            'latency_ms': elapsed_ms_since(t0),
                            'details': details,
                        })
                    try:
                        projects = connector.get_available_modules()
                        return JsonResponse({
                            'success': True,
                            'message': f'Connection successful! Found {len(projects)} project(s).',
                            'modules': projects,
                            'latency_ms': elapsed_ms_since(t0),
                            'details': details,
                        })
                    except Exception as e:
                        logger.exception('Azure DevOps get_available_modules failed')
                        return JsonResponse({
                            'success': False,
                            'message': f'Connection authenticated but failed to fetch projects: {str(e)}',
                            'modules': [],
                            'latency_ms': elapsed_ms_since(t0),
                            'details': details,
                        })
                client_id = data.get('client_id', '').strip()
                client_secret = data.get('client_secret', '').strip()
                refresh_token = data.get('refresh_token', '').strip()
                api_domain = data.get('api_domain', '').strip()
                token_url = data.get('token_url', '').strip()
                details = {'api_type': api_type, 'api_domain': api_domain}
                if not all([client_id, client_secret, refresh_token, api_domain]):
                    return JsonResponse({
                        'success': False,
                        'message': 'Missing required fields: client_id, client_secret, refresh_token, api_domain',
                        'latency_ms': 0,
                        'details': details,
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
                t0 = time.perf_counter()
                connector = ZohoConnector(temp_connection)
                if not connector.authenticate():
                    return JsonResponse({
                        'success': False,
                        'message': 'Authentication failed. Please check your credentials.',
                        'latency_ms': elapsed_ms_since(t0),
                        'details': details,
                    })
                try:
                    modules = connector.get_available_modules()
                    return JsonResponse({
                        'success': True,
                        'message': f'Connection successful! Found {len(modules)} modules.',
                        'modules': modules,
                        'latency_ms': elapsed_ms_since(t0),
                        'details': details,
                    })
                except Exception as e:
                    logger.exception('Error getting modules')
                    return JsonResponse({
                        'success': False,
                        'message': f'Connection authenticated but failed to fetch modules: {str(e)}',
                        'latency_ms': elapsed_ms_since(t0),
                        'details': details,
                    })

            details_existing = _api_connection_test_details_existing(connection)
            t0 = time.perf_counter()
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
                if success:
                    connection.last_tested_at = timezone.now()
                    connection.save(update_fields=['last_tested_at'])
                return JsonResponse({
                    'success': success,
                    'message': message,
                    'modules': endpoints,
                    'endpoints': endpoints,
                    'selected': connection.sap_endpoints or [],
                    'connection_id': str(connection.id),
                    'last_tested_at': connection.last_tested_at.isoformat() if connection.last_tested_at else None,
                    'latency_ms': elapsed_ms_since(t0),
                    'details': details_existing,
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
                'last_tested_at': connection.last_tested_at.isoformat() if (success and pk and connection.last_tested_at) else None,
                'latency_ms': elapsed_ms_since(t0),
                'details': details_existing,
            })

        except APIConnection.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Connection not found',
                'latency_ms': 0,
                'details': {},
            }, status=404)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid JSON in request body',
                'latency_ms': 0,
                'details': {},
            }, status=400)
        except Exception as e:
            logger.exception('Error in APIConnectionTestView')
            return JsonResponse({
                'success': False,
                'message': f'Error testing connection: {str(e)}',
                'latency_ms': 0,
                'details': {},
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
            if connection.api_type == 'azure_devops':
                # For Azure DevOps, return stored project names as modules and selected
                # Optionally could re-test connection here, but not required for edit UI
                modules = connection.selected_modules or []
                return JsonResponse({
                    'success': True,
                    'modules': modules,
                    'selected': modules,
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
