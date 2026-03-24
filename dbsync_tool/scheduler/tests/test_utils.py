"""
Unit tests for scheduler utilities
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncSchedule
from scheduler.utils import (
    calculate_next_run,
    normalize_initial_next_run_for_schedule,
    schedule_job_execution,
)


class ScheduleUtilsTestCase(TestCase):
    """Test cases for schedule utilities"""
    
    def setUp(self):
        """Set up test data"""
        from django.contrib.auth.models import User
        from connections.models import DatabaseConnection
        
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Create test connections (simplified - actual connections needed for full tests)
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
    
    def test_calculate_next_run_hourly(self):
        """Hourly without anchor falls back to next hour at :00."""
        schedule = SyncSchedule(
            schedule_type='hourly',
            is_enabled=True
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNotNone(next_run)
        self.assertGreater(next_run, timezone.now())
        expected_min = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        self.assertLessEqual(abs((next_run - expected_min).total_seconds()), 60)

    def test_calculate_next_run_hourly_advances_anchor(self):
        """Hourly with past next_run_at advances hour-by-hour keeping minute."""
        past = timezone.now() - timedelta(hours=3)
        past = past.replace(minute=22, second=0, microsecond=0)
        schedule = SyncSchedule(
            schedule_type='hourly',
            is_enabled=True,
            next_run_at=past,
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNotNone(next_run)
        self.assertGreater(next_run, timezone.now())
        self.assertEqual(next_run.minute, 22)

    def test_calculate_next_run_hourly_every_three_hours(self):
        """Hourly with interval_hours=3 advances in 3-hour steps; minute preserved."""
        past = timezone.now() - timedelta(hours=2)
        past = past.replace(minute=40, second=0, microsecond=0)
        schedule = SyncSchedule(
            schedule_type='hourly',
            interval_hours=3,
            is_enabled=True,
            next_run_at=past,
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNotNone(next_run)
        self.assertGreater(next_run, timezone.now())
        self.assertEqual(next_run.minute, 40)
        delta = next_run - past.replace(second=0, microsecond=0)
        self.assertEqual(delta % timedelta(hours=3), timedelta(0))
    
    def test_calculate_next_run_daily(self):
        """Test daily schedule calculation"""
        schedule = SyncSchedule(
            schedule_type='daily',
            is_enabled=True
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNotNone(next_run)
        # Should be at midnight
        self.assertEqual(next_run.hour, 0)
        self.assertEqual(next_run.minute, 0)
        self.assertGreater(next_run, timezone.now())
    
    def test_calculate_next_run_weekly(self):
        """Test weekly schedule calculation"""
        schedule = SyncSchedule(
            schedule_type='weekly',
            is_enabled=True
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNotNone(next_run)
        # Should be at midnight on Monday
        self.assertEqual(next_run.hour, 0)
        self.assertEqual(next_run.minute, 0)
        self.assertGreater(next_run, timezone.now())
    
    def test_calculate_next_run_disabled(self):
        """Test disabled schedule returns None"""
        schedule = SyncSchedule(
            schedule_type='hourly',
            is_enabled=False
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNone(next_run)
    
    def test_calculate_next_run_once_future(self):
        """Test 'once' schedule with future date"""
        future_time = timezone.now() + timedelta(days=1)
        schedule = SyncSchedule(
            schedule_type='once',
            is_enabled=True,
            next_run_at=future_time
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNotNone(next_run)
        self.assertEqual(next_run, future_time)
    
    def test_calculate_next_run_once_past(self):
        """Test 'once' schedule that's already past"""
        schedule = SyncSchedule(
            schedule_type='once',
            is_enabled=True,
            next_run_at=timezone.now() - timedelta(days=1)
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNone(next_run)
    
    def test_calculate_next_run_custom(self):
        """Custom schedule uses cron parser for next run."""
        schedule = SyncSchedule(
            schedule_type='custom',
            is_enabled=True,
            cron_expression='0 0 * * *'  # Daily at midnight
        )
        next_run = calculate_next_run(schedule)
        self.assertIsNotNone(next_run)
        self.assertGreater(next_run, timezone.now() - timedelta(days=1))

    def test_normalize_initial_next_run_hourly_daily(self):
        now = timezone.now()
        base = now + timedelta(hours=1)
        base = base.replace(minute=15, second=0, microsecond=0)
        h = normalize_initial_next_run_for_schedule('hourly', base)
        self.assertGreater(h, now)
        self.assertEqual(h.minute, 15)

        d = normalize_initial_next_run_for_schedule(
            'daily', now.replace(hour=9, minute=30, second=0, microsecond=0) - timedelta(days=1)
        )
        self.assertGreater(d, now)
        self.assertEqual(d.hour, 9)
        self.assertEqual(d.minute, 30)

    def test_normalize_initial_next_run_weekly(self):
        now = timezone.now()
        base = now + timedelta(days=3)
        base = base.replace(hour=16, minute=45, second=0, microsecond=0)
        w = normalize_initial_next_run_for_schedule('weekly', base)
        self.assertGreater(w, now)
        self.assertEqual(w.hour, 16)
        self.assertEqual(w.minute, 45)

    def test_normalize_initial_next_run_hourly_interval_three(self):
        now = timezone.now()
        base = now - timedelta(hours=1)
        base = base.replace(minute=10, second=0, microsecond=0)
        h = normalize_initial_next_run_for_schedule(
            'hourly', base, interval_hours=3
        )
        self.assertGreater(h, now)
        self.assertEqual(h.minute, 10)
        delta = h - base.replace(second=0, microsecond=0)
        self.assertEqual(delta % timedelta(hours=3), timedelta(0))
    
    def test_schedule_job_execution_with_schedule(self):
        """Test scheduling job execution"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=True
        )
        
        schedule_job_execution(job)
        
        job.refresh_from_db()
        schedule.refresh_from_db()
        
        self.assertIsNotNone(job.next_run_at)
        self.assertIsNotNone(schedule.next_run_at)
        self.assertEqual(job.next_run_at, schedule.next_run_at)
    
    def test_schedule_job_execution_no_schedule(self):
        """Test scheduling job without schedule"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        # Should not raise error
        schedule_job_execution(job)
    
    def test_schedule_job_execution_disabled_schedule(self):
        """Test scheduling job with disabled schedule"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='hourly',
            is_enabled=False
        )
        
        schedule_job_execution(job)
        
        job.refresh_from_db()
        # next_run_at should not be set
        self.assertIsNone(job.next_run_at)

