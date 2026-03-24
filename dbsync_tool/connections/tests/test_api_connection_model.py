"""
Unit and integration tests for APIConnection model
"""
from unittest.mock import Mock, patch
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from connections.models import APIConnection
from core.exceptions import EncryptionError
from core.constants import ZOHO_DEFAULT_TOKEN_URLS


class APIConnectionModelTests(TestCase):
    """Test cases for APIConnection model"""

    def setUp(self):
        """Set up test fixtures"""
        self.tenant = User.objects.create_user(
            username='tenant',
            password='testpass123',
            email='tenant@example.com'
        )
        self.creator = User.objects.create_user(
            username='creator',
            password='testpass123',
            email='creator@example.com'
        )
        self.test_client_id = 'test_client_id_123'
        self.test_client_secret = 'test_client_secret_456'
        self.test_refresh_token = 'test_refresh_token_789'
        self.test_api_domain = 'https://www.zohoapis.in'
        self.test_token_url = 'https://accounts.zoho.in/oauth/v2/token'

    def test_api_connection_creation(self):
        """Test creating APIConnection with all required fields"""
        conn = APIConnection.objects.create(
            name='Test Zoho Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        self.assertIsNotNone(conn.id)
        self.assertEqual(conn.name, 'Test Zoho Connection')
        self.assertEqual(conn.api_type, 'zoho_crm')
        self.assertEqual(conn.client_id, self.test_client_id)
        self.assertEqual(conn.api_domain, self.test_api_domain)
        self.assertEqual(conn.token_url, self.test_token_url)
        self.assertEqual(conn.tenant, self.tenant)
        self.assertEqual(conn.created_by, self.creator)
        self.assertTrue(conn.is_active)
        self.assertEqual(conn.selected_modules, [])

    def test_client_secret_encryption(self):
        """Test that client_secret is encrypted on save"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Refresh from database to get encrypted value
        conn.refresh_from_db()
        
        # Password should be encrypted (Fernet encrypted strings start with 'gAAAAAB')
        self.assertTrue(conn.client_secret.startswith('gAAAAAB'))
        self.assertNotEqual(conn.client_secret, self.test_client_secret)

    def test_refresh_token_encryption(self):
        """Test that refresh_token is encrypted on save"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Refresh from database to get encrypted value
        conn.refresh_from_db()
        
        # Refresh token should be encrypted
        self.assertTrue(conn.refresh_token.startswith('gAAAAAB'))
        self.assertNotEqual(conn.refresh_token, self.test_refresh_token)

    def test_get_decrypted_client_secret(self):
        """Test that get_decrypted_client_secret returns original value"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        decrypted = conn.get_decrypted_client_secret()
        self.assertEqual(decrypted, self.test_client_secret)

    def test_get_decrypted_refresh_token(self):
        """Test that get_decrypted_refresh_token returns original value"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        decrypted = conn.get_decrypted_refresh_token()
        self.assertEqual(decrypted, self.test_refresh_token)

    def test_credentials_not_re_encrypted(self):
        """Test that already encrypted credentials are not re-encrypted"""
        from core.encryption import encrypt_password
        
        # Encrypt credentials manually
        encrypted_secret = encrypt_password(self.test_client_secret)
        encrypted_token = encrypt_password(self.test_refresh_token)
        
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=encrypted_secret,  # Already encrypted
            refresh_token=encrypted_token,  # Already encrypted
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Refresh from database
        conn.refresh_from_db()
        
        # Credentials should remain the same (not re-encrypted)
        self.assertEqual(conn.client_secret, encrypted_secret)
        self.assertEqual(conn.refresh_token, encrypted_token)
        
        # Should still decrypt correctly
        self.assertEqual(conn.get_decrypted_client_secret(), self.test_client_secret)
        self.assertEqual(conn.get_decrypted_refresh_token(), self.test_refresh_token)

    def test_get_connection_params(self):
        """Test that get_connection_params returns correct dictionary with decrypted credentials"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        params = conn.get_connection_params()
        
        self.assertIsInstance(params, dict)
        self.assertEqual(params['client_id'], self.test_client_id)
        self.assertEqual(params['client_secret'], self.test_client_secret)  # Decrypted
        self.assertEqual(params['refresh_token'], self.test_refresh_token)  # Decrypted
        self.assertEqual(params['api_domain'], self.test_api_domain)
        self.assertEqual(params['token_url'], self.test_token_url)

    def test_unique_constraint(self):
        """Test that unique constraint prevents duplicate names per tenant"""
        # Create first connection
        APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Try to create another with same name for same tenant
        with self.assertRaises((IntegrityError, ValidationError)):
            APIConnection.objects.create(
                name='Test Connection',  # Same name
                api_type='zoho_crm',
                client_id=self.test_client_id,
                client_secret=self.test_client_secret,
                refresh_token=self.test_refresh_token,
                api_domain=self.test_api_domain,
                token_url=self.test_token_url,
                tenant=self.tenant,  # Same tenant
                created_by=self.creator
            )
        
        # But should allow same name for different tenant
        tenant2 = User.objects.create_user(
            username='tenant2',
            password='testpass123',
            email='tenant2@example.com'
        )
        
        conn2 = APIConnection.objects.create(
            name='Test Connection',  # Same name
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=tenant2,  # Different tenant
            created_by=self.creator
        )
        
        self.assertIsNotNone(conn2.id)

    def test_validation_invalid_api_type(self):
        """Test validation error for invalid api_type"""
        conn = APIConnection(
            name='Test Connection',
            api_type='invalid_type',  # Invalid
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        with self.assertRaises(ValidationError):
            conn.full_clean()

    def test_validation_invalid_api_domain(self):
        """Test validation error for invalid api_domain URL"""
        conn = APIConnection(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain='not-a-valid-url',  # Invalid URL
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        with self.assertRaises(ValidationError):
            conn.full_clean()

    def test_validation_invalid_token_url(self):
        """Test validation error for invalid token_url"""
        conn = APIConnection(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url='not-a-valid-url',  # Invalid URL
            tenant=self.tenant,
            created_by=self.creator
        )
        
        with self.assertRaises(ValidationError):
            conn.full_clean()

    def test_validation_invalid_selected_modules(self):
        """Test validation error for invalid selected_modules type"""
        conn = APIConnection(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            selected_modules='not-a-list',  # Invalid type
            tenant=self.tenant,
            created_by=self.creator
        )
        
        with self.assertRaises(ValidationError):
            conn.full_clean()

    def test_default_api_domain(self):
        """Test that default api_domain is set if not provided"""
        conn = APIConnection(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            # api_domain not provided
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        conn.save()
        
        self.assertEqual(conn.api_domain, 'https://www.zohoapis.in')

    def test_default_token_url(self):
        """Test that default token_url is set based on api_domain if not provided"""
        conn = APIConnection(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain='https://www.zohoapis.com',
            # token_url not provided
            tenant=self.tenant,
            created_by=self.creator
        )
        conn.save()
        
        expected_token_url = ZOHO_DEFAULT_TOKEN_URLS.get('https://www.zohoapis.com')
        self.assertEqual(conn.token_url, expected_token_url)

    def test_selected_modules_json(self):
        """Test that selected_modules is stored and retrieved as JSON list"""
        modules = ['Leads', 'Contacts', 'Accounts']
        
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            selected_modules=modules,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Refresh from database
        conn.refresh_from_db()
        
        # Should be retrieved as list
        self.assertIsInstance(conn.selected_modules, list)
        self.assertEqual(conn.selected_modules, modules)

    def test_model_string_representation(self):
        """Test that __str__ returns expected format"""
        conn = APIConnection.objects.create(
            name='Test Zoho',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        str_repr = str(conn)
        self.assertIn('Test Zoho', str_repr)
        self.assertIn('Zoho CRM', str_repr)

    @patch('connections.connectors.zoho.ZohoConnector')
    def test_test_connection_success(self, mock_zoho_connector_class):
        """Test that test_connection method works with ZohoConnector"""
        # Mock ZohoConnector
        mock_connector = Mock()
        mock_connector.authenticate.return_value = True
        mock_connector.get_available_modules.return_value = ['Leads', 'Contacts', 'Accounts']
        mock_zoho_connector_class.return_value = mock_connector
        
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        success, message, modules = conn.test_connection()
        
        self.assertTrue(success)
        self.assertIn('successful', message.lower())
        self.assertEqual(len(modules), 3)
        self.assertIn('Leads', modules)
    
    @patch('connections.connectors.zoho.ZohoConnector')
    def test_test_connection_auth_failure(self, mock_zoho_connector_class):
        """Test that test_connection handles authentication failure"""
        # Mock ZohoConnector with auth failure
        mock_connector = Mock()
        mock_connector.authenticate.return_value = False
        mock_zoho_connector_class.return_value = mock_connector
        
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        success, message, modules = conn.test_connection()
        
        self.assertFalse(success)
        self.assertIn('authentication', message.lower())
        self.assertEqual(modules, [])
    
    @patch('connections.connectors.zoho.ZohoConnector')
    def test_test_connection_module_fetch_failure(self, mock_zoho_connector_class):
        """Test that test_connection handles module fetch failure"""
        # Mock ZohoConnector with module fetch failure
        mock_connector = Mock()
        mock_connector.authenticate.return_value = True
        mock_connector.get_available_modules.side_effect = Exception("API error")
        mock_zoho_connector_class.return_value = mock_connector
        
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        success, message, modules = conn.test_connection()
        
        self.assertFalse(success)
        self.assertIn('modules', message.lower())
        self.assertEqual(modules, [])
    
    def test_test_connection_unsupported_api_type(self):
        """Test that test_connection handles unsupported API type"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        # Bypass validation: set api_type in DB to unsupported value
        APIConnection.objects.filter(pk=conn.pk).update(api_type='unsupported_type')
        conn.refresh_from_db()
        success, message, modules = conn.test_connection()
        self.assertFalse(success)
        self.assertIn('unsupported', message.lower())
        self.assertEqual(modules, [])

    def test_get_decrypted_client_secret_error_when_not_set(self):
        """Test that get_decrypted_client_secret raises error when not set"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        APIConnection.objects.filter(pk=conn.pk).update(client_secret=None)
        conn.refresh_from_db()
        with self.assertRaises(EncryptionError):
            conn.get_decrypted_client_secret()

    def test_get_decrypted_refresh_token_error_when_not_set(self):
        """Test that get_decrypted_refresh_token raises error when not set"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        APIConnection.objects.filter(pk=conn.pk).update(refresh_token=None)
        conn.refresh_from_db()
        with self.assertRaises(EncryptionError):
            conn.get_decrypted_refresh_token()

    def test_model_relationships(self):
        """Test that model relationships work correctly"""
        conn = APIConnection.objects.create(
            name='Test Connection',
            api_type='zoho_crm',
            client_id=self.test_client_id,
            client_secret=self.test_client_secret,
            refresh_token=self.test_refresh_token,
            api_domain=self.test_api_domain,
            token_url=self.test_token_url,
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Test tenant relationship
        self.assertEqual(conn.tenant, self.tenant)
        self.assertIn(conn, self.tenant.api_connections.all())
        
        # Test created_by relationship
        self.assertEqual(conn.created_by, self.creator)
        self.assertIn(conn, self.creator.created_api_connections.all())
        
        # Test cascade delete
        self.tenant.delete()
        
        # Connection should be deleted
        with self.assertRaises(APIConnection.DoesNotExist):
            APIConnection.objects.get(id=conn.id)

    # --- Azure DevOps tests ---

    def _azure_devops_kwargs(self, **overrides):
        """Base kwargs for creating an Azure DevOps APIConnection."""
        kwargs = {
            'name': 'Test Azure DevOps Connection',
            'api_type': 'azure_devops',
            'organization': 'MyOrg',
            'azure_tenant_id': '0f31460e-8f97-4bf6-9b20-fe837087ad59',
            'azure_client_id': 'eba2caf1-44f3-4aee-b798-b0b8696c18e7',
            'azure_client_secret': 'test-secret-value',
            'selected_modules': ['ProjectA'],
            'tenant': self.tenant,
            'created_by': self.creator,
        }
        kwargs.update(overrides)
        return kwargs

    def test_azure_devops_connection_creation(self):
        """Test creating APIConnection with azure_devops and all required Azure fields."""
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        self.assertIsNotNone(conn.id)
        self.assertEqual(conn.name, 'Test Azure DevOps Connection')
        self.assertEqual(conn.api_type, 'azure_devops')
        self.assertEqual(conn.organization, 'MyOrg')
        self.assertEqual(conn.azure_tenant_id, '0f31460e-8f97-4bf6-9b20-fe837087ad59')
        self.assertEqual(conn.azure_client_id, 'eba2caf1-44f3-4aee-b798-b0b8696c18e7')
        self.assertEqual(conn.selected_modules, ['ProjectA'])
        self.assertEqual(conn.tenant, self.tenant)
        self.assertEqual(conn.created_by, self.creator)

    def test_azure_client_secret_encryption(self):
        """Test that azure_client_secret is encrypted on save."""
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        conn.refresh_from_db()
        self.assertTrue(conn.azure_client_secret.startswith('gAAAAAB'))
        self.assertNotEqual(conn.azure_client_secret, 'test-secret-value')

    def test_get_decrypted_azure_client_secret(self):
        """Test that get_decrypted_azure_client_secret returns original value."""
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        decrypted = conn.get_decrypted_azure_client_secret()
        self.assertEqual(decrypted, 'test-secret-value')

    def test_get_decrypted_azure_client_secret_raises_when_missing(self):
        """Test that get_decrypted_azure_client_secret raises when secret not set."""
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        APIConnection.objects.filter(pk=conn.pk).update(azure_client_secret=None)
        conn.refresh_from_db()
        with self.assertRaises(EncryptionError):
            conn.get_decrypted_azure_client_secret()

    def test_azure_devops_requires_organization(self):
        """Test validation error when organization is missing for azure_devops."""
        conn = APIConnection(**self._azure_devops_kwargs(organization=''))
        with self.assertRaises(ValidationError) as cm:
            conn.full_clean()
        self.assertIn('organization', cm.exception.error_dict)

    def test_azure_devops_requires_azure_tenant_id(self):
        """Test validation error when azure_tenant_id is missing for azure_devops."""
        conn = APIConnection(**self._azure_devops_kwargs(azure_tenant_id=''))
        with self.assertRaises(ValidationError) as cm:
            conn.full_clean()
        self.assertIn('azure_tenant_id', cm.exception.error_dict)

    def test_azure_devops_requires_azure_client_id(self):
        """Test validation error when azure_client_id is missing for azure_devops."""
        conn = APIConnection(**self._azure_devops_kwargs(azure_client_id=''))
        with self.assertRaises(ValidationError) as cm:
            conn.full_clean()
        self.assertIn('azure_client_id', cm.exception.error_dict)

    def test_azure_devops_requires_azure_client_secret(self):
        """Test validation error when azure_client_secret is missing for azure_devops."""
        conn = APIConnection(**self._azure_devops_kwargs(azure_client_secret=''))
        with self.assertRaises(ValidationError) as cm:
            conn.full_clean()
        self.assertIn('azure_client_secret', cm.exception.error_dict)

    def test_azure_devops_valid_with_all_azure_fields(self):
        """Test that full_clean and save succeed with all Azure fields set."""
        conn = APIConnection(**self._azure_devops_kwargs())
        conn.full_clean()
        conn.save()
        self.assertIsNotNone(conn.id)

    def test_azure_devops_get_connection_params(self):
        """Test get_connection_params for azure_devops returns tenant_id, client_id, client_secret, organization."""
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        params = conn.get_connection_params()
        self.assertEqual(params['tenant_id'], '0f31460e-8f97-4bf6-9b20-fe837087ad59')
        self.assertEqual(params['client_id'], 'eba2caf1-44f3-4aee-b798-b0b8696c18e7')
        self.assertEqual(params['client_secret'], 'test-secret-value')
        self.assertEqual(params['organization'], 'MyOrg')

    @patch('connections.connectors.azure_devops.AzureDevOpsConnector')
    def test_azure_devops_test_connection_success(self, mock_connector_class):
        """Test test_connection for azure_devops returns success and project names."""
        mock_connector = Mock()
        mock_connector.authenticate.return_value = True
        mock_connector.get_available_modules.return_value = ['Proj1', 'Proj2']
        mock_connector_class.return_value = mock_connector
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        success, message, projects = conn.test_connection()
        self.assertTrue(success)
        self.assertIn('success', message.lower())
        self.assertEqual(projects, ['Proj1', 'Proj2'])

    @patch('connections.connectors.azure_devops.AzureDevOpsConnector')
    def test_azure_devops_test_connection_auth_failure(self, mock_connector_class):
        """Test test_connection for azure_devops when authenticate returns False."""
        mock_connector = Mock()
        mock_connector.authenticate.return_value = False
        mock_connector_class.return_value = mock_connector
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        success, message, projects = conn.test_connection()
        self.assertFalse(success)
        self.assertIn('auth', message.lower())
        self.assertEqual(projects, [])

    @patch('connections.connectors.azure_devops.AzureDevOpsConnector')
    def test_azure_devops_test_connection_fetch_projects_failure(self, mock_connector_class):
        """Test test_connection when get_available_modules raises."""
        mock_connector = Mock()
        mock_connector.authenticate.return_value = True
        mock_connector.get_available_modules.side_effect = Exception('API error')
        mock_connector_class.return_value = mock_connector
        conn = APIConnection.objects.create(**self._azure_devops_kwargs())
        success, message, projects = conn.test_connection()
        self.assertFalse(success)
        self.assertIn('project', message.lower())
        self.assertEqual(projects, [])

    def test_azure_devops_selected_modules_must_be_list(self):
        """Test that selected_modules must be a list for azure_devops."""
        conn = APIConnection(**self._azure_devops_kwargs(selected_modules='not-a-list'))
        with self.assertRaises(ValidationError) as cm:
            conn.full_clean()
        self.assertIn('selected_modules', cm.exception.error_dict)
