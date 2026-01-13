"""
Comprehensive unit tests for Celery tasks
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock, call
from sync_jobs.models import SyncJob, SyncExecution, SyncSchedule
from scheduler.tasks import execute_sync_job, cleanup_old_executions, trigger_scheduled_jobs_task
import uuid


class ExecuteSyncJobTaskTestCase(TestCase):
    """Test cases for execute_sync_job task"""
    
    def setUp(self):
        """Set up test data"""
        from django.contrib.auth.models import User
        from connections.models import DatabaseConnection
        
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
        
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
    
    @patch('scheduler.tasks.SyncExecutor')
    def test_execute_sync_job_success(self, mock_executor_class):
        """Test successful job execution"""
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor
        
        # Execute task
        result = execute_sync_job(str(self.job.id))
        
        # Verify
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['job_id'], str(self.job.id))
        mock_executor.execute.assert_called_once()
    
    def test_execute_sync_job_not_found(self):
        """Test job not found"""
        fake_id = str(uuid.uuid4())
        result = execute_sync_job(fake_id)
        
        self.assertEqual(result['status'], 'failed')
        self.assertIn('not found', result['error'].lower())
    
    def test_execute_sync_job_already_running(self):
        """Test job already running"""
        self.job.status = 'running'
        self.job.save()
        
        execution = SyncExecution.objects.create(
            job=self.job,
            status='running',
            started_at=timezone.now()
        )
        
        result = execute_sync_job(str(self.job.id))
        
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('already running', result['message'].lower())
    
    def test_execute_sync_job_paused(self):
        """Test paused job"""
        self.job.status = 'paused'
        self.job.save()
        
        result = execute_sync_job(str(self.job.id))
        
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('paused', result['message'].lower())


class TriggerScheduledJobsTaskTestCase(TestCase):
    """Test cases for trigger_scheduled_jobs_task"""
    
    def setUp(self):
        """Set up test data"""
        from django.contrib.auth.models import User
        from connections.models import DatabaseConnection
        
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
    
    @patch('scheduler.tasks.execute_sync_job')
    def test_trigger_scheduled_jobs_due(self, mock_execute_task):
        """Test triggering due scheduled jobs"""
        # Create job with schedule due now
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        
        SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True,
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        
        mock_execute_task.delay.return_value = MagicMock(id='test-task-id')
        
        # Execute task
        result = trigger_scheduled_jobs_task()
        
        # Verify
        self.assertIn('Triggered', result)
        mock_execute_task.delay.assert_called_once_with(str(job.id))
    
    def test_trigger_scheduled_jobs_no_due_jobs(self):
        """Test with no due jobs"""
        result = trigger_scheduled_jobs_task()
        
        self.assertIn('0', result)  # "Triggered 0 scheduled job(s)"


class CleanupOldExecutionsTestCase(TestCase):
    """Test cases for cleanup_old_executions task"""
    
    def setUp(self):
        """Set up test data"""
        from django.contrib.auth.models import User
        from connections.models import DatabaseConnection
        
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
        
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
    
    def test_cleanup_old_executions(self):
        """Test cleanup of old executions"""
        # Create old execution
        old_execution = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=timezone.now() - timedelta(days=91),
            completed_at=timezone.now() - timedelta(days=91)
        )
        
        # Create recent execution (should not be deleted)
        recent_execution = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=timezone.now() - timedelta(days=30),
            completed_at=timezone.now() - timedelta(days=30)
        )
        
        # Run cleanup
        deleted_count = cleanup_old_executions()
        
        # Verify
        self.assertEqual(deleted_count, 1)
        self.assertFalse(SyncExecution.objects.filter(id=old_execution.id).exists())
        self.assertTrue(SyncExecution.objects.filter(id=recent_execution.id).exists())
    
    def test_cleanup_old_executions_no_old(self):
        """Test cleanup task with no old executions"""
        result = cleanup_old_executions()
        self.assertIsInstance(result, int)
        self.assertEqual(result, 0)
    
    def test_cleanup_old_executions_with_old(self):
        """Test cleanup task with old executions"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user
        )
        
        # Create old execution (100 days ago)
        old_date = timezone.now() - timedelta(days=100)
        old_execution = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=old_date,
            completed_at=old_date + timedelta(minutes=5),
            total_tables=1,
            completed_tables=1,
            total_rows_synced=100
        )
        
        # Create recent execution (10 days ago)
        recent_date = timezone.now() - timedelta(days=10)
        recent_execution = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=recent_date,
            completed_at=recent_date + timedelta(minutes=5),
            total_tables=1,
            completed_tables=1,
            total_rows_synced=100
        )
        
        result = cleanup_old_executions()
        self.assertEqual(result, 1)  # Only old execution deleted
        
        # Verify old execution is deleted
        self.assertFalse(SyncExecution.objects.filter(id=old_execution.id).exists())
        # Verify recent execution still exists
        self.assertTrue(SyncExecution.objects.filter(id=recent_execution.id).exists())
    
    def test_cleanup_old_executions_only_completed_failed(self):
        """Test cleanup only removes completed/failed executions"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user
        )
        
        # Create old running execution (should not be deleted)
        old_date = timezone.now() - timedelta(days=100)
        old_running = SyncExecution.objects.create(
            job=job,
            status='running',
            started_at=old_date,
            total_tables=1,
            completed_tables=0,
            total_rows_synced=0
        )
        
        # Create old completed execution (should be deleted)
        old_completed = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=old_date,
            completed_at=old_date + timedelta(minutes=5),
            total_tables=1,
            completed_tables=1,
            total_rows_synced=100
        )
        
        result = cleanup_old_executions()
        self.assertEqual(result, 1)  # Only completed execution deleted
        
        # Verify running execution still exists
        self.assertTrue(SyncExecution.objects.filter(id=old_running.id).exists())
        # Verify completed execution is deleted
        self.assertFalse(SyncExecution.objects.filter(id=old_completed.id).exists())

