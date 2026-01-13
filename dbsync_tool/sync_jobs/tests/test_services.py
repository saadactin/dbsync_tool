"""
Tests for sync_jobs services
"""
from django.test import TestCase
from django.contrib.auth.models import User
from sync_jobs.models import SyncJob, SyncExecution
from sync_jobs.services import DashboardService
from connections.models import DatabaseConnection


class DashboardServiceTestCase(TestCase):
    """Test cases for DashboardService"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user
        )
    
    def test_get_user_statistics(self):
        """Test getting user statistics"""
        stats = DashboardService.get_user_statistics(self.user)
        
        self.assertIn('jobs', stats)
        self.assertIn('executions', stats)
        self.assertIn('success_rates', stats)
        self.assertIn('rows_synced', stats)
        self.assertEqual(stats['jobs']['total'], 0)
    
    def test_get_execution_trends(self):
        """Test getting execution trends"""
        trends = DashboardService.get_execution_trends(self.user, days=30)
        self.assertIsInstance(trends, list)
    
    def test_get_top_jobs_by_rows(self):
        """Test getting top jobs by rows"""
        jobs = DashboardService.get_top_jobs_by_rows(self.user, limit=10)
        self.assertIsInstance(jobs, list)
    
    def test_get_recent_activity(self):
        """Test getting recent activity"""
        activity = DashboardService.get_recent_activity(self.user, limit=20)
        self.assertIsInstance(activity, list)

