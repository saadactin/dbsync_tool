"""
Daily Health Check Service - Tests all connections (DB, API, Files)
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from django.utils import timezone
from django.db.models import Q

from .models import DatabaseConnection, APIConnection, FileSourceConnection
from .connectors import get_connector
from core.exceptions import DatabaseConnectionError

logger = logging.getLogger(__name__)


class ConnectionHealthCheck:
    """Service to test all connections and track health status."""

    def __init__(self):
        self.results = {
            'database': [],
            'api': [],
            'file': [],
        }
        self.total_tested = 0
        self.total_passed = 0
        self.total_failed = 0

    def test_all_connections(self, tenant=None) -> Dict:
        """
        Test all connections for a tenant (or all if tenant=None).

        Returns:
            {
                'tested_at': datetime,
                'total_tested': int,
                'total_passed': int,
                'total_failed': int,
                'database': [{name, status, error}, ...],
                'api': [{name, status, error}, ...],
                'file': [{name, status, error}, ...],
            }
        """
        logger.info("Starting health check for all connections")

        # Test database connections
        db_connections = DatabaseConnection.objects.all()
        if tenant:
            db_connections = db_connections.filter(tenant=tenant)

        for conn in db_connections:
            result = self._test_database_connection(conn)
            self.results['database'].append(result)
            self.total_tested += 1
            if result['status'] == 'passed':
                self.total_passed += 1
            else:
                self.total_failed += 1

        # Test API connections
        api_connections = APIConnection.objects.all()
        if tenant:
            api_connections = api_connections.filter(tenant=tenant)

        for conn in api_connections:
            result = self._test_api_connection(conn)
            self.results['api'].append(result)
            self.total_tested += 1
            if result['status'] == 'passed':
                self.total_passed += 1
            else:
                self.total_failed += 1

        # Test file source connections
        file_connections = FileSourceConnection.objects.all()
        if tenant:
            file_connections = file_connections.filter(tenant=tenant)

        for conn in file_connections:
            result = self._test_file_connection(conn)
            self.results['file'].append(result)
            self.total_tested += 1
            if result['status'] == 'passed':
                self.total_passed += 1
            else:
                self.total_failed += 1

        tested_at = timezone.now()
        return {
            'tested_at': tested_at.isoformat(),
            'total_tested': self.total_tested,
            'total_passed': self.total_passed,
            'total_failed': self.total_failed,
            'database': self.results['database'],
            'api': self.results['api'],
            'file': self.results['file'],
        }

    def _test_database_connection(self, conn: DatabaseConnection) -> Dict:
        """Test a single database connection."""
        result = {
            'id': str(conn.id),
            'name': conn.name,
            'type': conn.db_type,
            'host': conn.host,
            'status': 'failed',
            'error': None,
            'tested_at': timezone.now().isoformat(),
        }

        try:
            logger.debug(f"Testing database connection: {conn.name} ({conn.db_type})")

            # Get decrypted password
            password = conn.get_decrypted_password()

            # Get connector and test connection
            connector = get_connector(
                db_type=conn.db_type,
                host=conn.host,
                port=conn.port,
                username=conn.username,
                password=password,
                database_name=conn.database_name
            )
            connector.connect()

            # Try a simple query to verify it works
            connector.test_connection()

            connector.close()

            result['status'] = 'passed'
            logger.info(f"✅ Database connection test passed: {conn.name}")

        except DatabaseConnectionError as e:
            result['error'] = f"Connection failed: {str(e)}"
            logger.warning(f"❌ Database connection test failed: {conn.name} - {e}")
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            logger.error(f"❌ Database connection test error: {conn.name} - {e}", exc_info=True)

        return result

    def _test_api_connection(self, conn: APIConnection) -> Dict:
        """Test a single API connection."""
        result = {
            'id': str(conn.id),
            'name': conn.name,
            'type': conn.api_type,
            'url': getattr(conn, 'base_url', None) or getattr(conn, 'sap_base_url', None) or getattr(conn, 'zoho_api_domain', None),
            'status': 'failed',
            'error': None,
            'tested_at': timezone.now().isoformat(),
        }

        try:
            logger.debug(f"Testing API connection: {conn.name} ({conn.api_type})")

            # Get connector and test connection
            from connections.connectors.api_base import get_api_connector
            connector = get_api_connector(conn)

            # Test authentication/connection
            if hasattr(connector, 'test_connection'):
                connector.test_connection()
            elif hasattr(connector, 'authenticate'):
                connector.authenticate()
            else:
                # Fallback: just check if connector was created
                pass

            result['status'] = 'passed'
            logger.info(f"✅ API connection test passed: {conn.name}")

        except Exception as e:
            result['error'] = f"Connection failed: {str(e)}"
            logger.warning(f"❌ API connection test failed: {conn.name} - {e}")

        return result

    def _test_file_connection(self, conn: FileSourceConnection) -> Dict:
        """Test a single file source connection."""
        result = {
            'id': str(conn.id),
            'name': conn.name,
            'type': 'file',
            'path': conn.relative_path,
            'format': conn.file_format,
            'status': 'failed',
            'error': None,
            'tested_at': timezone.now().isoformat(),
        }

        try:
            logger.debug(f"Testing file connection: {conn.name}")

            from connections.file_source_paths import resolve_safe_source_path
            from pathlib import Path

            # Resolve and check if file exists
            file_path = resolve_safe_source_path(conn.relative_path)

            if not file_path.exists():
                result['error'] = f"File not found: {conn.relative_path}"
                logger.warning(f"❌ File not found: {conn.name} - {conn.relative_path}")
                return result

            if not file_path.is_file():
                result['error'] = f"Path is not a file: {conn.relative_path}"
                logger.warning(f"❌ Not a file: {conn.name}")
                return result

            # Check if file is readable
            if not file_path.stat().st_size > 0:
                result['error'] = "File is empty"
                logger.warning(f"⚠️ File is empty: {conn.name}")
                # Still mark as passed since file exists

            result['status'] = 'passed'
            logger.info(f"✅ File connection test passed: {conn.name}")

        except Exception as e:
            result['error'] = f"File check failed: {str(e)}"
            logger.error(f"❌ File connection test error: {conn.name} - {e}", exc_info=True)

        return result

    def get_summary_text(self) -> str:
        """Get human-readable summary of health check."""
        if self.total_failed == 0:
            return f"All {self.total_tested} connections are healthy ✅"
        else:
            return f"{self.total_failed} of {self.total_tested} connections failed ❌"


def run_health_check(tenant=None) -> Dict:
    """
    Run health check and return results.

    Usage:
        results = run_health_check()
        print(f"Tested: {results['total_tested']}")
        print(f"Failed: {results['total_failed']}")
    """
    checker = ConnectionHealthCheck()
    return checker.test_all_connections(tenant=tenant)
