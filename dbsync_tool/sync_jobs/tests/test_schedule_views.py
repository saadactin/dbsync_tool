"""
Integration tests for schedule management views
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncSchedule
from connections.models import DatabaseConnection
from accounts.models import UserProfile, Role


class ScheduleViewsTestCase(TestCase):
    """Test cases for schedule management views"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN, 'tenant': self.user},
        )
        self.client.login(username='testuser', password='testpass123')
        
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
        )
        
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        
        self.schedule = SyncSchedule.objects.create(
            job=self.job,
            schedule_type='hourly',
            is_enabled=True,
            tenant=self.user,
        )
    
    def test_pause_job_disables_schedule(self):
        """Test that pausing a job disables its schedule"""
        url = reverse('sync_jobs:job_pause', args=[self.job.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 302)  # Redirect
        
        # Refresh from database
        self.schedule.refresh_from_db()
        self.assertFalse(self.schedule.is_enabled)
        
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'paused')
    
    def test_resume_job_enables_schedule(self):
        """Test that resuming a job re-enables its schedule"""
        # First pause the job
        self.job.status = 'paused'
        self.job.save()
        self.schedule.is_enabled = False
        self.schedule.save()
        
        # Resume the job
        url = reverse('sync_jobs:job_resume', args=[self.job.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 302)  # Redirect
        
        # Refresh from database
        self.schedule.refresh_from_db()
        self.assertTrue(self.schedule.is_enabled)
        
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'pending')
        
        # Verify next_run_at was recalculated
        self.assertIsNotNone(self.job.next_run_at)
        self.assertIsNotNone(self.schedule.next_run_at)
    
    def test_update_schedule(self):
        """Test updating a job's schedule"""
        url = reverse('sync_jobs:update_schedule', args=[self.job.id])
        
        response = self.client.post(url, {
            'schedule_type': 'daily',
            'is_enabled': 'on',
            'start_datetime': ''
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect
        
        # Refresh from database
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.schedule_type, 'daily')
        self.assertTrue(self.schedule.is_enabled)

    def test_update_schedule_hourly_interval_hours(self):
        """Hourly schedule stores interval_hours from POST."""
        url = reverse('sync_jobs:update_schedule', args=[self.job.id])
        future = (timezone.now() + timedelta(days=1)).isoformat()
        response = self.client.post(
            url,
            {
                'schedule_type': 'hourly',
                'is_enabled': 'on',
                'start_datetime': future,
                'interval_hours': '4',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.schedule_type, 'hourly')
        self.assertEqual(self.schedule.interval_hours, 4)
    
    def test_update_schedule_custom_cron(self):
        """Test updating schedule with custom cron expression"""
        url = reverse('sync_jobs:update_schedule', args=[self.job.id])
        
        response = self.client.post(url, {
            'schedule_type': 'custom',
            'cron_expression': '0 0 * * *',
            'is_enabled': 'on',
            'start_datetime': ''
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect
        
        # Refresh from database
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.schedule_type, 'custom')
        self.assertEqual(self.schedule.cron_expression, '0 0 * * *')
    
    def test_update_schedule_invalid_type(self):
        """Test updating schedule with invalid schedule type"""
        url = reverse('sync_jobs:update_schedule', args=[self.job.id])
        
        response = self.client.post(url, {
            'schedule_type': 'invalid',
            'is_enabled': 'on',
            'start_datetime': ''
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect (with error message)
    
    def test_update_schedule_custom_missing_cron(self):
        """Test updating schedule with custom type but no cron expression"""
        url = reverse('sync_jobs:update_schedule', args=[self.job.id])
        
        response = self.client.post(url, {
            'schedule_type': 'custom',
            'cron_expression': '',
            'is_enabled': 'on',
            'start_datetime': ''
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect (with error message)

