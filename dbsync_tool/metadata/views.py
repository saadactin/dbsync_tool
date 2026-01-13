"""
API views for metadata loading
"""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
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
)
from core.exceptions import DatabaseConnectionError

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_schemas_view(request, connection_id):
    """
    API endpoint to load schemas for a connection
    
    GET /api/metadata/<connection_id>/schemas/
    """
    try:
        schemas = load_schemas(connection_id, request.user)
        return Response({
            'success': True,
            'data': schemas
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
        logger.error(f"Unexpected error in load_schemas_view: {str(e)}")
        return Response({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_tables_view(request, connection_id, schema):
    """
    API endpoint to load tables for a schema
    
    GET /api/metadata/<connection_id>/schemas/<schema>/tables/
    """
    try:
        tables = load_tables(connection_id, schema, request.user)
        return Response({
            'success': True,
            'data': tables
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
        logger.error(f"Unexpected error in load_tables_view: {str(e)}")
        return Response({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_table_columns_view(request, connection_id, schema, table):
    """
    API endpoint to load columns for a table
    
    GET /api/metadata/<connection_id>/schemas/<schema>/tables/<table>/columns/
    """
    try:
        columns = load_table_columns(connection_id, schema, table, request.user)
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
    include_row_count = request.GET.get('include_row_count', 'false').lower() == 'true'
    
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
        logger.error(f"Unexpected error in load_table_metadata_view: {str(e)}")
        return Response({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_table_row_count_view(request, connection_id, schema, table):
    """
    API endpoint to get row count for a table
    
    GET /api/metadata/<connection_id>/schemas/<schema>/tables/<table>/row-count/
    """
    try:
        row_count = get_table_row_count(connection_id, schema, table, request.user)
        return Response({
            'success': True,
            'data': {
                'row_count': row_count
            }
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
        logger.error(f"Unexpected error in get_table_row_count_view: {str(e)}")
        return Response({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_all_metadata_view(request, connection_id):
    """
    API endpoint to load all metadata for a connection (schemas + tables)
    
    GET /api/metadata/<connection_id>/all/
    Query params: include_row_counts=true/false (default: false)
    """
    include_row_counts = request.GET.get('include_row_counts', 'false').lower() == 'true'
    
    try:
        metadata = load_all_metadata(connection_id, request.user, include_row_counts=include_row_counts)
        return Response({
            'success': True,
            'data': metadata
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
        logger.error(f"Unexpected error in load_all_metadata_view: {str(e)}")
        return Response({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
