"""
UI integration tests for incremental sync functionality
Tests UI components, forms, and user interactions
"""
import unittest
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import datetime, timedelta
import pytz

from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, SyncCheckpoint
from connections.models import DatabaseConnection


class IncrementalSyncUITestCase(TestCase):
    """UI integration tests for incremental sync"""
    
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
    
    def test_create_job_step3_incremental_sync_display(self):
        """Test that Step 3 shows incremental column selection for incremental sync"""
        # Navigate to Step 3 (requires session data from Step 1 and Step 2)
        # For this test, we'll check the template directly
        session = self.client.session
        session['job_name'] = 'Test Job'
        session['source_connection_id'] = str(self.source_conn.id)
        session['target_connection_id'] = str(self.target_conn.id)
        session['selected_tables'] = [
            {'schema_name': 'public', 'table_name': 'users'}
        ]
        session.save()
        
        response = self.client.get(reverse('sync_jobs:create_step3'))
        
        self.assertEqual(response.status_code, 200)
        # Verify incremental sync option is present
        self.assertContains(response, 'incremental')
        self.assertContains(response, 'Incremental Sync')
    
    def test_job_detail_checkpoint_display(self):
        """Test that job detail page shows checkpoint section for incremental sync"""
        # Create incremental sync job
        job = SyncJob.objects.create(
            name='Test Incremental Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            incremental_column='updated_at',
            is_enabled=True
        )
        
        # Create checkpoint
        SyncCheckpoint.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            last_value='2024-01-01 12:00:00',
            updated_at=timezone.now()
        )
        
        response = self.client.get(reverse('sync_jobs:job_detail', args=[job.id]))
        
        self.assertEqual(response.status_code, 200)
        # Verify checkpoint section is present
        self.assertContains(response, 'Checkpoints')
        self.assertContains(response, 'public.users')
        self.assertContains(response, '2024-01-01 12:00:00')
        self.assertContains(response, 'Reset')
    
    def test_job_detail_no_checkpoint_display(self):
        """Test that job detail page shows 'No checkpoint' when checkpoint doesn't exist"""
        # Create incremental sync job without checkpoint
        job = SyncJob.objects.create(
            name='Test Incremental Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            incremental_column='updated_at',
            is_enabled=True
        )
        
        response = self.client.get(reverse('sync_jobs:job_detail', args=[job.id]))
        
        self.assertEqual(response.status_code, 200)
        # Verify 'No checkpoint' is displayed
        self.assertContains(response, 'No checkpoint')
    
    def test_reset_checkpoint_view(self):
        """Test reset checkpoint view"""
        # Create incremental sync job with checkpoint
        job = SyncJob.objects.create(
            name='Test Incremental Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        checkpoint = SyncCheckpoint.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            last_value='2024-01-01 12:00:00',
            updated_at=timezone.now()
        )
        
        # Verify checkpoint exists
        self.assertTrue(SyncCheckpoint.objects.filter(id=checkpoint.id).exists())
        
        # Reset checkpoint
        response = self.client.post(
            reverse('sync_jobs:reset_checkpoint', args=[job.id, 'public', 'users'])
        )
        
        # Should redirect to job detail
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('sync_jobs:job_detail', args=[job.id]))
        
        # Verify checkpoint was deleted
        self.assertFalse(SyncCheckpoint.objects.filter(id=checkpoint.id).exists())
    
    def test_reset_checkpoint_nonexistent(self):
        """Test reset checkpoint when checkpoint doesn't exist"""
        job = SyncJob.objects.create(
            name='Test Incremental Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        # Try to reset non-existent checkpoint
        response = self.client.post(
            reverse('sync_jobs:reset_checkpoint', args=[job.id, 'public', 'users'])
        )
        
        # Should still redirect (with warning message)
        self.assertEqual(response.status_code, 302)
    
    def test_view_checkpoints_api(self):
        """Test view checkpoints API endpoint"""
        # Create incremental sync job with checkpoints
        job = SyncJob.objects.create(
            name='Test Incremental Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        checkpoint1 = SyncCheckpoint.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            last_value='2024-01-01 12:00:00',
            updated_at=timezone.now()
        )
        
        checkpoint2 = SyncCheckpoint.objects.create(
            job=job,
            schema_name='public',
            table_name='products',
            last_value='2024-01-01 13:00:00',
            updated_at=timezone.now()
        )
        
        response = self.client.get(reverse('sync_jobs:view_checkpoints', args=[job.id]))
        
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
        """Test view checkpoints API when no checkpoints exist"""
        job = SyncJob.objects.create(
            name='Test Incremental Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        response = self.client.get(reverse('sync_jobs:view_checkpoints', args=[job.id]))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('checkpoints', data)
        self.assertEqual(len(data['checkpoints']), 0)
    
    def test_view_checkpoints_permission(self):
        """Test that users can only view checkpoints for their own jobs"""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        
        # Create job owned by other user
        job = SyncJob.objects.create(
            name='Other User Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=other_user
        )
        
        # Try to access checkpoints - should fail or return empty
        response = self.client.get(reverse('sync_jobs:view_checkpoints', args=[job.id]))
        
        # Should either redirect or return 404
        self.assertIn(response.status_code, [302, 404])


if __name__ == '__main__':
    unittest.main()

