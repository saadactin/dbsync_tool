"""
Tests for database connectors
"""
from django.test import TestCase
from django.conf import settings
from connections.connectors.postgres import PostgresConnector
from connections.connectors.base import ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError, InvalidDatabaseTypeError
from unittest.mock import patch, MagicMock


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


class ConnectorFactoryMongoTests(TestCase):
    def test_get_connector_mongodb_missing_pymongo_raises_invalid_database_type(self):
        from connections.connectors import get_connector

        with patch.dict("sys.modules", {"pymongo": None}):
            with self.assertRaises(InvalidDatabaseTypeError) as ctx:
                get_connector(
                    db_type="mongodb",
                    host="localhost",
                    port=27017,
                    username="u",
                    password="p",
                    database_name=None,
                )
            self.assertIn("Install pymongo", str(ctx.exception))


class MongoDBConnectorAuthSourceTests(TestCase):
    """MongoDB authSource behavior (fixes root@localhost failures when Database field is wrong)."""

    @patch("pymongo.MongoClient")
    def test_connect_defaults_auth_source_admin_when_database_empty(self, mock_client_class):
        from connections.connectors.mongodb import MongoDBConnector

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        c = MongoDBConnector("localhost", 27017, "root", "secret", database_name=None)
        c.connect()

        kwargs = mock_client_class.call_args.kwargs
        self.assertEqual(kwargs.get("authSource"), "admin")
        self.assertEqual(kwargs.get("username"), "root")
        self.assertEqual(kwargs.get("password"), "secret")

    @patch("pymongo.MongoClient")
    def test_connect_uses_database_name_as_auth_source_when_set_for_non_admin_users(self, mock_client_class):
        from connections.connectors.mongodb import MongoDBConnector

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        c = MongoDBConnector("localhost", 27017, "appuser", "secret", database_name="myapp")
        c.connect()

        kwargs = mock_client_class.call_args.kwargs
        self.assertEqual(kwargs.get("authSource"), "myapp")

    @patch("pymongo.MongoClient")
    def test_connect_uses_admin_auth_source_for_root_even_if_database_set(self, mock_client_class):
        from connections.connectors.mongodb import MongoDBConnector

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        c = MongoDBConnector("localhost", 27017, "root", "secret", database_name="saad")
        c.connect()

        kwargs = mock_client_class.call_args.kwargs
        self.assertEqual(kwargs.get("authSource"), "admin")

    @patch("pymongo.MongoClient")
    def test_connect_skips_credentials_when_no_user_or_password(self, mock_client_class):
        from connections.connectors.mongodb import MongoDBConnector

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        c = MongoDBConnector("localhost", 27017, "", "", database_name=None)
        c.connect()

        kwargs = mock_client_class.call_args.kwargs
        self.assertNotIn("authSource", kwargs)
        self.assertNotIn("username", kwargs)
        self.assertNotIn("password", kwargs)

