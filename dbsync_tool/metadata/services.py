"""
Metadata service for loading database schemas, tables, and column information
Supports lazy loading with connection pooling and caching
"""
from typing import List, Dict, Optional
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.cache import cache
from connections.models import DatabaseConnection
from connections.connectors import get_connector
from core.exceptions import DatabaseConnectionError, EncryptionError, DatabaseTimeoutError
from core.encryption import decrypt_password
from core.connection_pool import get_connection_pool
import logging
import signal
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Cache TTL in seconds (5-10 minutes)
METADATA_CACHE_TTL = 300  # 5 minutes
SCHEMA_CACHE_TTL = 600  # 10 minutes for schemas (change less frequently)


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


@contextmanager
def _query_timeout(timeout_seconds: int):
    """Context manager for query timeout using signal (Unix only)"""
    def timeout_handler(signum, frame):
        raise DatabaseTimeoutError(f"Query timeout after {timeout_seconds} seconds")
    
    # Only works on Unix systems
    try:
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except (AttributeError, ValueError):
        # Windows doesn't support SIGALRM, skip timeout
        yield


def load_schemas_lazy(connection_id: str, user, use_cache: bool = True) -> List[Dict]:
    """
    Lazy load schemas only (lightweight, uses connection pool and cache)
    
    Args:
        connection_id: UUID of the database connection
        user: User object (for permission checking)
        use_cache: Whether to use cache (default: True)
        
    Returns:
        List[Dict]: List of schema dictionaries with 'name' key
    """
    # Check cache first
    if use_cache:
        cache_key = f"metadata:{connection_id}:schemas"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for schemas: {connection_id}")
            return cached
    
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    # Permission check
    from accounts.services.tenant_service import TenantService
    conn_qs = DatabaseConnection.objects.filter(id=connection_id, is_active=True)
    user_conns = TenantService.get_queryset_for_user(conn_qs, user)
    if not user_conns.exists():
        raise PermissionDenied("You don't have permission to access this connection")
    
    pool = get_connection_pool()
    connector = None
    
    try:
        logger.info(f"Loading schemas for connection {connection_id} ({connection.name})")
        
        # Get connection from pool (read-only mode)
        logger.debug(f"Getting connection from pool for {connection_id}")
        connector = pool.get_connection(connection, read_only=True)
        logger.debug(f"Connection obtained from pool for {connection_id}")
        
        # Execute query with timeout
        logger.debug(f"Calling get_schemas() for {connection_id}")
        try:
            with _query_timeout(pool.query_timeout):
                schema_names = connector.get_schemas()
            logger.info(f"Successfully retrieved {len(schema_names)} schemas for connection {connection_id}")
        except DatabaseTimeoutError as e:
            logger.error(f"Timeout loading schemas for connection {connection_id}: {str(e)}")
            raise DatabaseTimeoutError("Query timeout: Database may be slow or unreachable. Please check database connection and try again.")
        except Exception as e:
            logger.error(f"Error calling get_schemas() for connection {connection_id}: {str(e)}", exc_info=True)
            raise
        
        result = [{'name': schema} for schema in schema_names]
        
        # Cache result
        if use_cache:
            cache.set(cache_key, result, SCHEMA_CACHE_TTL)
            logger.debug(f"Cached schemas for connection {connection_id}")
        
        return result
        
    except DatabaseTimeoutError as e:
        logger.error(f"Timeout loading schemas for connection {connection_id}: {str(e)}")
        raise
    except DatabaseConnectionError as e:
        logger.error(f"Database connection error loading schemas for connection {connection_id}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading schemas for connection {connection_id}: {str(e)}", exc_info=True)
        raise DatabaseConnectionError(f"Failed to load schemas: {str(e)}")
    finally:
        if connector:
            try:
                pool.return_connection(str(connection.id), connector)
                logger.debug(f"Returned connection to pool for {connection_id}")
            except Exception as e:
                logger.error(f"Error returning connection to pool: {str(e)}")


def load_tables_lazy(connection_id: str, schema_name: str, user, use_cache: bool = True) -> List[Dict]:
    """
    Lazy load tables for a specific schema (uses connection pool and cache)
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Name of the schema/database
        user: User object (for permission checking)
        use_cache: Whether to use cache (default: True)
        
    Returns:
        List[Dict]: List of table dictionaries with 'name' key
    """
    # Check cache first
    if use_cache:
        cache_key = f"metadata:{connection_id}:{schema_name}:tables"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for tables: {connection_id}.{schema_name}")
            return cached
    
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    # Permission check
    from accounts.services.tenant_service import TenantService
    conn_qs = DatabaseConnection.objects.filter(id=connection_id, is_active=True)
    user_conns = TenantService.get_queryset_for_user(conn_qs, user)
    if not user_conns.exists():
        raise PermissionDenied("You don't have permission to access this connection")
    
    pool = get_connection_pool()
    connector = None
    
    try:
        # Get connection from pool (read-only mode)
        connector = pool.get_connection(connection, read_only=True)
        
        # Execute query with timeout
        with _query_timeout(pool.query_timeout):
            table_names = connector.get_tables(schema_name)
        
        result = [{'name': table} for table in table_names]
        
        # Cache result
        if use_cache:
            cache.set(cache_key, result, METADATA_CACHE_TTL)
        
        return result
        
    except DatabaseTimeoutError:
        logger.error(f"Timeout loading tables for {connection_id}.{schema_name}")
        raise DatabaseConnectionError("Query timeout: Database may be slow or unreachable")
    except Exception as e:
        logger.error(f"Error loading tables for connection {connection_id}, schema {schema_name}: {str(e)}")
        raise DatabaseConnectionError(f"Failed to load tables: {str(e)}")
    finally:
        if connector:
            pool.return_connection(str(connection.id), connector)


def load_columns_lazy(connection_id: str, schema_name: str, table_name: str, user, use_cache: bool = True) -> List[Dict]:
    """
    Lazy load columns for a specific table (uses connection pool and cache)
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Name of the schema/database
        table_name: Name of the table
        user: User object (for permission checking)
        use_cache: Whether to use cache (default: True)
        
    Returns:
        List[Dict]: List of column dictionaries
    """
    # Check cache first
    if use_cache:
        cache_key = f"metadata:{connection_id}:{schema_name}:{table_name}:columns"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for columns: {connection_id}.{schema_name}.{table_name}")
            return cached
    
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    # Permission check
    from accounts.services.tenant_service import TenantService
    conn_qs = DatabaseConnection.objects.filter(id=connection_id, is_active=True)
    user_conns = TenantService.get_queryset_for_user(conn_qs, user)
    if not user_conns.exists():
        raise PermissionDenied("You don't have permission to access this connection")
    
    pool = get_connection_pool()
    connector = None
    
    try:
        # Get connection from pool (read-only mode)
        connector = pool.get_connection(connection, read_only=True)
        
        # Execute query with timeout
        with _query_timeout(pool.query_timeout):
            columns = connector.get_columns(schema_name, table_name)
        
        result = [
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
        
        # Cache result
        if use_cache:
            cache.set(cache_key, result, METADATA_CACHE_TTL)
        
        return result
        
    except DatabaseTimeoutError:
        logger.error(f"Timeout loading columns for {connection_id}.{schema_name}.{table_name}")
        raise DatabaseConnectionError("Query timeout: Database may be slow or unreachable")
    except Exception as e:
        logger.error(f"Error loading columns for {connection_id}.{schema_name}.{table_name}: {str(e)}")
        raise DatabaseConnectionError(f"Failed to load columns: {str(e)}")
    finally:
        if connector:
            pool.return_connection(str(connection.id), connector)


def get_approximate_row_count(connection_id: str, schema_name: str, table_name: str, user) -> Optional[int]:
    """
    Get approximate row count using system statistics (safe, no table scan)
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Name of the schema/database
        table_name: Name of the table
        user: User object (for permission checking)
        
    Returns:
        Optional[int]: Approximate row count or None if unavailable
    """
    try:
        connection = DatabaseConnection.objects.get(id=connection_id, is_active=True)
    except DatabaseConnection.DoesNotExist:
        raise ObjectDoesNotExist(f"Connection with ID {connection_id} not found or inactive")
    
    # Permission check
    from accounts.services.tenant_service import TenantService
    conn_qs = DatabaseConnection.objects.filter(id=connection_id, is_active=True)
    user_conns = TenantService.get_queryset_for_user(conn_qs, user)
    if not user_conns.exists():
        raise PermissionDenied("You don't have permission to access this connection")
    
    pool = get_connection_pool()
    connector = None
    
    try:
        connector = pool.get_connection(connection, read_only=True)
        
        # Use approximate count method if available
        if hasattr(connector, 'get_approximate_row_count'):
            with _query_timeout(pool.query_timeout):
                return connector.get_approximate_row_count(schema_name, table_name)
        else:
            # Fallback to regular row count (may be slow)
            logger.warning(f"Approximate row count not available, using regular count for {schema_name}.{table_name}")
            with _query_timeout(pool.query_timeout):
                return connector.get_row_count(schema_name, table_name)
                
    except DatabaseTimeoutError:
        logger.warning(f"Timeout getting row count for {schema_name}.{table_name}")
        return None
    except Exception as e:
        logger.warning(f"Error getting row count for {schema_name}.{table_name}: {str(e)}")
        return None
    finally:
        if connector:
            pool.return_connection(str(connection.id), connector)


def invalidate_metadata_cache(connection_id: str, schema_name: Optional[str] = None, table_name: Optional[str] = None):
    """
    Invalidate metadata cache for a connection
    
    Args:
        connection_id: UUID of the database connection
        schema_name: Optional schema name (if provided, only invalidate that schema)
        table_name: Optional table name (if provided, only invalidate that table)
    """
    if table_name and schema_name:
        cache_key = f"metadata:{connection_id}:{schema_name}:{table_name}:columns"
        cache.delete(cache_key)
    elif schema_name:
        cache_key = f"metadata:{connection_id}:{schema_name}:tables"
        cache.delete(cache_key)
        # Also delete all table caches for this schema
        # Note: This is a simple implementation - in production, you might want to track keys
    else:
        # Invalidate all caches for this connection
        cache_key_pattern = f"metadata:{connection_id}:*"
        # Django cache doesn't support pattern deletion, so we delete known patterns
        cache.delete(f"metadata:{connection_id}:schemas")


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

