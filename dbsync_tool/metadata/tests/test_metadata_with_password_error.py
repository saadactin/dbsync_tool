"""
End-to-end tests for metadata loading with password decryption errors
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connections.models import DatabaseConnection
from metadata.services import load_all_metadata
from core.exceptions import DatabaseConnectionError


class MetadataPasswordErrorTestCase(TestCase):
    """Test metadata loading when password decryption fails"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_load_all_metadata_with_reset_required_password(self):
        """Test that load_all_metadata raises helpful error when password needs reset"""
        from django.db import connection as db_connection
        
        # Create connection
        conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test_pass',  # Will be encrypted
            database_name='test_db',
            created_by=self.user
        )
        
        # Set password to RESET_REQUIRED
        with db_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE database_connections SET password = %s WHERE id = %s",
                ['RESET_REQUIRED', str(conn.id)]
            )
        
        # Should raise DatabaseConnectionError with helpful message
        with self.assertRaises(DatabaseConnectionError) as context:
            load_all_metadata(str(conn.id), self.user)
        
        error_msg = str(context.exception)
        self.assertIn('password', error_msg.lower())
        self.assertIn('update', error_msg.lower() or 'edit' in error_msg.lower())
        self.assertIn(conn.name, error_msg)
    
    def test_api_view_returns_helpful_error_for_reset_required(self):
        """Test that API view returns helpful error when password needs reset"""
        from django.db import connection as db_connection
        
        # Create connection
        conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test_pass',
            database_name='test_db',
            created_by=self.user
        )
        
        # Set password to RESET_REQUIRED
        with db_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE database_connections SET password = %s WHERE id = %s",
                ['RESET_REQUIRED', str(conn.id)]
            )
        
        # Login and call API
        self.client.login(username='testuser', password='testpass123')
        url = reverse('metadata:all_metadata', args=[conn.id])
        response = self.client.get(url)
        
        # Should return error response
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data.get('success', True))
        self.assertIn('password', data.get('error', '').lower())
        self.assertIn('update', data.get('error', '').lower() or 'edit' in data.get('error', '').lower())

