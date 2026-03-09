"""
Factory for creating connector instances
"""
from connections.models import DatabaseConnection
from connections.connectors.postgres import PostgresConnector
from connections.connectors.mysql import MySQLConnector
from connections.connectors.sqlserver import SQLServerConnector

try:
    from connections.connectors.clickhouse import ClickHouseConnector
except ImportError:  # pragma: no cover
    ClickHouseConnector = None

try:
    from connections.connectors.oracle_adw import OracleADWConnector
except ImportError:  # pragma: no cover
    OracleADWConnector = None

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

    if connection.db_type == "postgres":
        return PostgresConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name,
        )
    elif connection.db_type == "mysql":
        return MySQLConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name,
        )
    elif connection.db_type == "sqlserver":
        return SQLServerConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name,
        )
    elif connection.db_type == "clickhouse":
        if ClickHouseConnector is None:
            raise InvalidDatabaseTypeError(
                "ClickHouse connector not available. Install clickhouse-connect."
            )
        return ClickHouseConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name,
        )
    elif connection.db_type == "oracle_adw":
        if OracleADWConnector is None:
            raise InvalidDatabaseTypeError(
                "Oracle ADW connector not available. Ensure 'oracledb' is installed."
            )
        # Oracle ADW uses database_name as the service name / TNS alias.
        return OracleADWConnector(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=password,
            database_name=connection.database_name,
        )
    else:
        raise InvalidDatabaseTypeError(
            f"Unsupported database type: {connection.db_type}"
        )

