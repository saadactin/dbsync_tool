"""
Tests for password encryption/decryption
"""
from django.test import TestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from core.encryption import encrypt_password, decrypt_password, EncryptionService
from core.exceptions import EncryptionError


class EncryptionTestCase(TestCase):
    """Test password encryption and decryption"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.test_password = 'MySecurePassword123!'
    
    def test_encrypt_decrypt_password(self):
        """Test that encryption and decryption work correctly"""
        encrypted = encrypt_password(self.test_password)
        
        # Encrypted string should be different from original
        self.assertNotEqual(encrypted, self.test_password)
        
        # Should be a string
        self.assertIsInstance(encrypted, str)
        
        # Should start with Fernet prefix
        self.assertTrue(encrypted.startswith('gAAAAAB'))
        
        # Decrypt should return original
        decrypted = decrypt_password(encrypted)
        self.assertEqual(decrypted, self.test_password)
    
    def test_encrypt_empty_password(self):
        """Test encrypting empty password returns None"""
        result = encrypt_password('')
        self.assertIsNone(result)
    
    def test_decrypt_empty_password(self):
        """Test decrypting empty password returns None"""
        result = decrypt_password('')
        self.assertIsNone(result)
        result = decrypt_password(None)
        self.assertIsNone(result)
    
    def test_encryption_service_singleton(self):
        """Test that EncryptionService is a singleton"""
        service1 = EncryptionService()
        service2 = EncryptionService()
        self.assertIs(service1, service2)
    
    def test_database_connection_password_encryption(self):
        """Test that DatabaseConnection encrypts password on save"""
        conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password=self.test_password,  # Plain password
            database_name='test_db',
            created_by=self.user
        )
        
        # Password should be encrypted in database
        conn.refresh_from_db()
        self.assertNotEqual(conn.password, self.test_password)
        self.assertTrue(conn.password.startswith('gAAAAAB'))
        
        # get_decrypted_password should return original
        decrypted = conn.get_decrypted_password()
        self.assertEqual(decrypted, self.test_password)
    
    def test_database_connection_password_not_re_encrypted(self):
        """Test that already encrypted password is not re-encrypted"""
        # First encrypt manually
        encrypted = encrypt_password(self.test_password)
        
        conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password=encrypted,  # Already encrypted
            database_name='test_db',
            created_by=self.user
        )
        
        # Password should remain the same (not re-encrypted)
        conn.refresh_from_db()
        self.assertEqual(conn.password, encrypted)
        
        # Should still decrypt correctly
        decrypted = conn.get_decrypted_password()
        self.assertEqual(decrypted, self.test_password)
    
    def test_invalid_encryption_key_raises_error(self):
        """Test that invalid encryption key raises appropriate error"""
        # This test would require changing the encryption key mid-test
        # For now, we just test that decryption of invalid data raises error
        with self.assertRaises(ValueError):
            decrypt_password('invalid_encrypted_data')
    
    def test_connection_update_password(self):
        """Test updating a connection password"""
        conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='old_password',
            database_name='test_db',
            created_by=self.user
        )
        
        # Update password
        new_password = 'new_password_123'
        conn.password = new_password
        conn.save()
        
        # Verify new password
        conn.refresh_from_db()
        decrypted = conn.get_decrypted_password()
        self.assertEqual(decrypted, new_password)

