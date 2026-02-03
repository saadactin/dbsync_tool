"""
Connector factory and imports
"""
from .base import DBConnector, ColumnInfo
from .api_base import APIConnector
from core.exceptions import InvalidDatabaseTypeError

# Import connectors (will be created in Day 5-6)
try:
    from .postgres import PostgresConnector
except ImportError:
    PostgresConnector = None

try:
    from .mysql import MySQLConnector
except ImportError:
    MySQLConnector = None

try:
    from .sqlserver import SQLServerConnector
except ImportError:
    SQLServerConnector = None

try:
    from .clickhouse import ClickHouseConnector
except ImportError:
    ClickHouseConnector = None

# Import API connectors
try:
    from .zoho import ZohoConnector
except ImportError:
    ZohoConnector = None


def get_connector(db_type: str, host: str, port: int, username: str, password: str, database_name: str = None) -> DBConnector:
    """
    Factory function to create appropriate connector based on database type
    
    Args:
        db_type: Database type ('postgres', 'mysql', 'sqlserver', 'clickhouse')
        host: Database host
        port: Database port
        username: Database username
        password: Database password
        database_name: Database name (optional, for listing databases)
        
    Returns:
        DBConnector: Appropriate connector instance
        
    Raises:
        InvalidDatabaseTypeError: If database type is not supported
    """
    if db_type == 'postgres':
        if PostgresConnector is None:
            raise InvalidDatabaseTypeError("PostgreSQL connector not available. Install psycopg2-binary.")
        return PostgresConnector(host, port, username, password, database_name)
    elif db_type == 'mysql':
        if MySQLConnector is None:
            raise InvalidDatabaseTypeError("MySQL connector not available. Install mysql-connector-python.")
        return MySQLConnector(host, port, username, password, database_name)
    elif db_type == 'sqlserver':
        if SQLServerConnector is None:
            raise InvalidDatabaseTypeError("SQL Server connector not available. Install pyodbc and ODBC driver.")
        return SQLServerConnector(host, port, username, password, database_name)
    elif db_type == 'clickhouse':
        if ClickHouseConnector is None:
            raise InvalidDatabaseTypeError("ClickHouse connector not available. Install clickhouse-connect.")
        return ClickHouseConnector(host, port, username, password, database_name)
    else:
        raise InvalidDatabaseTypeError(f"Unsupported database type: {db_type}")


def get_api_connector(api_connection) -> APIConnector:
    """
    Factory function to create appropriate API connector based on API connection
    
    Args:
        api_connection: APIConnection model instance
        
    Returns:
        APIConnector: Appropriate API connector instance
        
    Raises:
        InvalidDatabaseTypeError: If API type is not supported
    """
    from connections.models import APIConnection
    
    if not isinstance(api_connection, APIConnection):
        raise ValueError("api_connection must be an APIConnection instance")
    
    if api_connection.api_type == 'zoho_crm':
        if ZohoConnector is None:
            raise InvalidDatabaseTypeError("Zoho CRM connector not available.")
        return ZohoConnector(api_connection)
    else:
        raise InvalidDatabaseTypeError(f"Unsupported API type: {api_connection.api_type}")

