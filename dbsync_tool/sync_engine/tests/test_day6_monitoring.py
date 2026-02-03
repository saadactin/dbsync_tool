"""
Tests for Day 6 APISyncMonitor
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog, APISyncState
from sync_engine.monitoring import APISyncMonitor
from accounts.models import UserProfile, Role


class APISyncMonitorTests(TestCase):
    """Test cases for APISyncMonitor"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create user profile
        UserProfile.objects.create(
            user=self.user,
            role=Role.ADMIN
        )
        
        # Create database connection
        self.target_conn = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create API connection
        self.api_conn = APIConnection.objects.create(
            name='Test Zoho API',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            selected_modules=['Leads', 'Contacts'],
            tenant=self.user,
            created_by=self.user
        )
        
        # Create sync job with API source
        self.job = SyncJob.objects.create(
            name='Test API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
    
    def test_get_job_metrics_no_executions(self):
        """Test get_job_metrics with no executions"""
        metrics = APISyncMonitor.get_job_metrics(self.job)
        
        self.assertEqual(metrics['job_id'], str(self.job.id))
        self.assertEqual(metrics['job_name'], self.job.name)
        self.assertEqual(metrics['total_executions'], 0)
        self.assertEqual(metrics['successful_executions'], 0)
        self.assertEqual(metrics['failed_executions'], 0)
        self.assertEqual(metrics['total_records_synced'], 0)
        self.assertEqual(metrics['module_count'], 0)
    
    def test_get_job_metrics_with_executions(self):
        """Test get_job_metrics with executions"""
        # Create executions
        exec1 = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=timezone.now() - timedelta(hours=2),
            completed_at=timezone.now() - timedelta(hours=1)
        )
        exec2 = SyncExecution.objects.create(
            job=self.job,
            status='failed',
            started_at=timezone.now() - timedelta(hours=1)
        )
        
        # Create sync states
        APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        APISyncState.objects.create(
            job=self.job,
            module_name='Contacts',
            records_synced=200
        )
        
        metrics = APISyncMonitor.get_job_metrics(self.job)
        
        self.assertEqual(metrics['total_executions'], 2)
        self.assertEqual(metrics['successful_executions'], 1)
        self.assertEqual(metrics['failed_executions'], 1)
        self.assertEqual(metrics['total_records_synced'], 300)
        self.assertEqual(metrics['module_count'], 2)
        self.assertIsNotNone(metrics['success_rate'])
        self.assertEqual(metrics['success_rate'], 50.0)
    
    def test_get_module_metrics_not_synced(self):
        """Test get_module_metrics for module that hasn't been synced"""
        metrics = APISyncMonitor.get_module_metrics(self.job, 'Leads')
        
        self.assertEqual(metrics['module_name'], 'Leads')
        self.assertEqual(metrics['status'], 'not_synced')
    
    def test_get_module_metrics_synced(self):
        """Test get_module_metrics for synced module"""
        # Create sync state
        sync_time = timezone.now() - timedelta(hours=2)
        state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            last_sync_time=sync_time,
            last_modified_time=sync_time - timedelta(hours=1),
            records_synced=100
        )
        
        # Create execution log
        execution = SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=sync_time
        )
        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name='api',
            table_name='Leads',
            status='completed',
            rows_inserted=100,
            started_at=sync_time
        )
        
        metrics = APISyncMonitor.get_module_metrics(self.job, 'Leads')
        
        self.assertEqual(metrics['module_name'], 'Leads')
        self.assertEqual(metrics['status'], 'synced')
        self.assertEqual(metrics['records_synced'], 100)
        self.assertIsNotNone(metrics['data_freshness_hours'])
        self.assertEqual(metrics['total_runs'], 1)
        self.assertEqual(metrics['successful_runs'], 1)
        self.assertEqual(metrics['success_rate'], 100.0)
    
    def test_get_health_status_healthy(self):
        """Test get_health_status for healthy job"""
        # Create recent successful execution
        SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=timezone.now() - timedelta(hours=1)
        )
        
        # Create fresh sync state
        APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            last_sync_time=timezone.now() - timedelta(hours=1),
            records_synced=100
        )
        
        health = APISyncMonitor.get_health_status(self.job)
        
        self.assertEqual(health, 'healthy')
    
    def test_get_health_status_warning(self):
        """Test get_health_status for job with warnings"""
        # Create job with old data
        APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            last_sync_time=timezone.now() - timedelta(days=10),
            records_synced=100
        )
        
        health = APISyncMonitor.get_health_status(self.job)
        
        self.assertEqual(health, 'warning')
    
    def test_get_health_status_error(self):
        """Test get_health_status for job with errors"""
        # Create job with high failure rate
        for i in range(6):
            SyncExecution.objects.create(
                job=self.job,
                status='failed' if i < 4 else 'completed',
                started_at=timezone.now() - timedelta(days=i)
            )
        
        health = APISyncMonitor.get_health_status(self.job)
        
        self.assertEqual(health, 'error')
    
    def test_get_health_status_paused(self):
        """Test get_health_status for paused job"""
        self.job.status = 'paused'
        self.job.save()
        
        health = APISyncMonitor.get_health_status(self.job)
        
        self.assertEqual(health, 'warning')
    
    def test_get_all_jobs_summary(self):
        """Test get_all_jobs_summary"""
        # Create another job
        job2 = SyncJob.objects.create(
            name='Test API Job 2',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create sync states
        APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        APISyncState.objects.create(
            job=job2,
            module_name='Contacts',
            records_synced=200
        )
        
        summary = APISyncMonitor.get_all_jobs_summary()
        
        self.assertGreaterEqual(summary['total_jobs'], 2)
        self.assertGreaterEqual(summary['total_modules'], 2)
        self.assertGreaterEqual(summary['total_records_synced'], 300)
