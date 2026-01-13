"""
End-to-end tests for password reset flow
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connections.models import DatabaseConnection


class PasswordResetFlowTestCase(TestCase):
    """Test the complete password reset flow when decryption fails"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create a connection with corrupted password
        self.conn = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='RESET_REQUIRED',  # Corrupted password marker
            database_name='test_db',
            created_by=self.user
        )
    
    def test_connection_edit_shows_password_required(self):
        """Test that editing connection with RESET_REQUIRED shows password as required"""
        # Ensure password is set to RESET_REQUIRED
        self.conn.refresh_from_db()
        if self.conn.password != 'RESET_REQUIRED':
            DatabaseConnection.objects.filter(id=self.conn.id).update(password='RESET_REQUIRED')
            self.conn.refresh_from_db()
        
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('connections:update', args=[self.conn.id]))
        
        self.assertEqual(response.status_code, 200)
        # Password field should be required when RESET_REQUIRED
        form = response.context['form']
        # Form should require password if it's RESET_REQUIRED
        # The form checks this in __init__, so we verify the form instance
        if self.conn.password == 'RESET_REQUIRED':
            self.assertTrue(
                form.fields['password'].required or 
                'must be set' in form.fields['password'].help_text.lower() or
                'warning' in form.fields['password'].help_text.lower()
            )
    
    def test_connection_cannot_connect_with_reset_required(self):
        """Test that connection with RESET_REQUIRED cannot be used"""
        from core.exceptions import EncryptionError
        from django.db import connection as db_connection
        
        # Directly set password to RESET_REQUIRED in database
        with db_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE database_connections SET password = %s WHERE id = %s",
                ['RESET_REQUIRED', str(self.conn.id)]
            )
        
        # Refresh from DB
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.password, 'RESET_REQUIRED')
        
        with self.assertRaises(EncryptionError) as context:
            self.conn.get_decrypted_password()
        
        error_msg = str(context.exception)
        # Should mention password needs to be set or updated
        self.assertTrue(
            'not set' in error_msg.lower() or 
            'password' in error_msg.lower() or
            'update' in error_msg.lower() or
            'edit' in error_msg.lower()
        )
    
    def test_connection_update_with_new_password(self):
        """Test updating connection with new password"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.post(
            reverse('connections:update', args=[self.conn.id]),
            {
                'name': 'Test Connection',
                'db_type': 'postgres',
                'host': 'localhost',
                'port': '5432',
                'username': 'test',
                'password': 'new_password_123',
                'database_name': 'test_db',
                'is_active': True,
            }
        )
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Verify password was updated
        self.conn.refresh_from_db()
        self.assertNotEqual(self.conn.password, 'RESET_REQUIRED')
        self.assertTrue(self.conn.password.startswith('gAAAAAB'))  # Encrypted
        
        # Should be able to decrypt
        decrypted = self.conn.get_decrypted_password()
        self.assertEqual(decrypted, 'new_password_123')

