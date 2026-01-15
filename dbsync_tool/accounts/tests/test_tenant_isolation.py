"""
Integration tests for tenant isolation
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob
from accounts.models import UserProfile, Role
from accounts.services.tenant_service import TenantService


class TenantIsolationTest(TestCase):
    """Test tenant isolation across different roles"""
    
    def setUp(self):
        """Set up test data with multiple admins and data"""
        self.client = Client()
        
        # Create Super Admin
        self.super_admin = User.objects.create_user(
            username='superadmin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        UserProfile.objects.create(
            user=self.super_admin,
            role=Role.SUPER_ADMIN,
            tenant=None
        )
        
        # Create Admin A
        self.admin_a = User.objects.create_user(
            username='admin_a',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=self.admin_a,
            role=Role.ADMIN,
            tenant=self.admin_a
        )
        
        # Create Admin B
        self.admin_b = User.objects.create_user(
            username='admin_b',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=self.admin_b,
            role=Role.ADMIN,
            tenant=self.admin_b
        )
        
        # Create Operator for Admin A
        self.operator_a = User.objects.create_user(
            username='operator_a',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.operator_a,
            role=Role.OPERATOR,
            tenant=self.admin_a
        )
        
        # Create connections
        self.conn_a = DatabaseConnection.objects.create(
            name='Admin A Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='db_a',
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        self.conn_b = DatabaseConnection.objects.create(
            name='Admin B Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='db_b',
            created_by=self.admin_b,
            tenant=self.admin_b
        )
        
        # Create operator connection
        self.conn_operator = DatabaseConnection.objects.create(
            name='Operator Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='db_operator',
            created_by=self.operator_a,
            tenant=self.admin_a
        )
    
    def test_admin_a_connection_not_visible_to_admin_b(self):
        """Test that Admin A's connection is not visible to Admin B"""
        self.client.login(username='admin_b', password='testpass123')
        response = self.client.get(reverse('connections:list'))
        
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        
        self.assertNotIn('Admin A Connection', connection_names)
        self.assertIn('Admin B Connection', connection_names)
    
    def test_operator_connection_visible_to_admin_only(self):
        """Test that Operator's connection is visible to their Admin"""
        # Admin A should see operator's connection
        self.client.login(username='admin_a', password='testpass123')
        response = self.client.get(reverse('connections:list'))
        
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        
        self.assertIn('Operator Connection', connection_names)
        self.assertIn('Admin A Connection', connection_names)
        
        # Admin B should not see operator's connection
        self.client.login(username='admin_b', password='testpass123')
        response = self.client.get(reverse('connections:list'))
        
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        
        self.assertNotIn('Operator Connection', connection_names)
    
    def test_super_admin_sees_all_connections(self):
        """Test that Super Admin sees all connections"""
        self.client.login(username='superadmin', password='testpass123')
        response = self.client.get(reverse('connections:list'))
        
        connections = response.context['connections']
        connection_names = [conn.name for conn in connections]
        
        self.assertIn('Admin A Connection', connection_names)
        self.assertIn('Admin B Connection', connection_names)
        self.assertIn('Operator Connection', connection_names)
    
    def test_cross_tenant_update_blocked(self):
        """Test that cross-tenant update is blocked"""
        self.client.login(username='admin_b', password='testpass123')
        
        # Try to update Admin A's connection
        response = self.client.post(
            reverse('connections:update', args=[self.conn_a.id]),
            {
                'name': 'Hacked Connection',
                'db_type': 'postgres',
                'host': 'localhost',
                'port': 5432,
                'username': 'user',
                'password': 'encrypted_pass',
                'database_name': 'db_a',
            }
        )
        
        # Should be blocked (403 or redirect)
        self.assertIn(response.status_code, [403, 302])
        
        # Connection should not be updated
        self.conn_a.refresh_from_db()
        self.assertNotEqual(self.conn_a.name, 'Hacked Connection')
    
    def test_cross_tenant_delete_blocked(self):
        """Test that cross-tenant delete is blocked"""
        self.client.login(username='admin_b', password='testpass123')
        
        # Try to delete Admin A's connection
        response = self.client.post(
            reverse('connections:delete', args=[self.conn_a.id])
        )
        
        # Should be blocked (403 or redirect)
        self.assertIn(response.status_code, [403, 302])
        
        # Connection should still exist
        self.assertTrue(
            DatabaseConnection.objects.filter(id=self.conn_a.id).exists()
        )
    
    def test_admin_a_job_not_visible_to_admin_b(self):
        """Test that Admin A's job is not visible to Admin B"""
        # Create jobs
        job_a = SyncJob.objects.create(
            name='Admin A Job',
            source_connection=self.conn_a,
            target_connection=self.conn_a,
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        job_b = SyncJob.objects.create(
            name='Admin B Job',
            source_connection=self.conn_b,
            target_connection=self.conn_b,
            created_by=self.admin_b,
            tenant=self.admin_b
        )
        
        # Admin B should not see Admin A's job
        self.client.login(username='admin_b', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'))
        
        # Check if job names are in response
        self.assertNotContains(response, 'Admin A Job')
        self.assertContains(response, 'Admin B Job')
    
    def test_operator_job_visible_to_admin_only(self):
        """Test that Operator's job is visible to their Admin"""
        # Create job for operator
        job_operator = SyncJob.objects.create(
            name='Operator Job',
            source_connection=self.conn_operator,
            target_connection=self.conn_operator,
            created_by=self.operator_a,
            tenant=self.admin_a
        )
        
        # Admin A should see operator's job
        self.client.login(username='admin_a', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'))
        
        self.assertContains(response, 'Operator Job')
        
        # Admin B should not see operator's job
        self.client.login(username='admin_b', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'))
        
        self.assertNotContains(response, 'Operator Job')
    
    def test_super_admin_sees_all_jobs(self):
        """Test that Super Admin sees all jobs"""
        # Create jobs
        job_a = SyncJob.objects.create(
            name='Admin A Job',
            source_connection=self.conn_a,
            target_connection=self.conn_a,
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        job_b = SyncJob.objects.create(
            name='Admin B Job',
            source_connection=self.conn_b,
            target_connection=self.conn_b,
            created_by=self.admin_b,
            tenant=self.admin_b
        )
        
        # Super Admin should see all jobs
        self.client.login(username='superadmin', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'))
        
        self.assertContains(response, 'Admin A Job')
        self.assertContains(response, 'Admin B Job')
    
    def test_dashboard_shows_tenant_data_only(self):
        """Test that dashboard shows only tenant data"""
        from sync_jobs.services import DashboardService
        
        # Create jobs for each admin
        job_a = SyncJob.objects.create(
            name='Admin A Job',
            source_connection=self.conn_a,
            target_connection=self.conn_a,
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        job_b = SyncJob.objects.create(
            name='Admin B Job',
            source_connection=self.conn_b,
            target_connection=self.conn_b,
            created_by=self.admin_b,
            tenant=self.admin_b
        )
        
        # Get stats for Admin A
        stats_a = DashboardService.get_user_statistics(self.admin_a)
        
        # Admin A should only see their job
        self.assertEqual(stats_a['jobs']['total'], 1)
        
        # Get stats for Super Admin
        stats_super = DashboardService.get_user_statistics(self.super_admin)
        
        # Super Admin should see all jobs
        self.assertEqual(stats_super['jobs']['total'], 2)
    
    def test_super_admin_dashboard_shows_all_data(self):
        """Test that Super Admin dashboard shows all data"""
        from sync_jobs.services import DashboardService
        
        # Create jobs for each admin
        job_a = SyncJob.objects.create(
            name='Admin A Job',
            source_connection=self.conn_a,
            target_connection=self.conn_a,
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        job_b = SyncJob.objects.create(
            name='Admin B Job',
            source_connection=self.conn_b,
            target_connection=self.conn_b,
            created_by=self.admin_b,
            tenant=self.admin_b
        )
        
        # Get stats for Super Admin
        stats_super = DashboardService.get_user_statistics(self.super_admin)
        
        # Super Admin should see all jobs
        self.assertEqual(stats_super['jobs']['total'], 2)
        self.assertEqual(stats_super['connections']['total'], 3)  # All connections
    
    def test_admin_dashboard_shows_tenant_data(self):
        """Test that Admin dashboard shows tenant data"""
        from sync_jobs.services import DashboardService
        
        # Create jobs for each admin
        job_a = SyncJob.objects.create(
            name='Admin A Job',
            source_connection=self.conn_a,
            target_connection=self.conn_a,
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        job_b = SyncJob.objects.create(
            name='Admin B Job',
            source_connection=self.conn_b,
            target_connection=self.conn_b,
            created_by=self.admin_b,
            tenant=self.admin_b
        )
        
        # Get stats for Admin A
        stats_a = DashboardService.get_user_statistics(self.admin_a)
        
        # Admin A should only see their tenant data
        self.assertEqual(stats_a['jobs']['total'], 1)
        self.assertEqual(stats_a['connections']['total'], 2)  # Admin A + Operator connections

