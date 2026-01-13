"""
Services for connection management
"""
from typing import Tuple
from connections.models import DatabaseConnection, ConnectionTestLog
from connections.connectors import get_connector
from core.exceptions import DatabaseConnectionError, InvalidDatabaseTypeError
from django.contrib.auth.models import User


def test_database_connection(connection: DatabaseConnection, tested_by: User = None) -> Tuple[bool, str]:
    """
    Test a database connection and log the result
    
    Args:
        connection: DatabaseConnection instance to test
        tested_by: User who is testing the connection
        
    Returns:
        tuple: (success: bool, message: str)
    """
    connector = None
    try:
        # Get connector
        connector = get_connector(
            db_type=connection.db_type,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=connection.get_decrypted_password(),
            database_name=connection.database_name
        )
        
        # Test connection
        success = connector.test_connection()
        
        # Log result
        ConnectionTestLog.objects.create(
            connection=connection,
            status='success' if success else 'failed',
            error_message=None if success else "Connection test failed",
            tested_by=tested_by
        )
        
        if success:
            return True, "Connection successful"
        else:
            return False, "Connection test failed"
            
    except InvalidDatabaseTypeError as e:
        error_msg = f"Invalid database type: {str(e)}"
        ConnectionTestLog.objects.create(
            connection=connection,
            status='failed',
            error_message=error_msg,
            tested_by=tested_by
        )
        return False, error_msg
        
    except DatabaseConnectionError as e:
        error_msg = f"Connection error: {str(e)}"
        ConnectionTestLog.objects.create(
            connection=connection,
            status='failed',
            error_message=error_msg,
            tested_by=tested_by
        )
        return False, error_msg
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ConnectionTestLog.objects.create(
            connection=connection,
            status='failed',
            error_message=error_msg,
            tested_by=tested_by
        )
        return False, error_msg
    finally:
        # Ensure connector is closed
        if connector:
            try:
                connector.close()
            except:
                pass

