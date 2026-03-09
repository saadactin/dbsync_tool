"""
Connector factory and imports
"""
from .base import DBConnector, ColumnInfo
from .api_base import APIConnector
from core.exceptions import InvalidDatabaseTypeError

# Import connectors (database)
try:
    from .postgres import PostgresConnector
except ImportError:  # pragma: no cover - environment-specific
    PostgresConnector = None

try:
    from .mysql import MySQLConnector
except ImportError:  # pragma: no cover
    MySQLConnector = None

try:
    from .sqlserver import SQLServerConnector
except ImportError:  # pragma: no cover
    SQLServerConnector = None

try:
    from .clickhouse import ClickHouseConnector
except ImportError:  # pragma: no cover
    ClickHouseConnector = None

try:
    from .oracle_adw import OracleADWConnector
except ImportError:  # pragma: no cover
    OracleADWConnector = None

# Import API connectors
try:
    from .zoho import ZohoConnector
except ImportError:  # pragma: no cover
    ZohoConnector = None

try:
    from .sap import SAPConnector
except ImportError:  # pragma: no cover
    SAPConnector = None


def get_connector(
    db_type: str,
    host: str,
    port: int,
    username: str,
    password: str,
    database_name: str = None,
) -> DBConnector:
    """
    Factory function to create appropriate connector based on database type.

    Args:
        db_type: Database type ('postgres', 'mysql', 'sqlserver', 'clickhouse', 'oracle_adw')
        host: Database host
        port: Database port
        username: Database username
        password: Database password (plaintext)
        database_name: Database name or service name (optional, for listing databases)

    Returns:
        DBConnector: Appropriate connector instance

    Raises:
        InvalidDatabaseTypeError: If database type is not supported or required driver is missing
    """
    if db_type == "postgres":
        if PostgresConnector is None:
            raise InvalidDatabaseTypeError(
                "PostgreSQL connector not available. Install psycopg2-binary."
            )
        return PostgresConnector(host, port, username, password, database_name)
    elif db_type == "mysql":
        if MySQLConnector is None:
            raise InvalidDatabaseTypeError(
                "MySQL connector not available. Install mysql-connector-python."
            )
        return MySQLConnector(host, port, username, password, database_name)
    elif db_type == "sqlserver":
        if SQLServerConnector is None:
            raise InvalidDatabaseTypeError(
                "SQL Server connector not available. Install pyodbc and ODBC driver."
            )
        return SQLServerConnector(host, port, username, password, database_name)
    elif db_type == "clickhouse":
        if ClickHouseConnector is None:
            raise InvalidDatabaseTypeError(
                "ClickHouse connector not available. Install clickhouse-connect."
            )
        return ClickHouseConnector(host, port, username, password, database_name)
    elif db_type == "oracle_adw":
        if OracleADWConnector is None:
            raise InvalidDatabaseTypeError(
                "Oracle ADW connector not available. Ensure 'oracledb' is installed."
            )
        # For Oracle ADW we treat database_name as the service name / TNS alias.
        return OracleADWConnector(host, port, username, password, database_name)
    else:
        raise InvalidDatabaseTypeError(f"Unsupported database type: {db_type}")


def get_api_connector(api_connection) -> APIConnector:
    """
    Factory function to create appropriate API connector based on API connection.

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

    if api_connection.api_type == "zoho_crm":
        if ZohoConnector is None:
            raise InvalidDatabaseTypeError("Zoho CRM connector not available.")
        return ZohoConnector(api_connection)
    elif api_connection.api_type == "sap_b1":
        if SAPConnector is None:
            raise InvalidDatabaseTypeError("SAP B1 connector not available.")
        return SAPConnector(api_connection)
    else:
        raise InvalidDatabaseTypeError(
            f"Unsupported API type: {api_connection.api_type}"
        )

