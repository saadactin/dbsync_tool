"""
Views for connection management
"""
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied
import json
from .models import DatabaseConnection
from .forms import DatabaseConnectionForm
from .services import test_database_connection
from .connectors import get_connector
from core.exceptions import DatabaseConnectionError, InvalidDatabaseTypeError


class ConnectionListView(LoginRequiredMixin, ListView):
    model = DatabaseConnection
    template_name = 'connections/connection_list.html'
    context_object_name = 'connections'
    paginate_by = 20
    
    def get_queryset(self):
        return DatabaseConnection.objects.filter(
            created_by=self.request.user
        ).select_related('created_by')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connections = self.get_queryset()
        
        # Group by db_type with display information
        db_type_info = {
            'postgres': {'name': 'PostgreSQL', 'connections': []},
            'mysql': {'name': 'MySQL', 'connections': []},
            'sqlserver': {'name': 'SQL Server', 'connections': []}
        }
        
        for conn in connections:
            if conn.db_type in db_type_info:
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
        
        return context


class ConnectionDetailView(LoginRequiredMixin, DetailView):
    model = DatabaseConnection
    template_name = 'connections/connection_detail.html'
    context_object_name = 'connection'
    
    def get_queryset(self):
        return DatabaseConnection.objects.filter(
            created_by=self.request.user
        ).select_related('created_by')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get recent test logs
        context['test_logs'] = self.object.test_logs.all()[:10]
        # Get last test status
        last_test = self.object.test_logs.first()
        context['last_test_status'] = last_test.status if last_test else None
        return context


class ConnectionCreateView(LoginRequiredMixin, CreateView):
    model = DatabaseConnection
    form_class = DatabaseConnectionForm
    template_name = 'connections/connection_form.html'
    success_url = reverse_lazy('connections:list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Connection "{form.instance.name}" created successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class ConnectionUpdateView(LoginRequiredMixin, UpdateView):
    model = DatabaseConnection
    form_class = DatabaseConnectionForm
    template_name = 'connections/connection_form.html'
    success_url = reverse_lazy('connections:list')
    
    def get_queryset(self):
        return DatabaseConnection.objects.filter(
            created_by=self.request.user
        )
    
    def form_valid(self, form):
        messages.success(self.request, f'Connection "{form.instance.name}" updated successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class ConnectionDeleteView(LoginRequiredMixin, DeleteView):
    model = DatabaseConnection
    template_name = 'connections/connection_confirm_delete.html'
    success_url = reverse_lazy('connections:list')
    
    def get_queryset(self):
        return DatabaseConnection.objects.filter(
            created_by=self.request.user
        )
    
    def delete(self, request, *args, **kwargs):
        connection = self.get_object()
        messages.success(request, f'Connection "{connection.name}" deleted successfully!')
        return super().delete(request, *args, **kwargs)


class ConnectionTestView(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            connection = DatabaseConnection.objects.get(
                pk=pk,
                created_by=request.user
            )
        except DatabaseConnection.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Connection not found'
            }, status=404)
        
        success, message = test_database_connection(connection, request.user)
        
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
        try:
            data = json.loads(request.body)
            db_type = data.get('db_type')
            host = data.get('host')
            port = data.get('port')
            username = data.get('username')
            password = data.get('password')
            
            # Validate required fields
            if not all([db_type, host, port, username, password]):
                return JsonResponse({
                    'success': False,
                    'message': 'Missing required fields: db_type, host, port, username, password'
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
            
            # Create connector without database_name
            connector = None
            try:
                connector = get_connector(
                    db_type=db_type,
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    database_name=None  # No database specified
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
                    return JsonResponse({
                        'success': False,
                        'message': f'Connection failed: {str(e)}'
                    }, status=200)
                
            except InvalidDatabaseTypeError as e:
                return JsonResponse({
                    'success': False,
                    'message': str(e)
                }, status=400)
            except DatabaseConnectionError as e:
                return JsonResponse({
                    'success': False,
                    'message': f'Connection failed: {str(e)}'
                }, status=200)
            except Exception as e:
                # Log the full error for debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.exception('Error in ConnectionTestAndListDatabasesView')
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
                    
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Unexpected error: {str(e)}'
            }, status=500)
