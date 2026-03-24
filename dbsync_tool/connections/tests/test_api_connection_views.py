"""
Tests for API Connection Views
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import PermissionDenied
import json

from connections.models import APIConnection
from accounts.models import UserProfile, Role
from core.constants import SAP_DOCUMENT_TYPES


class APIConnectionViewsTests(TestCase):
    """Test cases for API Connection Views"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.client = Client()
        
        # Create users with different roles
        self.super_admin = User.objects.create_user(
            username='superadmin',
            password='testpass123',
            email='superadmin@example.com',
            is_superuser=True,
            is_staff=True
        )
        # Use update_or_create in case a profile is auto-created by signals
        UserProfile.objects.update_or_create(
            user=self.super_admin,
            defaults={'role': Role.SUPER_ADMIN}
        )
        
        self.tenant_admin = User.objects.create_user(
            username='tenantadmin',
            password='testpass123',
            email='tenantadmin@example.com'
        )
        UserProfile.objects.update_or_create(
            user=self.tenant_admin,
            defaults={'role': Role.ADMIN, 'tenant': self.tenant_admin}
        )
        
        self.operator = User.objects.create_user(
            username='operator',
            password='testpass123',
            email='operator@example.com'
        )
        UserProfile.objects.update_or_create(
            user=self.operator,
            defaults={'role': Role.OPERATOR, 'tenant': self.tenant_admin}
        )
        
        self.viewer = User.objects.create_user(
            username='viewer',
            password='testpass123',
            email='viewer@example.com'
        )
        UserProfile.objects.update_or_create(
            user=self.viewer,
            defaults={'role': Role.VIEWER, 'tenant': self.tenant_admin}
        )
        
        # Create test API connection
        self.api_conn = APIConnection.objects.create(
            name='Test API Connection',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            tenant=self.tenant_admin,
            created_by=self.tenant_admin
        )
    
    def test_api_connection_list_view_requires_login(self):
        """Test that list view requires login"""
        response = self.client.get(reverse('connections:api_list'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_api_connection_list_view_authenticated(self):
        """Test list view for authenticated user"""
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'API Connections')
    
    def test_api_connection_list_view_shows_connections(self):
        """Test that list view shows API connections"""
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_list'))
        self.assertContains(response, 'Test API Connection')
    
    def test_api_connection_create_view_requires_login(self):
        """Test that create view requires login"""
        response = self.client.get(reverse('connections:api_create'))
        self.assertEqual(response.status_code, 302)
    
    def test_api_connection_create_view_requires_permission(self):
        """Test that create view requires operator or above permission"""
        self.client.login(username='viewer', password='testpass123')
        response = self.client.get(reverse('connections:api_create'))
        self.assertEqual(response.status_code, 403)  # Forbidden
    
    def test_api_connection_create_view_operator(self):
        """Test that operator can access create view"""
        self.client.login(username='operator', password='testpass123')
        response = self.client.get(reverse('connections:api_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create API Connection')
    
    def test_api_connection_create_post(self):
        """Test creating API connection via POST"""
        self.client.login(username='tenantadmin', password='testpass123')
        
        data = {
            'name': 'New API Connection',
            'api_type': 'zoho_crm',
            'client_id': 'new_client_id',
            'client_secret': 'new_secret',
            'refresh_token': 'new_token',
            'api_domain': 'https://www.zohoapis.in',
            'token_url': 'https://accounts.zoho.in/oauth/v2/token',
            'selected_modules': '[]',
            'is_active': True,
        }
        
        response = self.client.post(reverse('connections:api_create'), data=data)
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Verify connection was created
        self.assertTrue(APIConnection.objects.filter(name='New API Connection').exists())

    def test_api_connection_create_sap_b1_post(self):
        """Test creating SAP B1 API connection via POST with all endpoints."""
        self.client.login(username='tenantadmin', password='testpass123')
        sap_endpoints = SAP_DOCUMENT_TYPES
        data = {
            'name': 'SAP API Connection',
            'api_type': 'sap_b1',
            'sap_base_url': 'https://tservice.kloudqapps.com:8443/b1s/v2/',
            'sap_user_name': 'API',
            'sap_company_db': 'PRODUCTION_31052023',
            'sap_password': 'Admin@123',
            'sap_endpoints': json.dumps(sap_endpoints),
            'is_active': True,
        }
        response = self.client.post(reverse('connections:api_create'), data=data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(APIConnection.objects.filter(name='SAP API Connection', api_type='sap_b1').exists())
    
    def test_api_connection_detail_view(self):
        """Test detail view"""
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_detail', args=[self.api_conn.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test API Connection')
    
    def test_api_connection_update_view(self):
        """Test update view"""
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_update', args=[self.api_conn.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit API Connection')
    
    def test_api_connection_update_post(self):
        """Test updating API connection via POST"""
        self.client.login(username='tenantadmin', password='testpass123')
        
        data = {
            'name': 'Updated Connection',
            'api_type': 'zoho_crm',
            'client_id': 'test_client_id',
            'client_secret': '',  # Empty - keep existing
            'refresh_token': '',  # Empty - keep existing
            'api_domain': 'https://www.zohoapis.in',
            'token_url': 'https://accounts.zoho.in/oauth/v2/token',
            'selected_modules': '[]',
            'is_active': True,
        }
        
        response = self.client.post(reverse('connections:api_update', args=[self.api_conn.id]), data=data)
        self.assertEqual(response.status_code, 302)
        
        # Verify connection was updated
        self.api_conn.refresh_from_db()
        self.assertEqual(self.api_conn.name, 'Updated Connection')
    
    def test_api_connection_delete_view(self):
        """Test delete view"""
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_delete', args=[self.api_conn.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete API Connection')
    
    def test_api_connection_delete_post(self):
        """Test deleting API connection via POST"""
        self.client.login(username='tenantadmin', password='testpass123')
        
        conn_id = self.api_conn.id
        response = self.client.post(reverse('connections:api_delete', args=[conn_id]))
        self.assertEqual(response.status_code, 302)
        
        # Verify connection was deleted
        self.assertFalse(APIConnection.objects.filter(id=conn_id).exists())
    
    def test_api_connection_test_view_new_connection(self):
        """Test test connection view for new connection"""
        self.client.login(username='tenantadmin', password='testpass123')
        
        data = {
            'name': 'Test Connection',
            'api_type': 'zoho_crm',
            'client_id': 'test_client_id',
            'client_secret': 'test_secret',
            'refresh_token': 'test_token',
            'api_domain': 'https://www.zohoapis.in',
            'token_url': 'https://accounts.zoho.in/oauth/v2/token',
        }
        
        response = self.client.post(
            reverse('connections:api_test_new'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertIn('success', result)
    
    def test_api_connection_test_view_existing_connection(self):
        """Test test connection view for existing connection"""
        self.client.login(username='tenantadmin', password='testpass123')
        
        response = self.client.post(
            reverse('connections:api_test', args=[self.api_conn.id]),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertIn('success', result)
    
    def test_api_connection_modules_view(self):
        """Test modules view"""
        self.client.login(username='tenantadmin', password='testpass123')
        
        response = self.client.get(reverse('connections:api_modules', args=[self.api_conn.id]))
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertIn('modules', result)
    
    def test_api_connection_tenant_isolation(self):
        """Test that users can only see their tenant's connections"""
        # Create another tenant
        tenant2 = User.objects.create_user(
            username='tenant2',
            password='testpass123',
            email='tenant2@example.com'
        )
        UserProfile.objects.update_or_create(
            user=tenant2,
            defaults={'role': Role.ADMIN, 'tenant': tenant2}
        )
        
        # Create connection for tenant2
        conn2 = APIConnection.objects.create(
            name='Tenant2 Connection',
            api_type='zoho_crm',
            client_id='test_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            tenant=tenant2,
            created_by=tenant2
        )
        
        # Login as tenant_admin
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_list'))
        
        # Should see own connection
        self.assertContains(response, 'Test API Connection')
        # Should not see tenant2's connection
        self.assertNotContains(response, 'Tenant2 Connection')
    
    def test_api_connection_cross_tenant_update_blocked(self):
        """Test that cross-tenant updates are blocked"""
        # Create another tenant
        tenant2 = User.objects.create_user(
            username='tenant2',
            password='testpass123',
            email='tenant2@example.com'
        )
        UserProfile.objects.update_or_create(
            user=tenant2,
            defaults={'role': Role.ADMIN, 'tenant': tenant2}
        )
        
        # Login as tenant2
        self.client.login(username='tenant2', password='testpass123')
        
        # Try to update tenant_admin's connection
        response = self.client.get(reverse('connections:api_update', args=[self.api_conn.id]))
        # Cross-tenant access should not reveal existence of the object; expect 404
        self.assertEqual(response.status_code, 404)
    
    def test_api_connection_cross_tenant_delete_blocked(self):
        """Test that cross-tenant deletes are blocked"""
        # Create another tenant
        tenant2 = User.objects.create_user(
            username='tenant2',
            password='testpass123',
            email='tenant2@example.com'
        )
        UserProfile.objects.update_or_create(
            user=tenant2,
            defaults={'role': Role.ADMIN, 'tenant': tenant2}
        )
        
        # Login as tenant2
        self.client.login(username='tenant2', password='testpass123')
        
        # Try to delete tenant_admin's connection
        response = self.client.get(reverse('connections:api_delete', args=[self.api_conn.id]))
        # Cross-tenant access should not reveal existence of the object; expect 404
        self.assertEqual(response.status_code, 404)
    
    def test_api_connection_unique_name_per_tenant(self):
        """Test that duplicate names are prevented per tenant"""
        self.client.login(username='tenantadmin', password='testpass123')
        
        data = {
            'name': 'Test API Connection',  # Same name as existing
            'api_type': 'zoho_crm',
            'client_id': 'test_client_id',
            'client_secret': 'test_secret',
            'refresh_token': 'test_token',
            'api_domain': 'https://www.zohoapis.in',
            'token_url': 'https://accounts.zoho.in/oauth/v2/token',
            'selected_modules': '[]',
            'is_active': True,
        }
        
        response = self.client.post(reverse('connections:api_create'), data=data)
        # Should show error about duplicate name
        self.assertContains(response, 'already exists', status_code=200)

    # --- Azure DevOps view tests ---

    def _create_azure_connection(self, name='Azure Conn', modules=None):
        modules = modules or ['ProjA', 'ProjB']
        return APIConnection.objects.create(
            name=name,
            api_type='azure_devops',
            organization='MyOrg',
            azure_tenant_id='tenant-guid-123',
            azure_client_id='client-guid-456',
            azure_client_secret='secret-789',
            selected_modules=modules,
            tenant=self.tenant_admin,
            created_by=self.tenant_admin,
        )

    def test_api_connection_test_view_new_azure_devops(self):
        """Test test connection view for new Azure DevOps connection."""
        self.client.login(username='tenantadmin', password='testpass123')
        data = {
            'name': 'Azure Test Conn',
            'api_type': 'azure_devops',
            'organization': 'MyOrg',
            'azure_tenant_id': 'tenant-guid-123',
            'azure_client_id': 'client-guid-456',
            'azure_client_secret': 'secret-789',
        }
        with self.settings():
            response = self.client.post(
                reverse('connections:api_test_new'),
                data=json.dumps(data),
                content_type='application/json'
            )
        # We only assert shape and status code; connector behavior is unit-tested separately
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertIn('success', result)
        self.assertIn('modules', result)

    def test_api_connection_test_view_new_azure_devops_missing_fields(self):
        """Azure DevOps test view should validate required fields."""
        self.client.login(username='tenantadmin', password='testpass123')
        data = {
            'name': 'Azure Test Conn',
            'api_type': 'azure_devops',
            # Missing organization and others
        }
        response = self.client.post(
            reverse('connections:api_test_new'),
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        result = json.loads(response.content)
        self.assertFalse(result.get('success', True))
        self.assertIn('latency_ms', result)

    def test_api_connection_modules_view_azure_devops(self):
        """Modules view should return selected projects for Azure DevOps."""
        self.client.login(username='tenantadmin', password='testpass123')
        azure_conn = self._create_azure_connection(modules=['ProjA', 'ProjB'])
        response = self.client.get(reverse('connections:api_modules', args=[azure_conn.id]))
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertTrue(result.get('success', True))
        self.assertEqual(result.get('modules'), ['ProjA', 'ProjB'])
        self.assertEqual(result.get('selected'), ['ProjA', 'ProjB'])

    def test_api_connection_list_includes_azure_devops_group(self):
        """API connections list should include Azure DevOps group header when connections exist."""
        conn = self._create_azure_connection()
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_list'))
        self.assertEqual(response.status_code, 200)
        # Group header
        self.assertContains(response, 'Azure DevOps')
        # Connection name under that group
        self.assertContains(response, conn.name)
        # Organization in API Domain column
        self.assertContains(response, conn.organization)
        # Projects count label
        self.assertContains(response, '2 projects')

    def test_create_form_renders_azure_fields(self):
        """Create form should render Azure DevOps-specific fields and containers."""
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_create'))
        self.assertEqual(response.status_code, 200)
        # Azure DevOps section container
        self.assertContains(response, 'id="azure-devops-fields"')
        # Azure-specific inputs
        self.assertContains(response, 'id="id_organization"')
        self.assertContains(response, 'id="id_azure_tenant_id"')
        self.assertContains(response, 'id="id_azure_client_id"')
        self.assertContains(response, 'id="id_azure_client_secret"')
        # Shared module/project selection and JS hook IDs
        self.assertContains(response, 'id="module-selection-section"')
        self.assertContains(response, 'id="module-checkboxes"')
        self.assertContains(response, 'id="id_selected_modules"')
        self.assertContains(response, 'id="test-connection-btn"')
        self.assertContains(response, 'id="test-connection-message"')

    def test_edit_form_prepopulates_azure_fields(self):
        """Edit form should prepopulate Azure DevOps fields."""
        azure_conn = self._create_azure_connection(
            name='Azure Edit Conn',
            modules=['ProjX', 'ProjY'],
        )
        self.client.login(username='tenantadmin', password='testpass123')
        response = self.client.get(reverse('connections:api_update', args=[azure_conn.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Azure Edit Conn')
        self.assertContains(response, azure_conn.organization)
        self.assertContains(response, azure_conn.azure_tenant_id)
        self.assertContains(response, azure_conn.azure_client_id)
