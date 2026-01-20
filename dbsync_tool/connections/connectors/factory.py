"""
Factory for creating connector instances
"""
from connections.models import DatabaseConnection
from connections.connectors.postgres import PostgresConnector
from connections.connectors.mysql import MySQLConnector
from connections.connectors.sqlserver import SQLServerConnector
from core.encryption import decrypt_password
from connections.connectors.base import DBConnector
from core.exceptions import InvalidDatabaseTypeError

def get_connector(connection: DatabaseConnection) -> DBConnector:
    """
    Get connector instance for a database connection
    
    Args:
        connection: DatabaseConnection model instance
    
    Returns:
        DBConnector instance
        
    Raises:
        InvalidDatabaseTypeError: If database type is not supported
    """
    password = decrypt_password(connection.password)
    
    if connection.db_type == 'postgres':
        return PostgresConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name
        )
    elif connection.db_type == 'mysql':
        return MySQLConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name
        )
    elif connection.db_type == 'sqlserver':
        return SQLServerConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name
        )
    else:
        raise InvalidDatabaseTypeError(f"Unsupported database type: {connection.db_type}")



