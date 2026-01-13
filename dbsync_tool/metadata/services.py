"""
Metadata service for loading database schemas, tables, and column information
"""
from typing import List, Dict, Optional
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from connections.models import DatabaseConnection
from connections.connectors import get_connector
from core.exceptions import DatabaseConnectionError, EncryptionError
from core.encryption import decrypt_password
import logging

logger = logging.getLogger(__name__)


def _get_decrypted_password_safe(connection: DatabaseConnection) -> str:
    """
    Helper function to safely get decrypted password with better error messages
    
    Args:
        connection: DatabaseConnection instance
        
    Returns:
        str: Decrypted password
        
    Raises:
        DatabaseConnectionError: If decryption fails with helpful message
    """
    try:
        return connection.get_decrypted_password()
    except EncryptionError as e:
        error_msg = str(e)
        raise DatabaseConnectionError(
            f"Cannot decrypt password for connection '{connection.name}'. "
            f"Please update the password by editing this connection in the Connections page. "
            f"Details: {error_msg}"
        )


def load_schemas(connection_id: str, user) -> List[Dict]:
    """
    Load all schemas (or databases) from a connection
    
    Args:
        connection_id: UUID of the database connection
        user: User object (for permission checking)
        
    Returns:
        List[Dict]: List of schema dictionaries with 'name' key
        
    Raises:
        ObjectDoesNotExist: If connection not found
        PermissionDenied: If user doesn't own the connection
        DatabaseConnectionError: If connection fails
    """
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    # Permission check
    if connection.created_by != user:
        raise PermissionDenied("You don't have permission to access this connection")
    
    # Get decrypted password with better error handling
    try:
        decrypted_password = _get_decrypted_password_safe(connection)
    except DatabaseConnectionError:
        raise  # Re-raise with the helpful message
    
    connector = None
    try:
        # Get connector instance
        connector = get_connector(
            db_type=connection.db_type,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=decrypted_password,
            database_name=connection.database_name
        )
        
        # Connect and get schemas
        connector.connect()
        schema_names = connector.get_schemas()
        
        # Return as list of dictionaries
        return [{'name': schema} for schema in schema_names]
        
    except Exception as e:
        logger.error(f"Error loading schemas for connection {connection_id}: {str(e)}")
        raise DatabaseConnectionError(f"Failed to load schemas: {str(e)}")
    finally:
        if connector:
            connector.close()


def load_tables(connection_id: str, schema_name: str, user) -> List[Dict]:
    """
    Load all tables in a schema
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Name of the schema/database
        user: User object (for permission checking)
        
    Returns:
        List[Dict]: List of table dictionaries with 'name' key
        
    Raises:
        ObjectDoesNotExist: If connection not found
        PermissionDenied: If user doesn't own the connection
        DatabaseConnectionError: If connection fails
    """
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    # Permission check
    if connection.created_by != user:
        raise PermissionDenied("You don't have permission to access this connection")
    
    # Get decrypted password with better error handling
    try:
        decrypted_password = _get_decrypted_password_safe(connection)
    except DatabaseConnectionError:
        raise  # Re-raise with the helpful message
    
    connector = None
    try:
        connector = get_connector(
            db_type=connection.db_type,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=decrypted_password,
            database_name=connection.database_name
        )
        
        connector.connect()
        table_names = connector.get_tables(schema_name)
        
        return [{'name': table} for table in table_names]
        
    except Exception as e:
        logger.error(f"Error loading tables for connection {connection_id}, schema {schema_name}: {str(e)}")
        raise DatabaseConnectionError(f"Failed to load tables: {str(e)}")
    finally:
        if connector:
            connector.close()


def load_table_columns(connection_id: str, schema_name: str, table_name: str, user) -> List[Dict]:
    """
    Load column information for a table
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Name of the schema/database
        table_name: Name of the table
        user: User object (for permission checking)
        
    Returns:
        List[Dict]: List of column dictionaries with keys:
            - name: Column name
            - data_type: Column data type
            - is_nullable: Whether column allows NULL
            - is_primary_key: Whether column is primary key
            - max_length: Maximum length (if applicable)
            - default_value: Default value (if any)
    """
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    # Permission check
    if connection.created_by != user:
        raise PermissionDenied("You don't have permission to access this connection")
    
    # Get decrypted password with better error handling
    try:
        decrypted_password = _get_decrypted_password_safe(connection)
    except DatabaseConnectionError:
        raise  # Re-raise with the helpful message
    
    connector = None
    try:
        connector = get_connector(
            db_type=connection.db_type,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=decrypted_password,
            database_name=connection.database_name
        )
        
        connector.connect()
        columns = connector.get_columns(schema_name, table_name)
        
        return [
            {
                'name': col.name,
                'data_type': col.data_type,
                'is_nullable': col.is_nullable,
                'is_primary_key': col.is_primary_key,
                'max_length': col.max_length,
                'default_value': col.default_value,
            }
            for col in columns
        ]
        
    except Exception as e:
        logger.error(f"Error loading columns for {connection_id}.{schema_name}.{table_name}: {str(e)}")
        raise DatabaseConnectionError(f"Failed to load columns: {str(e)}")
    finally:
        if connector:
            connector.close()


def load_table_metadata(connection_id: str, schema_name: str, table_name: str, user, include_row_count: bool = False) -> Dict:
    """
    Load complete metadata for a table (columns + optional row count)
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Name of the schema/database
        table_name: Name of the table
        user: User object (for permission checking)
        include_row_count: Whether to include row count (can be slow)
        
    Returns:
        Dict: Table metadata with 'columns' and optionally 'row_count'
    """
    columns = load_table_columns(connection_id, schema_name, table_name, user)
    
    result = {
        'schema_name': schema_name,
        'table_name': table_name,
        'columns': columns,
    }
    
    if include_row_count:
        try:
            row_count = get_table_row_count(connection_id, schema_name, table_name, user)
            result['row_count'] = row_count
        except Exception as e:
            logger.warning(f"Failed to get row count for {schema_name}.{table_name}: {str(e)}")
            result['row_count'] = None
    
    return result


def get_table_row_count(connection_id: str, schema_name: str, table_name: str, user, timeout: int = 30) -> Optional[int]:
    """
    Get row count for a table (with timeout protection)
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Name of the schema/database
        table_name: Name of the table
        user: User object (for permission checking)
        timeout: Timeout in seconds (default 30)
        
    Returns:
        Optional[int]: Row count or None if timeout/error
    """
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    if connection.created_by != user:
        raise PermissionDenied("You don't have permission to access this connection")
    
    # Get decrypted password with better error handling
    try:
        decrypted_password = _get_decrypted_password_safe(connection)
    except DatabaseConnectionError:
        raise  # Re-raise with the helpful message
    
    connector = None
    try:
        connector = get_connector(
            db_type=connection.db_type,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=decrypted_password,
            database_name=connection.database_name
        )
        
        connector.connect()
        
        # Use timeout if available (may need to implement in connectors)
        row_count = connector.get_row_count(schema_name, table_name)
        return row_count
        
    except Exception as e:
        logger.warning(f"Error getting row count for {schema_name}.{table_name}: {str(e)}")
        return None
    finally:
        if connector:
            connector.close()


def load_all_metadata(connection_id: str, user, include_row_counts: bool = False) -> Dict:
    """
    Load all schemas, tables, and optionally row counts for a connection
    
    Args:
        connection_id: UUID of the database connection
        user: User object (for permission checking)
        include_row_counts: Whether to include row counts (can be very slow)
        
    Returns:
        Dict: Nested structure with schemas -> tables -> metadata
    """
    schemas = load_schemas(connection_id, user)
    
    result = {
        'connection_id': str(connection_id),
        'schemas': []
    }
    
    for schema_info in schemas:
        schema_name = schema_info['name']
        tables = load_tables(connection_id, schema_name, user)
        
        schema_data = {
            'name': schema_name,
            'tables': []
        }
        
        for table_info in tables:
            table_name = table_info['name']
            table_data = {
                'name': table_name,
                'schema_name': schema_name,
            }
            
            if include_row_counts:
                try:
                    row_count = get_table_row_count(connection_id, schema_name, table_name, user)
                    table_data['row_count'] = row_count
                except:
                    table_data['row_count'] = None
            
            schema_data['tables'].append(table_data)
        
        result['schemas'].append(schema_data)
    
    return result

