"""
Metadata cache utilities for caching database metadata
"""
from django.core.cache import cache
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Cache TTL constants (in seconds)
SCHEMA_CACHE_TTL = 600  # 10 minutes - schemas change infrequently
TABLE_CACHE_TTL = 300   # 5 minutes - tables change less frequently
COLUMN_CACHE_TTL = 300  # 5 minutes - columns change less frequently
ROW_COUNT_CACHE_TTL = 180  # 3 minutes - row counts change frequently


def get_cache_key(connection_id: str, schema_name: Optional[str] = None, 
                  table_name: Optional[str] = None, cache_type: str = 'schemas') -> str:
    """
    Generate cache key for metadata
    
    Args:
        connection_id: Connection UUID
        schema_name: Optional schema name
        table_name: Optional table name
        cache_type: Type of cache ('schemas', 'tables', 'columns', 'row_count')
        
    Returns:
        str: Cache key
    """
    parts = ['metadata', connection_id]
    if schema_name:
        parts.append(schema_name)
    if table_name:
        parts.append(table_name)
    parts.append(cache_type)
    return ':'.join(parts)


def get_cached_schemas(connection_id: str) -> Optional[List[Dict]]:
    """
    Get cached schemas for a connection
    
    Args:
        connection_id: Connection UUID
        
    Returns:
        Optional[List[Dict]]: Cached schemas or None
    """
    cache_key = get_cache_key(connection_id, cache_type='schemas')
    return cache.get(cache_key)


def set_cached_schemas(connection_id: str, schemas: List[Dict], ttl: int = SCHEMA_CACHE_TTL):
    """
    Cache schemas for a connection
    
    Args:
        connection_id: Connection UUID
        schemas: List of schema dictionaries
        ttl: Time to live in seconds
    """
    cache_key = get_cache_key(connection_id, cache_type='schemas')
    cache.set(cache_key, schemas, ttl)
    logger.debug(f"Cached schemas for connection {connection_id}")


def get_cached_tables(connection_id: str, schema_name: str) -> Optional[List[Dict]]:
    """
    Get cached tables for a schema
    
    Args:
        connection_id: Connection UUID
        schema_name: Schema name
        
    Returns:
        Optional[List[Dict]]: Cached tables or None
    """
    cache_key = get_cache_key(connection_id, schema_name=schema_name, cache_type='tables')
    return cache.get(cache_key)


def set_cached_tables(connection_id: str, schema_name: str, tables: List[Dict], 
                     ttl: int = TABLE_CACHE_TTL):
    """
    Cache tables for a schema
    
    Args:
        connection_id: Connection UUID
        schema_name: Schema name
        tables: List of table dictionaries
        ttl: Time to live in seconds
    """
    cache_key = get_cache_key(connection_id, schema_name=schema_name, cache_type='tables')
    cache.set(cache_key, tables, ttl)
    logger.debug(f"Cached tables for {connection_id}.{schema_name}")


def get_cached_columns(connection_id: str, schema_name: str, table_name: str) -> Optional[List[Dict]]:
    """
    Get cached columns for a table
    
    Args:
        connection_id: Connection UUID
        schema_name: Schema name
        table_name: Table name
        
    Returns:
        Optional[List[Dict]]: Cached columns or None
    """
    cache_key = get_cache_key(connection_id, schema_name=schema_name, 
                             table_name=table_name, cache_type='columns')
    return cache.get(cache_key)


def set_cached_columns(connection_id: str, schema_name: str, table_name: str, 
                      columns: List[Dict], ttl: int = COLUMN_CACHE_TTL):
    """
    Cache columns for a table
    
    Args:
        connection_id: Connection UUID
        schema_name: Schema name
        table_name: Table name
        columns: List of column dictionaries
        ttl: Time to live in seconds
    """
    cache_key = get_cache_key(connection_id, schema_name=schema_name, 
                             table_name=table_name, cache_type='columns')
    cache.set(cache_key, columns, ttl)
    logger.debug(f"Cached columns for {connection_id}.{schema_name}.{table_name}")


def invalidate_connection_cache(connection_id: str):
    """
    Invalidate all cached metadata for a connection
    
    Args:
        connection_id: Connection UUID
    """
    # Note: Django cache doesn't support pattern deletion
    # In production with Redis, you could use: cache.delete_pattern(f"metadata:{connection_id}:*")
    # For now, we'll delete known cache keys when connection is updated
    logger.info(f"Cache invalidation requested for connection {connection_id}")
    # Individual cache keys will expire naturally, or can be deleted on connection update


def invalidate_schema_cache(connection_id: str, schema_name: str):
    """
    Invalidate cached metadata for a specific schema
    
    Args:
        connection_id: Connection UUID
        schema_name: Schema name
    """
    # Delete schema cache
    cache_key = get_cache_key(connection_id, cache_type='schemas')
    cache.delete(cache_key)
    
    # Delete tables cache for this schema
    cache_key = get_cache_key(connection_id, schema_name=schema_name, cache_type='tables')
    cache.delete(cache_key)
    
    logger.debug(f"Invalidated cache for {connection_id}.{schema_name}")


def invalidate_table_cache(connection_id: str, schema_name: str, table_name: str):
    """
    Invalidate cached metadata for a specific table
    
    Args:
        connection_id: Connection UUID
        schema_name: Schema name
        table_name: Table name
    """
    # Delete columns cache
    cache_key = get_cache_key(connection_id, schema_name=schema_name, 
                             table_name=table_name, cache_type='columns')
    cache.delete(cache_key)
    
    # Delete row count cache
    cache_key = get_cache_key(connection_id, schema_name=schema_name, 
                             table_name=table_name, cache_type='row_count')
    cache.delete(cache_key)
    
    logger.debug(f"Invalidated cache for {connection_id}.{schema_name}.{table_name}")

