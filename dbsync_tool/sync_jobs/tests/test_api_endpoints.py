"""
API endpoint tests for incremental sync operations
Tests REST API endpoints for incremental sync functionality
"""
import unittest
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import datetime, timedelta
import pytz

from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, SyncCheckpoint
from connections.models import DatabaseConnection


class IncrementalSyncAPITestCase(TestCase):
    """API endpoint tests for incremental sync"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
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
            password='test',
            database_name='test_source',
            created_by=self.user
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_target',
            created_by=self.user
        )
        
        # Create incremental sync job
        self.job = SyncJob.objects.create(
            name='Test Incremental Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=self.job,
            schema_name='public',
            table_name='users',
            incremental_column='updated_at',
            is_enabled=True
        )
    
    def test_run_incremental_sync_job(self):
        """Test POST /sync-jobs/<id>/run/ for incremental sync"""
        response = self.client.post(
            reverse('sync_jobs:job_run_now', args=[self.job.id])
        )
        
        # Should redirect to job detail
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('sync_jobs:job_detail', args=[self.job.id]))
        
        # Verify execution was created (might be async, so check after delay)
        # This is a basic test - actual execution would need to be checked separately
    
    def test_run_incremental_sync_job_already_running(self):
        """Test running incremental sync job when already running"""
        # Create a running execution
        SyncExecution.objects.create(
            job=self.job,
            status='running',
            started_at=timezone.now()
        )
        self.job.status = 'running'
        self.job.save()
        
        response = self.client.post(
            reverse('sync_jobs:job_run_now', args=[self.job.id])
        )
        
        # Should redirect with error message
        self.assertEqual(response.status_code, 302)
    
    def test_run_incremental_sync_job_paused(self):
        """Test running incremental sync job when paused"""
        self.job.status = 'paused'
        self.job.save()
        
        response = self.client.post(
            reverse('sync_jobs:job_run_now', args=[self.job.id])
        )
        
        # Should redirect with error message
        self.assertEqual(response.status_code, 302)
    
    def test_get_executions_for_job(self):
        """Test GET /sync-jobs/<id>/executions/"""
        # Create some executions
        execution1 = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=timezone.now() - timedelta(hours=2),
            completed_at=timezone.now() - timedelta(hours=1),
            total_rows_synced=100
        )
        
        execution2 = SyncExecution.objects.create(
            job=self.job,
            status='failed',
            started_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now() - timedelta(minutes=30),
            error_message='Test error'
        )
        
        # Navigate to job detail page which shows executions
        response = self.client.get(reverse('sync_jobs:job_detail', args=[self.job.id]))
        
        self.assertEqual(response.status_code, 200)
        # Verify executions are displayed
        self.assertContains(response, str(execution1.id)[:8])  # Partial ID
        self.assertContains(response, 'completed')
        self.assertContains(response, 'failed')
    
    def test_get_execution_detail(self):
        """Test GET /sync-jobs/<job_id>/executions/<exec_id>/"""
        execution = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        response = self.client.get(
            reverse('sync_jobs:execution_detail', args=[self.job.id, execution.id])
        )
        
        self.assertEqual(response.status_code, 200)
        # Verify execution details are displayed
        self.assertContains(response, 'completed')
        self.assertContains(response, '100')
    
    def test_get_execution_logs_api(self):
        """Test GET /sync-jobs/<job_id>/executions/<exec_id>/logs/ via status API"""
        execution = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        # Create execution logs
        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name='public',
            table_name='users',
            status='completed',
            rows_fetched=100,
            rows_inserted=100,
            batch_number=1,
            started_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now() - timedelta(minutes=30)
        )
        
        response = self.client.get(
            reverse('sync_jobs:execution_status_api', args=[self.job.id, execution.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('logs', data)
        self.assertEqual(len(data['logs']), 1)
        
        log_data = data['logs'][0]
        self.assertEqual(log_data['schema_name'], 'public')
        self.assertEqual(log_data['table_name'], 'users')
        self.assertEqual(log_data['status'], 'completed')
        self.assertEqual(log_data['rows_fetched'], 100)
        self.assertEqual(log_data['rows_inserted'], 100)
    
    def test_reset_checkpoint_api(self):
        """Test POST /sync-jobs/<id>/checkpoints/reset/<schema>/<table>/"""
        # Create checkpoint
        checkpoint = SyncCheckpoint.objects.create(
            job=self.job,
            schema_name='public',
            table_name='users',
            last_value='2024-01-01 12:00:00',
            updated_at=timezone.now()
        )
        
        # Verify checkpoint exists
        self.assertTrue(SyncCheckpoint.objects.filter(id=checkpoint.id).exists())
        
        # Reset checkpoint
        response = self.client.post(
            reverse('sync_jobs:reset_checkpoint', args=[self.job.id, 'public', 'users'])
        )
        
        # Should redirect
        self.assertEqual(response.status_code, 302)
        
        # Verify checkpoint was deleted
        self.assertFalse(SyncCheckpoint.objects.filter(id=checkpoint.id).exists())
    
    def test_reset_checkpoint_invalid_job(self):
        """Test reset checkpoint with invalid job ID"""
        response = self.client.post(
            reverse('sync_jobs:reset_checkpoint', args=['00000000-0000-0000-0000-000000000000', 'public', 'users'])
        )
        
        # Should redirect with error
        self.assertEqual(response.status_code, 302)
    
    def test_view_checkpoints_api(self):
        """Test GET /sync-jobs/<id>/checkpoints/"""
        # Create checkpoints
        checkpoint1 = SyncCheckpoint.objects.create(
            job=self.job,
            schema_name='public',
            table_name='users',
            last_value='2024-01-01 12:00:00',
            updated_at=timezone.now()
        )
        
        checkpoint2 = SyncCheckpoint.objects.create(
            job=self.job,
            schema_name='public',
            table_name='products',
            last_value='2024-01-01 13:00:00',
            updated_at=timezone.now()
        )
        
        response = self.client.get(reverse('sync_jobs:view_checkpoints', args=[self.job.id]))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('checkpoints', data)
        self.assertEqual(len(data['checkpoints']), 2)
        
        # Verify checkpoint data structure
        checkpoint_data = data['checkpoints'][0]
        self.assertIn('schema_name', checkpoint_data)
        self.assertIn('table_name', checkpoint_data)
        self.assertIn('last_value', checkpoint_data)
        self.assertIn('updated_at', checkpoint_data)
    
    def test_view_checkpoints_empty(self):
        """Test GET /sync-jobs/<id>/checkpoints/ when no checkpoints exist"""
        response = self.client.get(reverse('sync_jobs:view_checkpoints', args=[self.job.id]))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('checkpoints', data)
        self.assertEqual(len(data['checkpoints']), 0)
    
    def test_view_checkpoints_permission_denied(self):
        """Test that users cannot view checkpoints for other users' jobs"""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        
        # Create job owned by other user
        other_job = SyncJob.objects.create(
            name='Other User Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=other_user
        )
        
        # Try to access checkpoints - should fail
        response = self.client.get(reverse('sync_jobs:view_checkpoints', args=[other_job.id]))
        
        # Should return 404 or redirect
        self.assertIn(response.status_code, [302, 404])


if __name__ == '__main__':
    unittest.main()

