"""
API endpoint tests for Connection Graph feature
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution
from connections.models import DatabaseConnection
from rest_framework import status


class ConnectionGraphAPITestCase(TestCase):
    """Test cases for Connection Graph API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create user profile (required for tenant service)
        from accounts.models import UserProfile
        UserProfile.objects.create(
            user=self.user,
            role='admin'
        )
        
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Create connections
        self.source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='mysql',
            host='localhost',
            port=3306,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
        
        # Create job
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
    
    def test_connection_graph_endpoint_requires_authentication(self):
        """Test that endpoint requires authentication"""
        self.client.logout()
        
        response = self.client.get('/api/jobs/connections/graph/')
        
        # Should return 401 or redirect to login
        self.assertIn(response.status_code, [401, 302, 403])
    
    def test_connection_graph_endpoint_success(self):
        """Test successful graph data retrieval"""
        response = self.client.get('/api/jobs/connections/graph/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('nodes', response.json())
        self.assertIn('edges', response.json())
        
        data = response.json()
        self.assertIsInstance(data['nodes'], list)
        self.assertIsInstance(data['edges'], list)
    
    def test_connection_graph_endpoint_structure(self):
        """Test that response has correct structure"""
        response = self.client.get('/api/jobs/connections/graph/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Check nodes structure
        if len(data['nodes']) > 0:
            node = data['nodes'][0]
            self.assertIn('id', node)
            self.assertIn('name', node)
            self.assertIn('type', node)
            self.assertIn('job_count', node)
            self.assertIn('is_active', node)
        
        # Check edges structure
        if len(data['edges']) > 0:
            edge = data['edges'][0]
            self.assertIn('source', edge)
            self.assertIn('target', edge)
            self.assertIn('jobs', edge)
            self.assertIn('job_count', edge)
            self.assertIn('status', edge)
            self.assertIn('success_rate', edge)
            self.assertIn(edge['status'], ['healthy', 'warning', 'critical'])
    
    def test_connection_graph_endpoint_with_jobs(self):
        """Test graph endpoint with multiple jobs"""
        # Create another job
        job2 = SyncJob.objects.create(
            name='Test Job 2',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create executions for health calculation
        now = timezone.now()
        for job in [self.job, job2]:
            for i in range(5):
                SyncExecution.objects.create(
                    job=job,
                    status='completed',
                    started_at=now - timedelta(hours=5-i),
                    completed_at=now - timedelta(hours=5-i) + timedelta(seconds=10),
                    total_rows_synced=1000
                )
        
        response = self.client.get('/api/jobs/connections/graph/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Should have 2 nodes (source and target)
        self.assertEqual(len(data['nodes']), 2)
        
        # Should have 1 edge (both jobs between same connections)
        self.assertEqual(len(data['edges']), 1)
        
        edge = data['edges'][0]
        self.assertEqual(edge['job_count'], 2)
        self.assertEqual(len(edge['jobs']), 2)
        self.assertEqual(edge['status'], 'healthy')
    
    def test_connection_graph_endpoint_tenant_isolation(self):
        """Test that endpoint respects tenant isolation"""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
            email='other@example.com'
        )
        from accounts.models import UserProfile
        UserProfile.objects.create(user=other_user, role='admin')
        
        # Create connection and job for other user
        other_conn = DatabaseConnection.objects.create(
            name='Other Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=other_user,
            tenant=other_user,
            is_active=True
        )
        
        other_job = SyncJob.objects.create(
            name='Other Job',
            source_connection=other_conn,
            target_connection=other_conn,
            sync_type='full',
            status='completed',
            created_by=other_user,
            tenant=other_user
        )
        
        # Get graph for first user
        response = self.client.get('/api/jobs/connections/graph/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Should not include other user's connections
        node_ids = [node['id'] for node in data['nodes']]
        self.assertNotIn(str(other_conn.id), node_ids)
    
    def test_connection_graph_endpoint_empty_data(self):
        """Test endpoint with no connections/jobs"""
        # Delete all data
        SyncJob.objects.all().delete()
        DatabaseConnection.objects.all().delete()
        
        response = self.client.get('/api/jobs/connections/graph/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertEqual(len(data['nodes']), 0)
        self.assertEqual(len(data['edges']), 0)
