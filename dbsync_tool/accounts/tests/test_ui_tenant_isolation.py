"""
UI tests for tenant isolation verification
Tests that users can only see and access their own tenant's data
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from accounts.models import UserProfile, Role
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob
from accounts.tests.test_ui_user_management import UserManagementUITestCase


class TenantIsolationUITests(UserManagementUITestCase):
    """
    Test Suite: Tenant Isolation UI Tests
    Tests 45-49
    """
    
    def setUp(self):
        """Set up test data with connections and jobs"""
        super().setUp()
        
        # Create sync job for Admin A
        self.job_admin_a = SyncJob.objects.create(
            name='Admin A Job 1',
            source_connection=self.conn_admin_a1,
            target_connection=self.conn_admin_a1,
            sync_type='full',
            status='pending',
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        # Create sync job for Admin B
        self.job_admin_b = SyncJob.objects.create(
            name='Admin B Job 1',
            source_connection=self.conn_admin_b1,
            target_connection=self.conn_admin_b1,
            sync_type='full',
            status='pending',
            created_by=self.admin_b,
            tenant=self.admin_b
        )
    
    def test_45_admin_a_cannot_see_admin_b_users(self):
        """Test 45: Admin A Cannot See Admin B's Users"""
        self.login_as(self.admin_a)
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        
        users = response.context['users']
        usernames = [user.username for user in users]
        
        # Should see Admin A's tenant users
        self.assertIn('admin_a', usernames)
        self.assertIn('operator_a1', usernames)
        self.assertIn('viewer_a1', usernames)
        
        # Should NOT see Admin B's users
        self.assertNotIn('admin_b', usernames)
        self.assertNotIn('operator_b1', usernames)
        self.assertNotIn('viewer_b1', usernames)
    
    def test_46_admin_a_cannot_see_admin_b_connections(self):
        """Test 46: Admin A Cannot See Admin B's Connections"""
        self.login_as(self.admin_a)
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 200)
        
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        
        # Should see Admin A's connections
        self.assertIn('Admin A Connection 1', connection_names)
        
        # Should NOT see Admin B's connections
        self.assertNotIn('Admin B Connection 1', connection_names)
    
    def test_47_admin_a_cannot_see_admin_b_jobs(self):
        """Test 47: Admin A Cannot See Admin B's Jobs"""
        self.login_as(self.admin_a)
        response = self.client.get(reverse('sync_jobs:list'))
        self.assertEqual(response.status_code, 200)
        
        # job_list view returns 'jobs' in context
        jobs = response.context.get('jobs', [])
        if not jobs:
            # If empty, check if it's a list or queryset
            jobs = list(response.context.get('jobs', []))
        
        job_names = [job.name for job in jobs]
        
        # Should see Admin A's jobs
        self.assertIn('Admin A Job 1', job_names)
        
        # Should NOT see Admin B's jobs
        self.assertNotIn('Admin B Job 1', job_names)
    
    def test_48_operator_a1_cannot_see_admin_b_data(self):
        """Test 48: Operator A1 Cannot See Admin B's Data"""
        self.login_as(self.operator_a1)
        
        # Check connections
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 200)
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        self.assertIn('Admin A Connection 1', connection_names)
        self.assertNotIn('Admin B Connection 1', connection_names)
        
        # Check jobs
        response = self.client.get(reverse('sync_jobs:list'))
        self.assertEqual(response.status_code, 200)
        jobs = response.context.get('jobs', [])
        job_names = [job.name for job in jobs]
        self.assertIn('Admin A Job 1', job_names)
        self.assertNotIn('Admin B Job 1', job_names)
    
    def test_49_viewer_a1_cannot_see_admin_b_data(self):
        """Test 49: Viewer A1 Cannot See Admin B's Data"""
        self.login_as(self.viewer_a1)
        
        # Check connections
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 200)
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        self.assertIn('Admin A Connection 1', connection_names)
        self.assertNotIn('Admin B Connection 1', connection_names)
        
        # Check jobs
        response = self.client.get(reverse('sync_jobs:list'))
        self.assertEqual(response.status_code, 200)
        jobs = response.context.get('jobs', [])
        job_names = [job.name for job in jobs]
        self.assertIn('Admin A Job 1', job_names)
        self.assertNotIn('Admin B Job 1', job_names)

