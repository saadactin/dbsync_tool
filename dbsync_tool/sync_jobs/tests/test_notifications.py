"""
Tests for notification service
"""
from django.test import TestCase
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock
from sync_jobs.models import SyncJob, SyncExecution, NotificationPreference
from sync_jobs.notifications import NotificationService
from connections.models import DatabaseConnection


class NotificationServiceTestCase(TestCase):
    """Test cases for NotificationService"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create notification preferences
        NotificationPreference.objects.create(
            user=self.user,
            email_enabled=True,
            notify_on_job_completed=True,
            notify_on_job_failed=True,
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
        
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            total_tables=5,
            completed_tables=5,
            total_rows_synced=1000
        )
    
    @patch('sync_jobs.notifications.send_mail')
    def test_send_job_completed_notification(self, mock_send_mail):
        """Test sending job completed notification"""
        NotificationService.send_job_completed_notification(self.job, self.execution)
        
        # Verify email was sent
        mock_send_mail.assert_called_once()
        self.assertEqual(mock_send_mail.call_args[1]['subject'], f"Sync Job Completed: {self.job.name}")
    
    @patch('sync_jobs.notifications.send_mail')
    def test_send_job_failed_notification(self, mock_send_mail):
        """Test sending job failed notification"""
        self.execution.status = 'failed'
        self.execution.save()
        
        NotificationService.send_job_failed_notification(self.job, self.execution)
        
        # Verify email was sent
        mock_send_mail.assert_called_once()
        self.assertEqual(mock_send_mail.call_args[1]['subject'], f"Sync Job Failed: {self.job.name}")

