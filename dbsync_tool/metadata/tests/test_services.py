"""
Unit tests for metadata services
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from connections.models import DatabaseConnection
from metadata.services import (
    load_schemas,
    load_tables,
    load_table_columns,
    get_table_row_count,
)
from core.exceptions import DatabaseConnectionError


class MetadataServiceTestCase(TestCase):
    """Test cases for metadata service functions"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create a test connection (you'll need a real database for integration tests)
        self.connection = DatabaseConnection.objects.create(
            name='Test PostgreSQL',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test_user',
            password='test_password',
            database_name='test_db',
            created_by=self.user
        )
    
    def test_load_schemas_connection_not_found(self):
        """Test loading schemas with invalid connection ID"""
        with self.assertRaises(ObjectDoesNotExist):
            load_schemas('00000000-0000-0000-0000-000000000000', self.user)
    
    def test_load_schemas_permission_denied(self):
        """Test loading schemas without permission"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
        )
        
        with self.assertRaises(PermissionDenied):
            load_schemas(str(self.connection.id), other_user)
    
    def test_load_schemas_inactive_connection(self):
        """Test loading schemas from inactive connection"""
        self.connection.is_active = False
        self.connection.save()
        
        with self.assertRaises(ObjectDoesNotExist):
            load_schemas(str(self.connection.id), self.user)
    
    def test_load_tables_connection_not_found(self):
        """Test loading tables with invalid connection ID"""
        with self.assertRaises(ObjectDoesNotExist):
            load_tables('00000000-0000-0000-0000-000000000000', 'public', self.user)
    
    def test_load_tables_permission_denied(self):
        """Test loading tables without permission"""
        other_user = User.objects.create_user(
            username='otheruser2',
            email='other2@example.com',
            password='otherpass123'
        )
        
        with self.assertRaises(PermissionDenied):
            load_tables(str(self.connection.id), 'public', other_user)
    
    def test_load_table_columns_connection_not_found(self):
        """Test loading columns with invalid connection ID"""
        with self.assertRaises(ObjectDoesNotExist):
            load_table_columns('00000000-0000-0000-0000-000000000000', 'public', 'test_table', self.user)
    
    def test_load_table_columns_permission_denied(self):
        """Test loading columns without permission"""
        other_user = User.objects.create_user(
            username='otheruser3',
            email='other3@example.com',
            password='otherpass123'
        )
        
        with self.assertRaises(PermissionDenied):
            load_table_columns(str(self.connection.id), 'public', 'test_table', other_user)
    
    # Note: Full integration tests require actual database connections
    # These tests verify permission and validation logic only



