"""
Tests for password decryption in metadata loading
"""
from django.test import TestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from metadata.services import load_schemas
from core.exceptions import EncryptionError, DatabaseConnectionError


class MetadataPasswordDecryptionTestCase(TestCase):
    """Test that metadata loading handles password decryption errors gracefully"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.test_password = 'test_password_123'
    
    def test_load_schemas_with_valid_password(self):
        """Test loading schemas with valid encrypted password"""
        conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password=self.test_password,
            database_name='test_db',
            created_by=self.user
        )
        
        # This will fail at connection level, but decryption should work
        try:
            load_schemas(str(conn.id), self.user)
        except (DatabaseConnectionError, Exception) as e:
            # Connection error is expected, but decryption should not fail
            self.assertNotIn('Failed to decrypt password', str(e))
            self.assertNotIn('EncryptionError', str(e.__class__.__name__))
    
    def test_encryption_error_propagates_correctly(self):
        """Test that encryption errors are properly raised and formatted"""
        from core.exceptions import DatabaseConnectionError
        from django.db import connection as db_connection
        
        # Create connection
        conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password=self.test_password,
            database_name='test_db',
            created_by=self.user
        )
        
        # Corrupt the password in database (direct SQL update)
        with db_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE database_connections SET password = %s WHERE id = %s",
                ['corrupted_encrypted_data', str(conn.id)]
            )
        
        conn.refresh_from_db()
        
        # Should raise DatabaseConnectionError with helpful message
        with self.assertRaises(DatabaseConnectionError) as context:
            load_schemas(str(conn.id), self.user)
        
        error_msg = str(context.exception)
        # Should mention password, decrypt, update, or connection name
        self.assertTrue(
            'password' in error_msg.lower() or 
            'decrypt' in error_msg.lower() or
            'update' in error_msg.lower() or
            'edit' in error_msg.lower() or
            conn.name in error_msg
        )

