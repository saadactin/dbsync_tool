"""
Tests for APIConnectionForm
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from connections.forms import APIConnectionForm
from connections.models import APIConnection
from core.constants import ZOHO_API_DOMAINS, ZOHO_DEFAULT_TOKEN_URLS


class APIConnectionFormTests(TestCase):
    """Test cases for APIConnectionForm"""
    
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
        self.test_data = {
            'name': 'Test Zoho Connection',
            'api_type': 'zoho_crm',
            'client_id': 'test_client_id_123',
            'client_secret': 'test_client_secret_456',
            'refresh_token': 'test_refresh_token_789',
            'api_domain': 'https://www.zohoapis.in',
            'token_url': 'https://accounts.zoho.in/oauth/v2/token',
            'is_active': True,
        }
    
    def test_form_valid_data(self):
        """Test form with valid data"""
        form = APIConnectionForm(data=self.test_data)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
    
    def test_form_required_fields(self):
        """Test that required fields are validated"""
        required_fields = ['name', 'api_type', 'client_id', 'client_secret', 
                          'refresh_token', 'api_domain']
        
        for field in required_fields:
            data = self.test_data.copy()
            del data[field]
            form = APIConnectionForm(data=data)
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)
    
    def test_form_name_validation(self):
        """Test name field validation"""
        # Test empty name
        data = self.test_data.copy()
        data['name'] = ''
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        
        # Test name with invalid characters
        data['name'] = 'Test@Connection!'
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        
        # Test valid name
        data['name'] = 'Test Connection'
        form = APIConnectionForm(data=data)
        self.assertTrue(form.is_valid())
    
    def test_form_api_type_validation(self):
        """Test API type field validation"""
        # Test invalid API type
        data = self.test_data.copy()
        data['api_type'] = 'invalid_type'
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        
        # Test valid API type
        data['api_type'] = 'zoho_crm'
        form = APIConnectionForm(data=data)
        self.assertTrue(form.is_valid())
    
    def test_form_api_domain_validation(self):
        """Test API domain field validation"""
        # Test invalid URL
        data = self.test_data.copy()
        data['api_domain'] = 'not-a-valid-url'
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        
        # Test valid domain
        data['api_domain'] = 'https://www.zohoapis.in'
        form = APIConnectionForm(data=data)
        self.assertTrue(form.is_valid())
    
    def test_form_token_url_auto_population(self):
        """Test that token_url is auto-populated from api_domain"""
        data = self.test_data.copy()
        del data['token_url']  # Remove token_url
        data['api_domain'] = 'https://www.zohoapis.com'
        
        form = APIConnectionForm(data=data)
        self.assertTrue(form.is_valid())
        
        # Token URL should be auto-populated
        expected_token_url = ZOHO_DEFAULT_TOKEN_URLS.get('https://www.zohoapis.com')
        self.assertEqual(form.cleaned_data['token_url'], expected_token_url)
    
    def test_form_edit_mode_password_optional(self):
        """Test that password fields are optional in edit mode"""
        # Create existing connection
        conn = APIConnection.objects.create(
            name='Existing Connection',
            api_type='zoho_crm',
            client_id='test_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            tenant=self.tenant,
            created_by=self.creator
        )
        
        # Form in edit mode - password fields optional
        data = {
            'name': 'Updated Connection',
            'api_type': 'zoho_crm',
            'client_id': 'test_id',
            'client_secret': '',  # Empty - should be allowed
            'refresh_token': '',  # Empty - should be allowed
            'api_domain': 'https://www.zohoapis.in',
            'token_url': 'https://accounts.zoho.in/oauth/v2/token',
            'is_active': True,
        }
        
        form = APIConnectionForm(data=data, instance=conn)
        self.assertTrue(form.is_valid())
    
    def test_form_create_mode_password_required(self):
        """Test that password fields are required in create mode"""
        data = self.test_data.copy()
        data['client_secret'] = ''  # Empty
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('client_secret', form.errors)
        
        data = self.test_data.copy()
        data['refresh_token'] = ''  # Empty
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('refresh_token', form.errors)
    
    def test_form_selected_modules_validation(self):
        """Test selected_modules field validation"""
        data = self.test_data.copy()
        data['selected_modules'] = ['Leads', 'Contacts']
        form = APIConnectionForm(data=data)
        self.assertTrue(form.is_valid())
        
        # Test that it accepts list
        self.assertIsInstance(form.cleaned_data['selected_modules'], list)
    
    def test_form_save_encrypts_credentials(self):
        """Test that form.save() encrypts credentials"""
        form = APIConnectionForm(data=self.test_data)
        self.assertTrue(form.is_valid())
        
        instance = form.save(commit=False)
        instance.tenant = self.tenant
        instance.created_by = self.creator
        instance.save()
        
        # Refresh from database
        instance.refresh_from_db()
        
        # Credentials should be encrypted
        self.assertTrue(instance.client_secret.startswith('gAAAAAB'))
        self.assertTrue(instance.refresh_token.startswith('gAAAAAB'))
    
    def test_form_api_domain_choices(self):
        """Test that API domain field has correct choices"""
        form = APIConnectionForm()
        
        # Get choices from field
        choices = form.fields['api_domain'].choices
        
        # Should include all Zoho domains
        domain_values = [choice[0] for choice in choices if choice[0]]
        for domain in ZOHO_API_DOMAINS.values():
            self.assertIn(domain, domain_values)

    # --- Azure DevOps form tests ---

    def _azure_form_data(self, **overrides):
        data = {
            'name': 'Azure DevOps Conn',
            'api_type': 'azure_devops',
            'organization': 'MyOrg',
            'azure_tenant_id': 'tenant-guid-123',
            'azure_client_id': 'client-guid-456',
            'azure_client_secret': 'secret-789',
            'selected_modules': ['ProjA', 'ProjB'],
            'is_active': True,
        }
        data.update(overrides)
        return data

    def test_azure_devops_form_valid_data(self):
        """Azure DevOps form with valid data should be valid."""
        form = APIConnectionForm(data=self._azure_form_data())
        self.assertTrue(form.is_valid(), f"Azure form errors: {form.errors}")

    def test_azure_devops_form_requires_organization(self):
        data = self._azure_form_data(organization='')
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('organization', form.errors)

    def test_azure_devops_form_requires_azure_tenant_id(self):
        data = self._azure_form_data(azure_tenant_id='')
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('azure_tenant_id', form.errors)

    def test_azure_devops_form_requires_azure_client_id(self):
        data = self._azure_form_data(azure_client_id='')
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('azure_client_id', form.errors)

    def test_azure_devops_form_requires_azure_client_secret_on_create(self):
        data = self._azure_form_data(azure_client_secret='')
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('azure_client_secret', form.errors)

    def test_azure_devops_form_requires_at_least_one_project(self):
        data = self._azure_form_data(selected_modules=[])
        form = APIConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('selected_modules', form.errors)

    def test_azure_devops_form_save_sets_azure_fields(self):
        """Saving Azure DevOps form maps fields and encrypts secret."""
        form = APIConnectionForm(data=self._azure_form_data())
        self.assertTrue(form.is_valid(), f"Azure form errors: {form.errors}")
        instance = form.save(commit=False)
        instance.tenant = self.tenant
        instance.created_by = self.creator
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.organization, 'MyOrg')
        self.assertEqual(instance.azure_tenant_id, 'tenant-guid-123')
        self.assertEqual(instance.azure_client_id, 'client-guid-456')
        self.assertEqual(instance.selected_modules, ['ProjA', 'ProjB'])
        self.assertTrue(instance.azure_client_secret.startswith('gAAAAAB'))

    def test_azure_devops_form_edit_keeps_secret_when_blank(self):
        """On edit, leaving azure_client_secret blank should keep existing secret."""
        # create existing Azure connection through model
        conn = APIConnection.objects.create(
            name='Existing Azure',
            api_type='azure_devops',
            organization='MyOrg',
            azure_tenant_id='tenant-guid-123',
            azure_client_id='client-guid-456',
            azure_client_secret='secret-789',
            selected_modules=['ProjA'],
            tenant=self.tenant,
            created_by=self.creator,
        )
        original_secret = conn.azure_client_secret
        data = {
            'name': 'Existing Azure',
            'api_type': 'azure_devops',
            'organization': 'MyOrg',
            'azure_tenant_id': 'tenant-guid-123',
            'azure_client_id': 'client-guid-456',
            'azure_client_secret': '',
            'selected_modules': ['ProjA'],
            'is_active': True,
        }
        form = APIConnectionForm(data=data, instance=conn)
        self.assertTrue(form.is_valid(), f"Azure edit form errors: {form.errors}")
        saved = form.save()
        saved.refresh_from_db()
        self.assertEqual(saved.azure_client_secret, original_secret)
