"""
Unit tests for execution views
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog
import uuid


class ExecutionViewsTestCase(TestCase):
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass123')
        
        # Create test connections
        self.source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='encrypted_password',
            database_name='test_db',
            created_by=self.user
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='encrypted_password',
            database_name='test_db',
            created_by=self.user
        )
        
        # Create test job
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        # Create test execution
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status='running',
            started_at=timezone.now(),
            total_tables=3,
            completed_tables=1,
            total_rows_synced=1000
        )
        
        # Create test logs
        self.log1 = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name='public',
            table_name='table1',
            status='completed',
            started_at=timezone.now(),
            completed_at=timezone.now(),
            rows_fetched=500,
            rows_inserted=500,
            batch_number=1
        )
        
        self.log2 = SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name='public',
            table_name='table2',
            status='running',
            started_at=timezone.now(),
            rows_fetched=300,
            rows_inserted=300,
            batch_number=1
        )
    
    def test_execution_detail_view_success(self):
        """Test execution detail view loads successfully"""
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{self.execution.id}/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Execution Details')
        self.assertContains(response, self.job.name)
        self.assertContains(response, 'table1')
        self.assertContains(response, 'table2')
    
    def test_execution_detail_view_not_found(self):
        """Test execution detail view with invalid execution ID"""
        fake_id = uuid.uuid4()
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{fake_id}/'
        )
        self.assertEqual(response.status_code, 302)  # Redirect to job detail
        self.assertRedirects(response, f'/sync-jobs/{self.job.id}/')
    
    def test_execution_detail_view_unauthorized(self):
        """Test execution detail view with unauthorized user"""
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )
        self.client.logout()
        self.client.login(username='otheruser', password='testpass123')
        
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{self.execution.id}/'
        )
        self.assertEqual(response.status_code, 302)  # Redirect
    
    def test_execution_status_api_success(self):
        """Test execution status API returns correct data"""
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{self.execution.id}/status/'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertIn('execution', data)
        self.assertIn('logs', data)
        self.assertIn('statistics', data)
        self.assertEqual(data['execution']['status'], 'running')
        self.assertEqual(len(data['logs']), 2)
        self.assertEqual(data['statistics']['completed_logs'], 1)
        self.assertEqual(data['statistics']['running_logs'], 1)
    
    def test_execution_status_api_not_found(self):
        """Test execution status API with invalid execution ID"""
        fake_id = uuid.uuid4()
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{fake_id}/status/'
        )
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn('error', data)
    
    def test_job_detail_view_with_executions(self):
        """Test job detail view includes execution history"""
        response = self.client.get(f'/sync-jobs/{self.job.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Execution History')
        self.assertContains(response, str(self.execution.id))
    
    def test_execution_detail_duration_calculation(self):
        """Test duration calculation in execution detail"""
        # Complete the execution
        self.execution.status = 'completed'
        self.execution.completed_at = timezone.now()
        self.execution.save()
        
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{self.execution.id}/'
        )
        self.assertEqual(response.status_code, 200)
        # Duration should be calculated and displayed
        self.assertIn('Duration', response.content.decode())


