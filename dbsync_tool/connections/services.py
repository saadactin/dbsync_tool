"""
Services for connection management
"""
import time
from typing import Any, Dict, Optional

from django.contrib.auth.models import User

from connections.models import DatabaseConnection, ConnectionTestLog
from connections.connectors import get_connector
from connections.timing import elapsed_ms_since
from core.exceptions import DatabaseConnectionError, InvalidDatabaseTypeError


def _connection_test_details(connection: DatabaseConnection) -> Dict[str, Any]:
    return {
        "name": connection.name,
        "db_type": connection.db_type,
        "host": connection.host,
        "port": connection.port,
        "database_name": connection.database_name,
    }


def test_database_connection(
    connection: DatabaseConnection, tested_by: Optional[User] = None
) -> Dict[str, Any]:
    """
    Test a database connection and log the result.

    Returns:
        dict with keys: success (bool), message (str), latency_ms (int),
        details (dict of non-secret connection metadata).
    """
    connector = None
    t0 = time.perf_counter()
    details = _connection_test_details(connection)

    def _result(success: bool, message: str) -> Dict[str, Any]:
        return {
            "success": success,
            "message": message,
            "latency_ms": elapsed_ms_since(t0),
            "details": details,
        }

    try:
        connector = get_connector(
            db_type=connection.db_type,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=connection.get_decrypted_password(),
            database_name=connection.database_name,
        )

        success = connector.test_connection()

        ConnectionTestLog.objects.create(
            connection=connection,
            status="success" if success else "failed",
            error_message=None if success else "Connection test failed",
            tested_by=tested_by,
        )

        if success:
            return _result(True, "Connection successful")
        return _result(False, "Connection test failed")

    except InvalidDatabaseTypeError as e:
        error_msg = f"Invalid database type: {str(e)}"
        ConnectionTestLog.objects.create(
            connection=connection,
            status="failed",
            error_message=error_msg,
            tested_by=tested_by,
        )
        return _result(False, error_msg)

    except DatabaseConnectionError as e:
        error_msg = f"Connection error: {str(e)}"
        ConnectionTestLog.objects.create(
            connection=connection,
            status="failed",
            error_message=error_msg,
            tested_by=tested_by,
        )
        return _result(False, error_msg)

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ConnectionTestLog.objects.create(
            connection=connection,
            status="failed",
            error_message=error_msg,
            tested_by=tested_by,
        )
        return _result(False, error_msg)
    finally:
        if connector:
            try:
                connector.close()
            except Exception:
                pass
