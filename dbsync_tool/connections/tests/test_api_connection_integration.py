"""
Integration tests for APIConnection model with real Zoho credentials
These tests use actual Zoho API credentials to verify end-to-end functionality
"""
import os
from django.test import TestCase
from django.contrib.auth.models import User

from connections.models import APIConnection
from core.exceptions import EncryptionError


class APIConnectionIntegrationTests(TestCase):
    """Integration tests using real Zoho credentials"""
    
    # Real credentials from user (can be overridden with environment variables)
    REAL_CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID', '1000.0L3LLVLEKE9ELW7CE0I0KJ3K4FKBBT')
    REAL_CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET', 'd99c479d4c0db451c653d8c380bf6a4c557a73528c')
    REAL_REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN', '1000.2cbaa36345c6d04b699b0cb6740c21ef.149922195c479d83c84826653ff84ff4')
    REAL_API_DOMAIN = os.environ.get('ZOHO_API_DOMAIN', 'https://www.zohoapis.in')
    
    def setUp(self):
        """Set up test fixtures"""
        self.tenant = User.objects.create_user(
            username='test_tenant',
            password='testpass123',
            email='tenant@example.com'
        )
        self.creator = User.objects.create_user(
            username='test_creator',
            password='testpass123',
            email='creator@example.com'
        )
    
    def test_create_api_connection_with_real_credentials(self):
        """Test creating APIConnection with real Zoho credentials"""
        conn = APIConnection.objects.create(
            name='Real Zoho Connection Test',
            api_type='zoho_crm',
            client_id=self.REAL_CLIENT_ID,
            client_secret=self.REAL_CLIENT_SECRET,
            refresh_token=self.REAL_REFRESH_TOKEN,
            api_domain=self.REAL_API_DOMAIN,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Verify connection was created
        self.assertIsNotNone(conn.id)
        self.assertEqual(conn.name, 'Real Zoho Connection Test')
        self.assertEqual(conn.api_type, 'zoho_crm')
        self.assertEqual(conn.client_id, self.REAL_CLIENT_ID)
        self.assertEqual(conn.api_domain, self.REAL_API_DOMAIN)
        
        # Verify credentials are encrypted
        conn.refresh_from_db()
        self.assertTrue(conn.client_secret.startswith('gAAAAAB'))
        self.assertTrue(conn.refresh_token.startswith('gAAAAAB'))
        
        # Verify decryption works
        decrypted_secret = conn.get_decrypted_client_secret()
        decrypted_token = conn.get_decrypted_refresh_token()
        
        self.assertEqual(decrypted_secret, self.REAL_CLIENT_SECRET)
        self.assertEqual(decrypted_token, self.REAL_REFRESH_TOKEN)
        
        # Verify connection params
        params = conn.get_connection_params()
        self.assertEqual(params['client_id'], self.REAL_CLIENT_ID)
        self.assertEqual(params['client_secret'], self.REAL_CLIENT_SECRET)
        self.assertEqual(params['refresh_token'], self.REAL_REFRESH_TOKEN)
        self.assertEqual(params['api_domain'], self.REAL_API_DOMAIN)
        self.assertIn('token_url', params)
    
    def test_api_connection_encryption_persistence(self):
        """Test that encrypted credentials persist correctly across saves"""
        conn = APIConnection.objects.create(
            name='Encryption Test Connection',
            api_type='zoho_crm',
            client_id=self.REAL_CLIENT_ID,
            client_secret=self.REAL_CLIENT_SECRET,
            refresh_token=self.REAL_REFRESH_TOKEN,
            api_domain=self.REAL_API_DOMAIN,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Get encrypted values
        conn.refresh_from_db()
        encrypted_secret = conn.client_secret
        encrypted_token = conn.refresh_token
        
        # Update name (should not re-encrypt)
        conn.name = 'Updated Name'
        conn.save()
        
        # Verify credentials didn't change
        conn.refresh_from_db()
        self.assertEqual(conn.client_secret, encrypted_secret)
        self.assertEqual(conn.refresh_token, encrypted_token)
        
        # Verify decryption still works
        self.assertEqual(conn.get_decrypted_client_secret(), self.REAL_CLIENT_SECRET)
        self.assertEqual(conn.get_decrypted_refresh_token(), self.REAL_REFRESH_TOKEN)
    
    def test_api_connection_with_selected_modules(self):
        """Test APIConnection with selected modules"""
        modules = ['Leads', 'Contacts', 'Accounts', 'Deals']
        
        conn = APIConnection.objects.create(
            name='Modules Test Connection',
            api_type='zoho_crm',
            client_id=self.REAL_CLIENT_ID,
            client_secret=self.REAL_CLIENT_SECRET,
            refresh_token=self.REAL_REFRESH_TOKEN,
            api_domain=self.REAL_API_DOMAIN,
            selected_modules=modules,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Verify modules are stored
        conn.refresh_from_db()
        self.assertEqual(conn.selected_modules, modules)
        self.assertIsInstance(conn.selected_modules, list)
    
    def test_api_connection_default_token_url(self):
        """Test that default token URL is set correctly"""
        conn = APIConnection.objects.create(
            name='Default Token URL Test',
            api_type='zoho_crm',
            client_id=self.REAL_CLIENT_ID,
            client_secret=self.REAL_CLIENT_SECRET,
            refresh_token=self.REAL_REFRESH_TOKEN,
            api_domain=self.REAL_API_DOMAIN,
            # token_url not provided - should use default
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Verify default token URL is set
        self.assertIsNotNone(conn.token_url)
        self.assertEqual(conn.token_url, 'https://accounts.zoho.in/oauth/v2/token')
    
    def test_api_connection_retrieval(self):
        """Test retrieving APIConnection from database"""
        # Create connection
        conn = APIConnection.objects.create(
            name='Retrieval Test Connection',
            api_type='zoho_crm',
            client_id=self.REAL_CLIENT_ID,
            client_secret=self.REAL_CLIENT_SECRET,
            refresh_token=self.REAL_REFRESH_TOKEN,
            api_domain=self.REAL_API_DOMAIN,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        conn_id = conn.id
        
        # Retrieve from database
        retrieved = APIConnection.objects.get(id=conn_id)
        
        # Verify all fields
        self.assertEqual(retrieved.name, 'Retrieval Test Connection')
        self.assertEqual(retrieved.api_type, 'zoho_crm')
        self.assertEqual(retrieved.client_id, self.REAL_CLIENT_ID)
        
        # Verify decryption works after retrieval
        self.assertEqual(retrieved.get_decrypted_client_secret(), self.REAL_CLIENT_SECRET)
        self.assertEqual(retrieved.get_decrypted_refresh_token(), self.REAL_REFRESH_TOKEN)
    
    def test_api_connection_tenant_filtering(self):
        """Test that connections are properly filtered by tenant"""
        # Create tenant 2
        tenant2 = User.objects.create_user(
            username='tenant2',
            password='testpass123',
            email='tenant2@example.com'
        )
        
        # Create connections for different tenants
        conn1 = APIConnection.objects.create(
            name='Same Name',
            api_type='zoho_crm',
            client_id=self.REAL_CLIENT_ID,
            client_secret=self.REAL_CLIENT_SECRET,
            refresh_token=self.REAL_REFRESH_TOKEN,
            api_domain=self.REAL_API_DOMAIN,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        conn2 = APIConnection.objects.create(
            name='Same Name',  # Same name, different tenant
            api_type='zoho_crm',
            client_id=self.REAL_CLIENT_ID,
            client_secret=self.REAL_CLIENT_SECRET,
            refresh_token=self.REAL_REFRESH_TOKEN,
            api_domain=self.REAL_API_DOMAIN,
            tenant=tenant2,
            created_by=self.creator
        )
        
        # Verify both exist
        self.assertIsNotNone(conn1.id)
        self.assertIsNotNone(conn2.id)
        
        # Verify tenant filtering
        tenant1_connections = APIConnection.objects.filter(tenant=self.tenant)
        tenant2_connections = APIConnection.objects.filter(tenant=tenant2)
        
        self.assertEqual(tenant1_connections.count(), 1)
        self.assertEqual(tenant2_connections.count(), 1)
        self.assertIn(conn1, tenant1_connections)
        self.assertIn(conn2, tenant2_connections)
