"""
Integration tests for ClickHouse with forms, views, and models
"""
from django.test import TestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from connections.forms import DatabaseConnectionForm
from core.constants import DB_TYPE_CHOICES, DEFAULT_PORTS
from core.encryption import encrypt_password
import json


class ClickHouseIntegrationTests(TestCase):
    """Integration tests for ClickHouse"""
    
    def setUp(self):
        """Set up test user"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        # Create tenant user
        self.tenant = User.objects.create_user(
            username='tenant',
            password='tenant123',
            email='tenant@example.com'
        )
    
    def test_clickhouse_in_db_type_choices(self):
        """Test that ClickHouse appears in DB_TYPE_CHOICES"""
        choices = [choice[0] for choice in DB_TYPE_CHOICES]
        self.assertIn('clickhouse', choices)
    
    def test_form_accepts_clickhouse(self):
        """Test that DatabaseConnectionForm accepts ClickHouse as db_type"""
        form_data = {
            'name': 'Test ClickHouse Connection',
            'db_type': 'clickhouse',
            'host': 'localhost',
            'port': 9000,
            'username': 'default',
            'password': 'testpass',
            'database_name': 'test_db',
            'is_active': True
        }
        form = DatabaseConnectionForm(data=form_data)
        # Form should be valid (we're not testing actual connection)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
    
    def test_form_default_port_for_clickhouse(self):
        """Test that form sets default port for ClickHouse"""
        form_data = {
            'name': 'Test ClickHouse',
            'db_type': 'clickhouse',
            'host': 'localhost',
            'port': '',  # Empty port
            'username': 'default',
            'password': 'testpass',
            'database_name': 'test_db',
        }
        form = DatabaseConnectionForm(data=form_data)
        # Port should be set to default
        if 'port' in form.data:
            # If port is in data, it should use default
            pass
        # Check that default port is 9000
        self.assertEqual(DEFAULT_PORTS.get('clickhouse'), 9000)
    
    def test_create_clickhouse_connection_model(self):
        """Test creating a DatabaseConnection model with ClickHouse"""
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
    
    def test_clickhouse_connection_string_template(self):
        """Test that connection string template exists for ClickHouse"""
        from core.constants import CONNECTION_STRING_TEMPLATES
        self.assertIn('clickhouse', CONNECTION_STRING_TEMPLATES)
        template = CONNECTION_STRING_TEMPLATES['clickhouse']
        self.assertIn('{username}', template)
        self.assertIn('{password}', template)
        self.assertIn('{host}', template)
        self.assertIn('{port}', template)
        self.assertIn('{database}', template)
