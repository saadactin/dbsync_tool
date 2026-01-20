"""
Tests for database connectors
"""
from django.test import TestCase
from django.conf import settings
from connections.connectors.postgres import PostgresConnector
from connections.connectors.base import ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError


class PostgresConnectorTests(TestCase):
    """Test cases for PostgreSQL connector"""
    
    def setUp(self):
        """Set up test connector"""
        # Use test database from settings
        self.connector = PostgresConnector(
            host=settings.DATABASES['default']['HOST'],
            port=int(settings.DATABASES['default'].get('PORT', 5432)),
            username=settings.DATABASES['default']['USER'],
            password=settings.DATABASES['default']['PASSWORD'],
            database_name=settings.DATABASES['default']['NAME']
        )
    
    def test_connect(self):
        """Test connection establishment"""
        try:
            conn = self.connector.connect()
            self.assertIsNotNone(conn)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("PostgreSQL not available for testing")
    
    def test_test_connection(self):
        """Test connection test method"""
        try:
            result = self.connector.test_connection()
            self.assertIsInstance(result, bool)
        except Exception:
            self.skipTest("PostgreSQL not available for testing")
    
    def test_get_schemas(self):
        """Test getting schemas"""
        try:
            self.connector.connect()
            schemas = self.connector.get_schemas()
            self.assertIsInstance(schemas, list)
            # Should at least have 'public' schema
            if schemas:
                self.assertIn('public', schemas)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("PostgreSQL not available for testing")
    
    def test_get_tables(self):
        """Test getting tables"""
        try:
            self.connector.connect()
            tables = self.connector.get_tables('public')
            self.assertIsInstance(tables, list)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("PostgreSQL not available for testing")
    
    def test_table_exists(self):
        """Test table existence check"""
        try:
            self.connector.connect()
            # Check for a table that should exist (like django_migrations)
            exists = self.connector.table_exists('public', 'django_migrations')
            self.assertIsInstance(exists, bool)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("PostgreSQL not available for testing")
    
    def test_context_manager(self):
        """Test context manager usage"""
        try:
            with self.connector:
                self.assertIsNotNone(self.connector._connection)
            # Connection should be closed after context
            self.assertIsNone(self.connector._connection)
        except DatabaseConnectionError:
            self.skipTest("PostgreSQL not available for testing")



