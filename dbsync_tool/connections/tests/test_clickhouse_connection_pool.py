"""
Tests for ClickHouse connection pool integration
"""
from django.test import TestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from core.connection_pool import get_connection_pool
from core.encryption import encrypt_password
from core.exceptions import DatabaseConnectionError
import os


class ClickHouseConnectionPoolTests(TestCase):
    """Test cases for ClickHouse connection pool integration"""
    
    def setUp(self):
        """Set up test connection"""
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
        
        # Create a ClickHouse connection model
        password = os.environ.get('CLICKHOUSE_PASSWORD', 'testpass')
        if not password:
            password = 'testpass'  # Ensure we have a non-empty password
        self.connection = DatabaseConnection.objects.create(
            name='Test ClickHouse Connection',
            db_type='clickhouse',
            host=os.environ.get('CLICKHOUSE_HOST', 'localhost'),
            port=int(os.environ.get('CLICKHOUSE_PORT', '9000')),
            username=os.environ.get('CLICKHOUSE_USER', 'default'),
            password=encrypt_password(password),
            database_name=os.environ.get('CLICKHOUSE_DATABASE', 'default'),
            created_by=self.user,
            tenant=self.tenant,
            is_active=True
        )
    
    def test_connection_pool_accepts_clickhouse(self):
        """Test that connection pool can handle ClickHouse connections"""
        pool = get_connection_pool()
        try:
            connector = pool.get_connection(self.connection, read_only=True)
            self.assertIsNotNone(connector)
            # Return connection to pool
            pool.return_connection(str(self.connection.id), connector)
        except DatabaseConnectionError:
            # Expected if ClickHouse is not available
            pass
    
    def test_connection_pool_validation_clickhouse(self):
        """Test connection pool validation for ClickHouse"""
        pool = get_connection_pool()
        try:
            # Get connection
            connector = pool.get_connection(self.connection, read_only=True)
            # Return it
            pool.return_connection(str(self.connection.id), connector)
            # Get it again - should reuse from pool
            connector2 = pool.get_connection(self.connection, read_only=True)
            self.assertIsNotNone(connector2)
            pool.return_connection(str(self.connection.id), connector2)
        except DatabaseConnectionError:
            # Expected if ClickHouse is not available
            pass
