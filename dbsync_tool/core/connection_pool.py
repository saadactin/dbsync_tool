"""
Connection pool manager for database connections
Provides thread-safe connection pooling with timeouts and read-only mode support
"""
import threading
import time
import logging
from typing import Optional, Dict, List
from collections import deque
from connections.connectors.base import DBConnector
from connections.models import DatabaseConnection
from connections.connectors.factory import get_connector
from core.exceptions import DatabaseConnectionError, DatabaseTimeoutError

logger = logging.getLogger(__name__)


class ConnectionPool:
    """
    Thread-safe connection pool for database connectors
    Manages connections per connection_id with max pool size and timeouts
    """
    
    def __init__(
        self,
        max_size: int = 10,
        connection_timeout: int = 3,
        idle_timeout: int = 60,
        query_timeout: int = 5
    ):
        """
        Initialize connection pool
        
        Args:
            max_size: Maximum number of connections per connection_id
            connection_timeout: Connection timeout in seconds
            idle_timeout: Idle connection timeout in seconds
            query_timeout: Query timeout in seconds
        """
        self.max_size = max_size
        self.connection_timeout = connection_timeout
        self.idle_timeout = idle_timeout
        self.query_timeout = query_timeout
        
        # Pool structure: {connection_id: deque([(connector, last_used_time), ...])}
        self._pools: Dict[str, deque] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._pool_lock = threading.Lock()  # Lock for pool dictionary access
        
    def _get_pool_lock(self, connection_id: str) -> threading.Lock:
        """Get or create lock for a specific connection pool"""
        with self._pool_lock:
            if connection_id not in self._locks:
                self._locks[connection_id] = threading.Lock()
            return self._locks[connection_id]
    
    def _get_pool(self, connection_id: str) -> deque:
        """Get or create pool for a specific connection"""
        with self._pool_lock:
            if connection_id not in self._pools:
                self._pools[connection_id] = deque()
            return self._pools[connection_id]
    
    def _create_connector(self, connection: DatabaseConnection, read_only: bool = True) -> DBConnector:
        """
        Create a new connector instance
        
        Args:
            connection: DatabaseConnection model instance
            read_only: Whether to set connection to read-only mode
            
        Returns:
            DBConnector instance
        """
        # Use factory function that takes connection object (it handles decryption internally)
        try:
            connector = get_connector(connection)
        except Exception as e:
            logger.error(f"Failed to create connector for connection {connection.id}: {str(e)}")
            raise DatabaseConnectionError(f"Failed to create connector: {str(e)}")
        
        # Connect with timeout
        try:
            connector.connect()
            
            # Set read-only mode if requested (for metadata queries)
            if read_only and hasattr(connector, '_connection') and connector._connection:
                try:
                    if connection.db_type == 'postgres':
                        import psycopg2
                        with connector._connection.cursor() as cursor:
                            cursor.execute("SET TRANSACTION READ ONLY")
                    elif connection.db_type == 'mysql':
                        with connector._connection.cursor() as cursor:
                            cursor.execute("SET SESSION TRANSACTION READ ONLY")
                    elif connection.db_type == 'sqlserver':
                        # SQL Server doesn't support session-level read-only, but we can use hints
                        pass
                except Exception as e:
                    logger.warning(f"Failed to set read-only mode: {str(e)}")
                    # Continue anyway - read-only is a best practice, not required
            
            return connector
        except Exception as e:
            logger.error(f"Failed to create connector for connection {connection.id}: {str(e)}")
            raise DatabaseConnectionError(f"Connection failed: {str(e)}")
    
    def _cleanup_idle_connections(self, connection_id: str):
        """Remove idle connections that have exceeded idle_timeout"""
        pool = self._get_pool(connection_id)
        lock = self._get_pool_lock(connection_id)
        current_time = time.time()
        
        with lock:
            while pool:
                connector, last_used = pool[0]
                if current_time - last_used > self.idle_timeout:
                    try:
                        connector.close()
                    except Exception as e:
                        logger.warning(f"Error closing idle connection: {str(e)}")
                    pool.popleft()
                else:
                    break
    
    def get_connection(
        self,
        connection: DatabaseConnection,
        read_only: bool = True
    ) -> DBConnector:
        """
        Get a connection from the pool or create a new one
        
        Args:
            connection: DatabaseConnection model instance
            read_only: Whether connection should be read-only (default: True for metadata)
            
        Returns:
            DBConnector instance from pool or newly created
            
        Raises:
            DatabaseConnectionError: If connection fails
            DatabaseTimeoutError: If connection timeout exceeded
        """
        connection_id = str(connection.id)
        pool = self._get_pool(connection_id)
        lock = self._get_pool_lock(connection_id)
        
        # Cleanup idle connections first
        self._cleanup_idle_connections(connection_id)
        
        with lock:
            # Try to get connection from pool
            while pool:
                connector, last_used = pool.popleft()
                
                # Check if connection is still valid
                try:
                    if hasattr(connector, '_connection') and connector._connection:
                        # Test connection with quick query
                        if connection.db_type == 'postgres':
                            import psycopg2
                            with connector._connection.cursor() as cursor:
                                cursor.execute("SELECT 1")
                        elif connection.db_type == 'mysql':
                            with connector._connection.cursor() as cursor:
                                cursor.execute("SELECT 1")
                        elif connection.db_type == 'sqlserver':
                            cursor = connector._connection.cursor()
                            cursor.execute("SELECT 1")
                            cursor.close()
                        
                        # Connection is valid, return it
                        return connector
                except Exception as e:
                    logger.debug(f"Connection validation failed, creating new one: {str(e)}")
                    try:
                        connector.close()
                    except Exception:
                        pass
                    continue
            
            # No available connection in pool, create new one if under limit
            if len(pool) < self.max_size:
                return self._create_connector(connection, read_only)
            else:
                raise DatabaseConnectionError(
                    f"Connection pool exhausted (max {self.max_size} connections). "
                    "Please wait for connections to be released."
                )
    
    def return_connection(self, connection_id: str, connector: DBConnector):
        """
        Return a connection to the pool
        
        Args:
            connection_id: Connection ID string
            connector: DBConnector instance to return
        """
        pool = self._get_pool(connection_id)
        lock = self._get_pool_lock(connection_id)
        
        with lock:
            # Only return if pool is not full
            if len(pool) < self.max_size:
                pool.append((connector, time.time()))
            else:
                # Pool is full, close the connection
                try:
                    connector.close()
                except Exception as e:
                    logger.warning(f"Error closing connection: {str(e)}")
    
    def close_all(self, connection_id: Optional[str] = None):
        """
        Close all connections in pool(s)
        
        Args:
            connection_id: If provided, close only connections for this ID. Otherwise close all.
        """
        with self._pool_lock:
            if connection_id:
                connection_ids = [connection_id]
            else:
                connection_ids = list(self._pools.keys())
        
        for conn_id in connection_ids:
            pool = self._get_pool(conn_id)
            lock = self._get_pool_lock(conn_id)
            
            with lock:
                while pool:
                    connector, _ = pool.popleft()
                    try:
                        connector.close()
                    except Exception as e:
                        logger.warning(f"Error closing connection: {str(e)}")
            
            # Clean up
            with self._pool_lock:
                if conn_id in self._pools:
                    del self._pools[conn_id]
                if conn_id in self._locks:
                    del self._locks[conn_id]


# Global connection pool instance
_global_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()


def get_connection_pool() -> ConnectionPool:
    """Get or create global connection pool instance"""
    global _global_pool
    if _global_pool is None:
        with _pool_lock:
            if _global_pool is None:
                _global_pool = ConnectionPool(
                    max_size=10,
                    connection_timeout=3,
                    idle_timeout=60,
                    query_timeout=5
                )
    return _global_pool


def reset_connection_pool():
    """Reset global connection pool (useful for testing)"""
    global _global_pool
    with _pool_lock:
        if _global_pool:
            _global_pool.close_all()
        _global_pool = None

