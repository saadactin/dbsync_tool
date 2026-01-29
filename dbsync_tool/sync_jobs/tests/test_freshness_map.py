"""
Tests for Freshness Map feature
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, SyncSchedule, FreshnessMetric
from sync_jobs.services import FreshnessMapService
from connections.models import DatabaseConnection


class FreshnessMapServiceTestCase(TestCase):
    """Test cases for FreshnessMapService"""
    
    def setUp(self):
        """Set up test data"""
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
    
    def test_calculate_freshness_no_execution(self):
        """Test freshness calculation for job with no executions"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        freshness = FreshnessMapService.calculate_freshness(job, self.user)
        
        self.assertIn('last_successful_sync', freshness)
        self.assertIn('freshness_minutes', freshness)
        self.assertIn('expected_freshness_minutes', freshness)
        self.assertIn('freshness_status', freshness)
        
        self.assertIsNone(freshness['last_successful_sync'])
        self.assertIsNone(freshness['freshness_minutes'])
        self.assertEqual(freshness['freshness_status'], 'never_run')
        self.assertEqual(freshness['expected_freshness_minutes'], 1440)  # Default 24 hours
    
    def test_calculate_freshness_with_execution(self):
        """Test freshness calculation with successful execution"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create a successful execution 30 minutes ago
        execution = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=35),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        freshness = FreshnessMapService.calculate_freshness(job, self.user)
        
        self.assertIsNotNone(freshness['last_successful_sync'])
        self.assertIsNotNone(freshness['freshness_minutes'])
        self.assertGreaterEqual(freshness['freshness_minutes'], 25)  # Should be around 30 minutes
        self.assertEqual(freshness['freshness_status'], 'fresh')  # Less than 24 hours
    
    def test_calculate_freshness_stale(self):
        """Test freshness calculation for stale job"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create schedule with hourly interval (60 minutes)
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True,
            tenant=self.user
        )
        
        # Create execution 90 minutes ago (1.5x interval = stale)
        execution = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=95),
            completed_at=timezone.now() - timedelta(minutes=90),
            total_rows_synced=100
        )
        
        freshness = FreshnessMapService.calculate_freshness(job, self.user)
        
        self.assertEqual(freshness['expected_freshness_minutes'], 60)  # Hourly
        self.assertGreaterEqual(freshness['freshness_minutes'], 85)
        self.assertEqual(freshness['freshness_status'], 'stale')  # Between 1x and 2x interval
    
    def test_calculate_freshness_critical(self):
        """Test freshness calculation for critical job"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create schedule with hourly interval (60 minutes)
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True,
            tenant=self.user
        )
        
        # Create execution 150 minutes ago (>2x interval = critical)
        execution = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=155),
            completed_at=timezone.now() - timedelta(minutes=150),
            total_rows_synced=100
        )
        
        freshness = FreshnessMapService.calculate_freshness(job, self.user)
        
        self.assertEqual(freshness['expected_freshness_minutes'], 60)
        self.assertGreaterEqual(freshness['freshness_minutes'], 145)
        self.assertEqual(freshness['freshness_status'], 'critical')  # >2x interval
    
    def test_get_expected_interval_hourly(self):
        """Test expected interval calculation for hourly schedule"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True,
            tenant=self.user
        )
        
        interval = FreshnessMapService._get_expected_interval_minutes(job)
        self.assertEqual(interval, 60)
    
    def test_get_expected_interval_daily(self):
        """Test expected interval calculation for daily schedule"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='daily',
            is_enabled=True,
            tenant=self.user
        )
        
        interval = FreshnessMapService._get_expected_interval_minutes(job)
        self.assertEqual(interval, 1440)
    
    def test_get_expected_interval_no_schedule(self):
        """Test expected interval calculation for job without schedule"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        interval = FreshnessMapService._get_expected_interval_minutes(job)
        self.assertEqual(interval, 1440)  # Default 24 hours
    
    def test_get_expected_interval_disabled_schedule(self):
        """Test expected interval calculation for disabled schedule"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=False,  # Disabled
            tenant=self.user
        )
        
        interval = FreshnessMapService._get_expected_interval_minutes(job)
        self.assertEqual(interval, 1440)  # Should use default when disabled
    
    def test_update_freshness_metric_create(self):
        """Test creating a new freshness metric"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create execution
        execution = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=30),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        # Update freshness metric
        FreshnessMapService.update_freshness_metric(job, self.user)
        
        # Check metric was created
        metric = FreshnessMetric.objects.get(job=job)
        self.assertIsNotNone(metric)
        self.assertEqual(metric.tenant, self.user)
        self.assertIsNotNone(metric.last_successful_sync)
        self.assertEqual(metric.freshness_status, 'fresh')
    
    def test_update_freshness_metric_update(self):
        """Test updating existing freshness metric"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create first execution
        execution1 = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(hours=2),
            completed_at=timezone.now() - timedelta(hours=2),
            total_rows_synced=100
        )
        
        # Update freshness metric
        FreshnessMapService.update_freshness_metric(job, self.user)
        metric1 = FreshnessMetric.objects.get(job=job)
        old_freshness = metric1.freshness_minutes
        
        # Create new execution
        execution2 = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=30),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=200
        )
        
        # Update freshness metric again
        FreshnessMapService.update_freshness_metric(job, self.user)
        metric2 = FreshnessMetric.objects.get(job=job)
        
        # Should be updated with new execution
        self.assertLess(metric2.freshness_minutes, old_freshness)
        self.assertEqual(metric2.freshness_status, 'fresh')
    
    def test_get_freshness_map(self):
        """Test getting freshness map for all jobs"""
        # Create multiple jobs
        job1 = SyncJob.objects.create(
            name='Job 1',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        job2 = SyncJob.objects.create(
            name='Job 2',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create execution for job1
        SyncExecution.objects.create(
            job=job1,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=30),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        # Get freshness map
        freshness_map = FreshnessMapService.get_freshness_map(self.user)
        
        self.assertIn('jobs', freshness_map)
        self.assertIn('summary', freshness_map)
        self.assertEqual(len(freshness_map['jobs']), 2)
        self.assertEqual(freshness_map['summary']['total'], 2)
        self.assertEqual(freshness_map['summary']['never_run'], 1)
        self.assertEqual(freshness_map['summary']['fresh'], 1)
    
    def test_get_freshness_map_with_filter(self):
        """Test getting freshness map with status filter"""
        # Create jobs with different statuses
        job1 = SyncJob.objects.create(
            name='Fresh Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        job2 = SyncJob.objects.create(
            name='Stale Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create schedule for job2
        schedule = SyncSchedule.objects.create(
            job=job2,
            schedule_type='hourly',
            is_enabled=True,
            tenant=self.user
        )
        
        # Create execution for job1 (fresh)
        SyncExecution.objects.create(
            job=job1,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=30),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=100
        )
        
        # Create execution for job2 (stale - 90 minutes ago with 60 min interval)
        SyncExecution.objects.create(
            job=job2,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=95),
            completed_at=timezone.now() - timedelta(minutes=90),
            total_rows_synced=100
        )
        
        # Get freshness map filtered by stale
        freshness_map = FreshnessMapService.get_freshness_map(self.user, status_filter='stale')
        
        self.assertEqual(len(freshness_map['jobs']), 1)
        self.assertEqual(freshness_map['jobs'][0]['name'], 'Stale Job')
        self.assertEqual(freshness_map['jobs'][0]['freshness_status'], 'stale')
    
    def test_get_last_successful_execution(self):
        """Test getting last successful execution"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create multiple executions
        execution1 = SyncExecution.objects.create(
            job=job,
            status='failed',
            started_at=timezone.now() - timedelta(hours=2),
            completed_at=timezone.now() - timedelta(hours=2),
            total_rows_synced=0
        )
        
        execution2 = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now() - timedelta(hours=1),
            total_rows_synced=100
        )
        
        execution3 = SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(minutes=30),
            completed_at=timezone.now() - timedelta(minutes=30),
            total_rows_synced=200
        )
        
        last_execution = FreshnessMapService._get_last_successful_execution(job)
        
        self.assertIsNotNone(last_execution)
        self.assertEqual(last_execution.id, execution3.id)
        self.assertEqual(last_execution.status, 'completed')
