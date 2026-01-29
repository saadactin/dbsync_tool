"""
API endpoint tests for Freshness Map feature
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from sync_jobs.models import SyncJob, SyncExecution, SyncSchedule, FreshnessMetric
from connections.models import DatabaseConnection


class FreshnessMapAPITestCase(TestCase):
    """Test cases for Freshness Map API endpoint"""
    
    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
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
        
        self.client.force_authenticate(user=self.user)
        
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
    
    def test_freshness_map_endpoint_authenticated(self):
        """Test freshness map API endpoint with authentication"""
        response = self.client.get('/api/jobs/freshness-map/')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.data)
        self.assertIn('summary', response.data)
        
        # Verify summary structure
        summary = response.data['summary']
        self.assertIn('total', summary)
        self.assertIn('fresh', summary)
        self.assertIn('stale', summary)
        self.assertIn('critical', summary)
        self.assertIn('never_run', summary)
    
    def test_freshness_map_endpoint_unauthenticated(self):
        """Test freshness map API endpoint without authentication"""
        self.client.logout()
        response = self.client.get('/api/jobs/freshness-map/')
        
        self.assertEqual(response.status_code, 401)  # Unauthorized
    
    def test_freshness_map_with_jobs(self):
        """Test freshness map endpoint with jobs"""
        # Create jobs
        job1 = SyncJob.objects.create(
            name='Job 1',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        job2 = SyncJob.objects.create(
            name='Job 2',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create execution for job1
        SyncExecution.objects.create(
            job=job1,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=30),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        response = self.client.get('/api/jobs/freshness-map/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['jobs']), 2)
        self.assertEqual(response.data['summary']['total'], 2)
        
        # Verify job data structure
        job_data = response.data['jobs'][0]
        self.assertIn('id', job_data)
        self.assertIn('name', job_data)
        self.assertIn('freshness_status', job_data)
        self.assertIn('freshness_minutes', job_data)
        self.assertIn('expected_freshness_minutes', job_data)
        self.assertIn('last_successful_sync', job_data)
    
    def test_freshness_map_time_period_filter(self):
        """Test freshness map endpoint with time period filter"""
        response = self.client.get('/api/jobs/freshness-map/?time_period=7d')
        self.assertEqual(response.status_code, 200)
        
        response = self.client.get('/api/jobs/freshness-map/?time_period=30d')
        self.assertEqual(response.status_code, 200)
        
        response = self.client.get('/api/jobs/freshness-map/?time_period=all')
        self.assertEqual(response.status_code, 200)
    
    def test_freshness_map_status_filter(self):
        """Test freshness map endpoint with status filter"""
        # Create jobs with different statuses
        job1 = SyncJob.objects.create(
            name='Fresh Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        job2 = SyncJob.objects.create(
            name='Stale Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create schedule for job2
        schedule = SyncSchedule.objects.create(
            job=job2,
            schedule_type='hourly',
            is_enabled=True,
            tenant=self.user
        )
        
        # Create execution for job1 (fresh)
        SyncExecution.objects.create(
            job=job1,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=30),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        # Create execution for job2 (stale)
        SyncExecution.objects.create(
            job=job2,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=95),
            completed_at=timezone.now() - timedelta(minutes=90),
            total_rows_synced=100
        )
        
        # Filter by fresh
        response = self.client.get('/api/jobs/freshness-map/?status=fresh')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['jobs']), 1)
        self.assertEqual(response.data['jobs'][0]['freshness_status'], 'fresh')
        
        # Filter by stale
        response = self.client.get('/api/jobs/freshness-map/?status=stale')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['jobs']), 1)
        self.assertEqual(response.data['jobs'][0]['freshness_status'], 'stale')
        
        # Filter by never_run
        job3 = SyncJob.objects.create(
            name='Never Run Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        response = self.client.get('/api/jobs/freshness-map/?status=never_run')
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data['jobs']), 1)
        never_run_jobs = [j for j in response.data['jobs'] if j['freshness_status'] == 'never_run']
        self.assertGreaterEqual(len(never_run_jobs), 1)
    
    def test_freshness_map_tenant_isolation(self):
        """Test that users only see their own jobs"""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
            email='other@example.com'
        )
        
        from accounts.models import UserProfile
        UserProfile.objects.create(
            user=other_user,
            role='admin'
        )
        
        # Create job for other user
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
            name='Other User Job',
            source_connection=other_conn,
            target_connection=other_conn,
            sync_type='full',
            created_by=other_user,
            tenant=other_user
        )
        
        # Create job for current user
        my_job = SyncJob.objects.create(
            name='My Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Get freshness map for current user
        response = self.client.get('/api/jobs/freshness-map/')
        
        self.assertEqual(response.status_code, 200)
        job_names = [j['name'] for j in response.data['jobs']]
        self.assertIn('My Job', job_names)
        self.assertNotIn('Other User Job', job_names)
