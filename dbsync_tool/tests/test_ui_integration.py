"""
End-to-end UI integration tests
Tests complete workflows across multiple features
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from accounts.models import UserProfile, Role
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob
from accounts.tests.test_ui_user_management import UserManagementUITestCase


class EndToEndUITests(UserManagementUITestCase):
    """
    End-to-end UI integration tests
    Tests complete workflows
    """
    
    def test_super_admin_creates_admin_workflow(self):
        """Test complete workflow: Super Admin creates Admin, Admin creates Operator"""
        # Super Admin creates Admin
        self.login_as(self.super_admin)
        response = self.create_user_via_ui(
            creator=self.super_admin,
            username='new_admin',
            email='new_admin@example.com',
            password='NewAdmin123!',
            role=Role.ADMIN,
            is_active=True,
            is_staff=True
        )
        self.assertEqual(response.status_code, 302)
        
        new_admin = User.objects.get(username='new_admin')
        self.assertEqual(new_admin.userprofile.role, Role.ADMIN)
        self.assertEqual(new_admin.userprofile.tenant, new_admin)
        
        # New Admin creates Operator
        self.client.logout()
        self.login_as(new_admin)
        response = self.create_user_via_ui(
            creator=new_admin,
            username='new_operator',
            email='new_operator@example.com',
            password='NewOperator123!',
            role=Role.OPERATOR,
            is_active=True,
            is_staff=False
        )
        self.assertEqual(response.status_code, 302)
        
        new_operator = User.objects.get(username='new_operator')
        self.assertEqual(new_operator.userprofile.role, Role.OPERATOR)
        self.assertEqual(new_operator.userprofile.tenant, new_admin)
        
        # New Operator creates connection
        self.client.logout()
        self.login_as(new_operator)
        response = self.client.post(reverse('connections:create'), {
            'name': 'New Operator Connection',
            'db_type': 'postgres',
            'host': 'localhost',
            'port': 5432,
            'username': 'test',
            'password': 'test',
            'database_name': 'test',
            'is_active': True
        })
        self.assertEqual(response.status_code, 302)
        
        new_conn = DatabaseConnection.objects.get(name='New Operator Connection')
        self.assertEqual(new_conn.tenant, new_admin)  # Should belong to Admin, not Operator
        self.assertEqual(new_conn.created_by, new_operator)
    
    def test_tenant_isolation_workflow(self):
        """Test complete tenant isolation workflow"""
        # Admin A creates connection
        self.login_as(self.admin_a)
        response = self.client.post(reverse('connections:create'), {
            'name': 'Admin A Private Connection',
            'db_type': 'mysql',
            'host': 'localhost',
            'port': 3306,
            'username': 'test',
            'password': 'test',
            'database_name': 'test',
            'is_active': True
        })
        self.assertEqual(response.status_code, 302)
        
        # Admin B should NOT see Admin A's connection
        self.client.logout()
        self.login_as(self.admin_b)
        response = self.client.get(reverse('connections:list'))
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        self.assertNotIn('Admin A Private Connection', connection_names)
        
        # Super Admin should see both
        self.client.logout()
        self.login_as(self.super_admin)
        response = self.client.get(reverse('connections:list'))
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        self.assertIn('Admin A Private Connection', connection_names)


