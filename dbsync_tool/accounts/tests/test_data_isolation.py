"""
Test cases for data isolation between users
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse


class DataIsolationTest(TestCase):
    """
    Test cases for data isolation between users
    """
    
    def setUp(self):
        self.client = Client()
        self.user_a = User.objects.create_user(
            username='usera',
            password='pass123'
        )
        self.user_b = User.objects.create_user(
            username='userb',
            password='pass123'
        )
    
    def test_user_cannot_see_other_users_connections(self):
        """
        Test: User A cannot see User B's connections
        Given: User A and User B exist, User B has connections
        When: User A accesses connection list
        Then: Only User A's connections shown
        """
        # Create connection for User B
        from connections.models import DatabaseConnection
        conn_b = DatabaseConnection.objects.create(
            name='User B Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='testpass',  # Will be encrypted automatically
            database_name='test',
            created_by=self.user_b
        )
        
        # Login as User A
        self.client.login(username='usera', password='pass123')
        response = self.client.get(reverse('connections:list'))
        
        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'User B Connection')
    
    def test_user_cannot_see_other_users_jobs(self):
        """
        Test: User A cannot see User B's jobs
        Given: User A and User B exist, User B has jobs
        When: User A accesses job list
        Then: Only User A's jobs shown
        """
        # Create connection and job for User B
        from connections.models import DatabaseConnection
        from sync_jobs.models import SyncJob
        conn_b = DatabaseConnection.objects.create(
            name='Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='testpass',  # Will be encrypted automatically
            database_name='test',
            created_by=self.user_b
        )
        job_b = SyncJob.objects.create(
            name='User B Job',
            source_connection=conn_b,
            target_connection=conn_b,
            sync_type='full',
            status='pending',
            created_by=self.user_b
        )
        
        # Login as User A
        self.client.login(username='usera', password='pass123')
        response = self.client.get(reverse('sync_jobs:list'))
        
        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'User B Job')
    
    def test_user_cannot_access_other_users_connection_detail(self):
        """
        Test: User A cannot access User B's connection detail
        Given: User A and User B exist, User B has connection
        When: User A tries to access User B's connection detail
        Then: 404 Not Found or 403 Forbidden
        """
        from connections.models import DatabaseConnection
        conn_b = DatabaseConnection.objects.create(
            name='User B Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='testpass',  # Will be encrypted automatically
            database_name='test',
            created_by=self.user_b
        )
        
        self.client.login(username='usera', password='pass123')
        response = self.client.get(
            reverse('connections:detail', args=[conn_b.id])
        )
        
        self.assertIn(response.status_code, [403, 404])
    
    def test_user_cannot_access_other_users_job_detail(self):
        """
        Test: User A cannot access User B's job detail
        Given: User A and User B exist, User B has job
        When: User A tries to access User B's job detail
        Then: 404 Not Found or 403 Forbidden
        """
        from connections.models import DatabaseConnection
        from sync_jobs.models import SyncJob
        conn_b = DatabaseConnection.objects.create(
            name='Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='testpass',  # Will be encrypted automatically
            database_name='test',
            created_by=self.user_b
        )
        job_b = SyncJob.objects.create(
            name='User B Job',
            source_connection=conn_b,
            target_connection=conn_b,
            sync_type='full',
            status='pending',
            created_by=self.user_b
        )
        
        self.client.login(username='usera', password='pass123')
        response = self.client.get(
            reverse('sync_jobs:job_detail', args=[job_b.id])
        )
        
        self.assertIn(response.status_code, [403, 404])

