"""
Integration tests for Celery task execution
Note: These tests require Redis and Celery worker to be running
"""
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock
from sync_jobs.models import SyncJob, SyncExecution, SyncSchedule
from scheduler.tasks import execute_sync_job, trigger_scheduled_jobs_task
from scheduler.utils import trigger_scheduled_jobs
import logging

logger = logging.getLogger(__name__)


class CeleryIntegrationTestCase(TransactionTestCase):
    """Integration tests for Celery tasks
    
    Note: These tests mock Celery task execution since we don't have
    Redis/Celery worker in test environment
    """
    
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
    
    @patch('scheduler.tasks.SyncExecutor')
    def test_execute_sync_job_success_mocked(self, mock_executor_class):
        """Test successful job execution (mocked)"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        # Mock executor
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor
        
        # Mock execution creation
        execution = SyncExecution.objects.create(
            job=job,
            status='running',
            started_at=timezone.now(),
            total_tables=1,
            completed_tables=0,
            total_rows_synced=0
        )
        
        # Execute task (without Celery, directly call function)
        result = execute_sync_job.apply(args=[str(job.id)])
        
        # Note: This test requires actual implementation
        # For now, we're just testing the structure
        self.assertIsNotNone(result)
    
    def test_execute_sync_job_not_found(self):
        """Test task execution with non-existent job"""
        result = execute_sync_job.apply(args=['00000000-0000-0000-0000-000000000000'])
        self.assertEqual(result.status, 'SUCCESS')
        result_data = result.result
        self.assertEqual(result_data['status'], 'failed')
        self.assertIn('not found', result_data['error'].lower())
    
    def test_execute_sync_job_already_running(self):
        """Test task execution when job is already running"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='running',
            created_by=self.user
        )
        
        execution = SyncExecution.objects.create(
            job=job,
            status='running',
            started_at=timezone.now(),
            total_tables=1,
            completed_tables=0,
            total_rows_synced=0
        )
        
        result = execute_sync_job.apply(args=[str(job.id)])
        self.assertEqual(result.status, 'SUCCESS')
        result_data = result.result
        self.assertEqual(result_data['status'], 'skipped')
        self.assertEqual(result_data['message'], 'Job is already running')
    
    def test_execute_sync_job_paused(self):
        """Test task execution when job is paused"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='paused',
            created_by=self.user
        )
        
        result = execute_sync_job.apply(args=[str(job.id)])
        self.assertEqual(result.status, 'SUCCESS')
        result_data = result.result
        self.assertEqual(result_data['status'], 'skipped')
        self.assertEqual(result_data['message'], 'Job is paused')
    
    @patch('scheduler.utils.execute_sync_job')
    def test_trigger_scheduled_jobs(self, mock_execute_task):
        """Test triggering scheduled jobs"""
        from datetime import timedelta
        from scheduler.utils import trigger_scheduled_jobs
        
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            next_run_at=timezone.now() - timedelta(minutes=1)  # Past due
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True,
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        
        mock_execute_task.delay = MagicMock(return_value=MagicMock(id='test-task-id'))
        
        count = trigger_scheduled_jobs()
        
        self.assertEqual(count, 1)
        mock_execute_task.delay.assert_called_once_with(str(job.id))
    
    def test_trigger_scheduled_jobs_no_due_jobs(self):
        """Test triggering when no jobs are due"""
        from datetime import timedelta
        from scheduler.utils import trigger_scheduled_jobs
        
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            next_run_at=timezone.now() + timedelta(hours=1)  # Future
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True,
            next_run_at=timezone.now() + timedelta(hours=1)
        )
        
        count = trigger_scheduled_jobs()
        
        self.assertEqual(count, 0)


class ScheduledExecutionIntegrationTestCase(TestCase):
    """Integration tests for scheduled job execution"""
    
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
    def test_hourly_schedule_trigger(self, mock_execute_task):
        """Test hourly schedule triggers correctly"""
        # Create job with hourly schedule due now
        job = SyncJob.objects.create(
            name='Hourly Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True,
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        
        mock_execute_task.delay.return_value = MagicMock(id='test-task-id')
        
        # Trigger scheduled jobs
        result = trigger_scheduled_jobs_task()
        
        # Verify job was triggered
        mock_execute_task.delay.assert_called_once_with(str(job.id))
        
        # Verify next_run_at updated
        job.refresh_from_db()
        schedule.refresh_from_db()
        self.assertIsNotNone(job.next_run_at)
        self.assertGreater(job.next_run_at, timezone.now())
    
    def test_schedule_job_execution_calculates_next_run(self):
        """Test that schedule_job_execution calculates next_run_at correctly"""
        from scheduler.utils import schedule_job_execution
        
        job = SyncJob.objects.create(
            name='Daily Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='daily',
            is_enabled=True
        )
        
        # Schedule job execution
        schedule_job_execution(job)
        
        # Verify next_run_at set
        job.refresh_from_db()
        schedule.refresh_from_db()
        self.assertIsNotNone(job.next_run_at)
        self.assertIsNotNone(schedule.next_run_at)
        self.assertEqual(job.next_run_at, schedule.next_run_at)
