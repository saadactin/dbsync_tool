"""
API endpoint tests for Health Score feature
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from sync_jobs.models import SyncJob, SyncExecution, HealthScoreSnapshot
from connections.models import DatabaseConnection


class HealthScoreAPITestCase(TestCase):
    """Test cases for Health Score API endpoint"""
    
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
    
    def test_health_score_endpoint_authenticated(self):
        """Test health score API endpoint with authentication"""
        response = self.client.get('/api/jobs/health-score/')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('score', response.data)
        self.assertIn('components', response.data)
        self.assertIn('trend', response.data)
        self.assertIn('trend_data', response.data)
        self.assertIn('calculated_at', response.data)
        
        # Verify score is in valid range
        self.assertGreaterEqual(response.data['score'], 0)
        self.assertLessEqual(response.data['score'], 100)
        
        # Verify components
        components = response.data['components']
        self.assertIn('success_rate', components)
        self.assertIn('connection_health', components)
        self.assertIn('schedule_adherence', components)
        self.assertIn('error_frequency', components)
        
        # Verify trend direction
        self.assertIn(response.data['trend'], ['improving', 'degrading', 'stable'])
    
    def test_health_score_endpoint_unauthenticated(self):
        """Test health score API endpoint without authentication"""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/jobs/health-score/')
        
        # Should return 401 or 403
        self.assertIn(response.status_code, [401, 403])
    
    def test_health_score_with_jobs(self):
        """Test health score calculation with jobs"""
        # Create a job
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        response = self.client.get('/api/jobs/health-score/')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('score', response.data)
        self.assertIsInstance(response.data['score'], int)
    
    def test_health_score_with_executions(self):
        """Test health score with execution history"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create successful execution
        SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(days=1),
            completed_at=timezone.now() - timedelta(days=1) + timedelta(minutes=5),
            total_rows_synced=100
        )
        
        response = self.client.get('/api/jobs/health-score/')
        
        self.assertEqual(response.status_code, 200)
        # With successful execution, success rate should be 100%
        self.assertEqual(response.data['components']['success_rate'], 100.0)
    
    def test_health_score_trend_data(self):
        """Test health score trend data in response"""
        # Create some historical snapshots
        for i in range(3):
            HealthScoreSnapshot.objects.create(
                tenant=self.user,
                score=80 + i,
                components={
                    'success_rate': 85,
                    'connection_health': 90,
                    'schedule_adherence': 75,
                    'error_frequency': 80
                },
                calculated_at=timezone.now() - timedelta(days=3-i)
            )
        
        response = self.client.get('/api/jobs/health-score/')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('trend_data', response.data)
        self.assertIsInstance(response.data['trend_data'], list)
        
        if len(response.data['trend_data']) > 0:
            self.assertIn('date', response.data['trend_data'][0])
            self.assertIn('score', response.data['trend_data'][0])
