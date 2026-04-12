"""
Factory for creating connector instances
"""
from connections.models import DatabaseConnection
from connections.connectors import get_connector as get_connector_by_type

from core.encryption import decrypt_password
from connections.connectors.base import DBConnector
from core.exceptions import InvalidDatabaseTypeError


def get_connector(connection: DatabaseConnection) -> DBConnector:
    """
    Get connector instance for a database connection.

    Args:
        connection: DatabaseConnection model instance

    Returns:
        DBConnector instance

    Raises:
        InvalidDatabaseTypeError: If database type is not supported or driver is missing
    """
    password = decrypt_password(connection.password)
    return get_connector_by_type(
        db_type=connection.db_type,
        host=connection.host,
        port=connection.port,
        username=connection.username,
        password=password,
        database_name=connection.database_name,
    )

