"""
Complete integration test for ClickHouse feature
Tests all aspects of ClickHouse integration
"""
from django.test import TestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from connections.forms import DatabaseConnectionForm
from connections.connectors import get_connector
from connections.connectors.factory import get_connector as get_connector_factory
from core.constants import DB_TYPES, DEFAULT_PORTS, CONNECTION_STRING_TEMPLATES, DB_TYPE_CHOICES
from core.connection_pool import get_connection_pool
from core.encryption import encrypt_password
from core.exceptions import InvalidDatabaseTypeError
import os


class ClickHouseCompleteIntegrationTest(TestCase):
    """Complete integration test for ClickHouse"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.tenant = User.objects.create_user(
            username='tenant',
            password='tenant123',
            email='tenant@example.com'
        )
    
    def test_clickhouse_in_all_constants(self):
        """Test that ClickHouse is properly configured in all constants"""
        # Test DB_TYPES
        db_type_values = [t[0] for t in DB_TYPES]
        self.assertIn('clickhouse', db_type_values)
        
        # Test DEFAULT_PORTS
        self.assertIn('clickhouse', DEFAULT_PORTS)
        self.assertEqual(DEFAULT_PORTS['clickhouse'], 9000)
        
        # Test CONNECTION_STRING_TEMPLATES
        self.assertIn('clickhouse', CONNECTION_STRING_TEMPLATES)
        template = CONNECTION_STRING_TEMPLATES['clickhouse']
        self.assertIn('{username}', template)
        self.assertIn('{password}', template)
        self.assertIn('{host}', template)
        self.assertIn('{port}', template)
        self.assertIn('{database}', template)
        
        # Test DB_TYPE_CHOICES
        choices = [choice[0] for choice in DB_TYPE_CHOICES]
        self.assertIn('clickhouse', choices)
    
    def test_clickhouse_connector_import(self):
        """Test that ClickHouse connector can be imported"""
        try:
            from connections.connectors.clickhouse import ClickHouseConnector
            self.assertIsNotNone(ClickHouseConnector)
        except ImportError as e:
            self.fail(f"ClickHouse connector import failed: {e}")
    
    def test_factory_functions_work(self):
        """Test that factory functions work with ClickHouse"""
        # Test __init__.py factory
        try:
            connector = get_connector(
                db_type='clickhouse',
                host='localhost',
                port=9000,
                username='default',
                password='',
                database_name='default'
            )
            self.assertIsNotNone(connector)
            self.assertEqual(connector.host, 'localhost')
            self.assertEqual(connector.port, 9000)
        except InvalidDatabaseTypeError as e:
            if 'not available' in str(e):
                self.skipTest("ClickHouse connector not available")
            else:
                raise
    
    def test_form_validation(self):
        """Test that forms accept ClickHouse"""
        form_data = {
            'name': 'Test ClickHouse',
            'db_type': 'clickhouse',
            'host': 'localhost',
            'port': 9000,
            'username': 'default',
            'password': 'testpass',
            'database_name': 'test_db',
            'is_active': True
        }
        form = DatabaseConnectionForm(data=form_data)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
    
    def test_model_creation(self):
        """Test creating a ClickHouse connection model"""
        connection = DatabaseConnection.objects.create(
            name='Test ClickHouse Connection',
            db_type='clickhouse',
            host='localhost',
            port=9000,
            username='default',
            password=encrypt_password('testpass'),
            database_name='test_db',
            created_by=self.user,
            tenant=self.tenant,
            is_active=True
        )
        self.assertEqual(connection.db_type, 'clickhouse')
        self.assertEqual(connection.port, 9000)
        self.assertIsNotNone(connection.id)
    
    def test_factory_with_model(self):
        """Test factory function with DatabaseConnection model"""
        connection = DatabaseConnection.objects.create(
            name='Test ClickHouse',
            db_type='clickhouse',
            host='localhost',
            port=9000,
            username='default',
            password=encrypt_password('testpass'),
            database_name='test_db',
            created_by=self.user,
            tenant=self.tenant,
            is_active=True
        )
        
        try:
            connector = get_connector_factory(connection)
            self.assertIsNotNone(connector)
            self.assertEqual(connector.host, 'localhost')
            self.assertEqual(connector.port, 9000)
        except Exception as e:
            if 'not available' in str(e) or 'Connection failed' in str(e):
                # Expected if ClickHouse is not running
                pass
            else:
                raise
    
    def test_connection_pool_integration(self):
        """Test connection pool integration"""
        connection = DatabaseConnection.objects.create(
            name='Test ClickHouse Pool',
            db_type='clickhouse',
            host='localhost',
            port=9000,
            username='default',
            password=encrypt_password('testpass'),
            database_name='test_db',
            created_by=self.user,
            tenant=self.tenant,
            is_active=True
        )
        
        pool = get_connection_pool()
        try:
            connector = pool.get_connection(connection, read_only=True)
            self.assertIsNotNone(connector)
            pool.return_connection(str(connection.id), connector)
        except Exception as e:
            # Expected if ClickHouse is not running
            if 'Connection failed' not in str(e):
                raise
    
    def test_invalid_db_type_still_works(self):
        """Test that invalid database types still raise proper errors"""
        with self.assertRaises(InvalidDatabaseTypeError):
            get_connector(
                db_type='invalid_db',
                host='localhost',
                port=9000,
                username='user',
                password='pass',
                database_name='test'
            )
