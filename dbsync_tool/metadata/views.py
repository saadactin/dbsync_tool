"""
API views for metadata loading
"""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import logging

from metadata.services import (
    load_schemas,
    load_tables,
    load_table_columns,
    load_table_metadata,
    get_table_row_count,
    load_all_metadata,
    load_schemas_lazy,
    load_tables_lazy,
    load_columns_lazy,
    get_approximate_row_count,
)
import uuid
from core.exceptions import DatabaseConnectionError, DatabaseTimeoutError
from core.error_responses import error_response_from_exception, ErrorCode, create_error_response
from core.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_schemas_view(request, connection_id):
    """
    API endpoint to load schemas for a connection (lazy loading with cache)
    
    GET /api/metadata/<connection_id>/schemas/
    Query params: use_cache=true/false (default: true)
    """
    # Path parameter validation (UUID)
    try:
        connection_id = str(uuid.UUID(str(connection_id)))
    except (ValueError, TypeError):
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Invalid connection ID format (must be UUID)"),
            trace_id=trace_id
        )
    
    # Query parameter validation
    use_cache = request.GET.get('use_cache', 'true').lower() == 'true'
    
    try:
        # Use lazy loading method with connection pooling and caching
        schemas = load_schemas_lazy(connection_id, request.user, use_cache=use_cache)
        return Response({
            'success': True,
            'data': schemas
        }, status=status.HTTP_200_OK)
    except ObjectDoesNotExist as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except PermissionDenied as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except (DatabaseConnectionError, DatabaseTimeoutError) as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except Exception as e:
        trace_id = ErrorHandler.get_trace_id(request)
        ErrorHandler.log_error(request, e, trace_id)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_tables_view(request, connection_id, schema):
    """
    API endpoint to load tables for a schema (lazy loading with cache)
    
    GET /api/metadata/<connection_id>/schemas/<schema>/tables/
    Query params: use_cache=true/false (default: true)
    """
    # Path parameter validation (UUID)
    try:
        connection_id = str(uuid.UUID(str(connection_id)))
    except (ValueError, TypeError):
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Invalid connection ID format (must be UUID)"),
            trace_id=trace_id
        )
    
    # Schema name validation
    if not schema or not schema.strip():
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Schema name is required"),
            trace_id=trace_id
        )
    
    schema = schema.strip()
    if len(schema) > 100:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Schema name is too long (max 100 characters)"),
            trace_id=trace_id
        )
    
    # Query parameter validation
    use_cache = request.GET.get('use_cache', 'true').lower() == 'true'
    
    try:
        # Use lazy loading method with connection pooling and caching
        tables = load_tables_lazy(connection_id, schema, request.user, use_cache=use_cache)
        return Response({
            'success': True,
            'data': tables
        }, status=status.HTTP_200_OK)
    except ObjectDoesNotExist as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except PermissionDenied as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except (DatabaseConnectionError, DatabaseTimeoutError) as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except Exception as e:
        trace_id = ErrorHandler.get_trace_id(request)
        ErrorHandler.log_error(request, e, trace_id)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_table_columns_view(request, connection_id, schema, table):
    """
    API endpoint to load columns for a table (lazy loading with cache)
    
    GET /api/metadata/<connection_id>/schemas/<schema>/tables/<table>/columns/
    Query params: use_cache=true/false (default: true)
    """
    # Path parameter validation (UUID)
    try:
        connection_id = str(uuid.UUID(str(connection_id)))
    except (ValueError, TypeError):
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Invalid connection ID format (must be UUID)"),
            trace_id=trace_id
        )
    
    # Schema and table name validation
    if not schema or not schema.strip() or not table or not table.strip():
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Schema and table names are required"),
            trace_id=trace_id
        )
    
    schema = schema.strip()
    table = table.strip()
    
    # Query parameter validation
    use_cache = request.GET.get('use_cache', 'true').lower() == 'true'
    
    try:
        # Use lazy loading method with connection pooling and caching
        columns = load_columns_lazy(connection_id, schema, table, request.user, use_cache=use_cache)
        return Response({
            'success': True,
            'data': columns
        }, status=status.HTTP_200_OK)
    except ObjectDoesNotExist as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_404_NOT_FOUND)
    except PermissionDenied as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_403_FORBIDDEN)
    except DatabaseConnectionError as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        logger.error(f"Unexpected error in load_table_columns_view: {str(e)}")
        return Response({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_table_metadata_view(request, connection_id, schema, table):
    """
    API endpoint to load complete metadata for a table
    
    GET /api/metadata/<connection_id>/schemas/<schema>/tables/<table>/
    """
    # Path parameter validation (UUID)
    try:
        connection_id = str(uuid.UUID(str(connection_id)))
    except (ValueError, TypeError):
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Invalid connection ID format (must be UUID)"),
            trace_id=trace_id
        )
    
    # Schema and table name validation
    if not schema or not schema.strip() or not table or not table.strip():
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Schema and table names are required"),
            trace_id=trace_id
        )
    
    schema = schema.strip()
    table = table.strip()
    
    # Query parameter validation
    include_row_count = request.GET.get('include_row_count', 'false').lower()
    if include_row_count not in ['true', 'false']:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("include_row_count must be 'true' or 'false'"),
            trace_id=trace_id
        )
    include_row_count = include_row_count == 'true'
    
    try:
        metadata = load_table_metadata(
            connection_id, 
            schema, 
            table, 
            request.user,
            include_row_count=include_row_count
        )
        return Response({
            'success': True,
            'data': metadata
        }, status=status.HTTP_200_OK)
    except ObjectDoesNotExist as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except PermissionDenied as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except (DatabaseConnectionError, DatabaseTimeoutError) as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except Exception as e:
        trace_id = ErrorHandler.get_trace_id(request)
        ErrorHandler.log_error(request, e, trace_id)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_table_row_count_view(request, connection_id, schema, table):
    """
    API endpoint to get approximate row count for a table (safe, no table scan)
    
    GET /api/metadata/<connection_id>/schemas/<schema>/tables/<table>/row-count/
    Query params: approximate=true/false (default: true) - use approximate count from statistics
    """
    # Path parameter validation (UUID)
    try:
        connection_id = str(uuid.UUID(str(connection_id)))
    except (ValueError, TypeError):
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Invalid connection ID format (must be UUID)"),
            trace_id=trace_id
        )
    
    # Schema and table name validation
    if not schema or not schema.strip() or not table or not table.strip():
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Schema and table names are required"),
            trace_id=trace_id
        )
    
    schema = schema.strip()
    table = table.strip()
    
    # Query parameter validation
    use_approximate = request.GET.get('approximate', 'true').lower() == 'true'
    
    try:
        if use_approximate:
            # Use approximate count (safe, fast, no table scan)
            row_count = get_approximate_row_count(connection_id, schema, table, request.user)
        else:
            # Use exact count (may be slow for large tables)
            row_count = get_table_row_count(connection_id, schema, table, request.user)
        
        return Response({
            'success': True,
            'data': {
                'row_count': row_count,
                'approximate': use_approximate
            }
        }, status=status.HTTP_200_OK)
    except ObjectDoesNotExist as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except PermissionDenied as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except (DatabaseConnectionError, DatabaseTimeoutError) as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except Exception as e:
        trace_id = ErrorHandler.get_trace_id(request)
        ErrorHandler.log_error(request, e, trace_id)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_all_metadata_view(request, connection_id):
    """
    API endpoint to load all metadata for a connection (schemas + tables)
    NOTE: This loads everything at once - consider using lazy loading endpoints instead
    
    GET /api/metadata/<connection_id>/all/
    Query params: include_row_counts=true/false (default: false)
    """
    # Path parameter validation (UUID)
    try:
        connection_id = str(uuid.UUID(str(connection_id)))
    except (ValueError, TypeError):
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("Invalid connection ID format (must be UUID)"),
            trace_id=trace_id
        )
    
    # Query parameter validation
    include_row_counts = request.GET.get('include_row_counts', 'false').lower()
    if include_row_counts not in ['true', 'false']:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            ValidationError("include_row_counts must be 'true' or 'false'"),
            trace_id=trace_id
        )
    include_row_counts = include_row_counts == 'true'
    
    try:
        # Use regular load_all_metadata (not lazy) for backward compatibility
        # But recommend using lazy endpoints for better performance
        metadata = load_all_metadata(connection_id, request.user, include_row_counts=include_row_counts)
        return Response({
            'success': True,
            'data': metadata,
            'warning': 'Consider using lazy loading endpoints (/schemas/, /schemas/<schema>/tables/) for better performance'
        }, status=status.HTTP_200_OK)
    except ObjectDoesNotExist as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except PermissionDenied as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except (DatabaseConnectionError, DatabaseTimeoutError) as e:
        trace_id = ErrorHandler.get_trace_id(request)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
    except Exception as e:
        trace_id = ErrorHandler.get_trace_id(request)
        ErrorHandler.log_error(request, e, trace_id)
        return error_response_from_exception(
            e,
            trace_id=trace_id
        )
