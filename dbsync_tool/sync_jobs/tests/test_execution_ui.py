"""
Integration tests for execution UI functionality
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog
import json


class ExecutionUITestCase(TestCase):
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
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
    
    def test_execution_detail_page_loads(self):
        """Test that execution detail page loads with all elements"""
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{self.execution.id}/'
        )
        self.assertEqual(response.status_code, 200)
        
        # Check for key elements
        content = response.content.decode()
        self.assertIn('execution-header', content)
        self.assertIn('stat-card', content)
        self.assertIn('logs-table-body', content)
        self.assertIn('execution_detail.js', content)
    
    def test_execution_status_api_updates(self):
        """Test that execution status API provides real-time updates"""
        # Simulate execution progress
        self.execution.completed_tables = 2
        self.execution.total_rows_synced = 2000
        self.execution.save()
        
        self.log2.status = 'completed'
        self.log2.completed_at = timezone.now()
        self.log2.rows_fetched = 500
        self.log2.rows_inserted = 500
        self.log2.save()
        
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{self.execution.id}/status/'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['execution']['completed_tables'], 2)
        self.assertEqual(data['execution']['total_rows_synced'], 2000)
        self.assertEqual(data['statistics']['completed_logs'], 2)
    
    def test_execution_completion_stops_polling(self):
        """Test that completed executions don't trigger polling"""
        self.execution.status = 'completed'
        self.execution.completed_at = timezone.now()
        self.execution.save()
        
        response = self.client.get(
            f'/sync-jobs/{self.job.id}/executions/{self.execution.id}/'
        )
        self.assertEqual(response.status_code, 200)
        
        # Check that polling script is not included for completed executions
        content = response.content.decode()
        # For completed executions, the script should not initialize polling
        # (the template checks execution.status == 'running')
        if self.execution.status == 'completed':
            # Script tag should not be present for completed executions
            self.assertNotIn('initializeExecutionUpdates', content)


