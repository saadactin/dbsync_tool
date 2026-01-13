"""
Integration tests for sync jobs complete workflows
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncSchedule, SyncExecution


class SyncJobWorkflowTestCase(TestCase):
    """Integration tests for complete sync job workflows"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test connections
        self.source_conn = DatabaseConnection.objects.create(
            name='Source DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user
        )
    
    def test_complete_job_creation_workflow(self):
        """Test complete job creation workflow: Step 1 → Step 2 → Step 3 → Job List"""
        self.client.login(username='testuser', password='testpass123')
        
        # Step 1: Create job with connections
        response = self.client.post(reverse('sync_jobs:create_step1'), {
            'job_name': 'Integration Test Job',
            'source_connection': str(self.source_conn.id),
            'target_connection': str(self.target_conn.id),
        }, follow=True)
        self.assertRedirects(response, reverse('sync_jobs:create_step2'))
        
        # Step 2: Select tables (simulate with session)
        session = self.client.session
        session['sync_job_name'] = 'Integration Test Job'
        session['sync_job_source_connection_id'] = str(self.source_conn.id)
        session['sync_job_target_connection_id'] = str(self.target_conn.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'public', 'table_name': 'users'},
            {'schema_name': 'public', 'table_name': 'orders'}
        ]
        session.save()
        
        response = self.client.post(reverse('sync_jobs:create_step2_submit'), {
            'selected_tables': [
                '{"schema":"public","table":"users"}',
                '{"schema":"public","table":"orders"}'
            ]
        }, follow=True)
        self.assertRedirects(response, reverse('sync_jobs:create_step3'))
        
        # Step 3: Configure and create job
        response = self.client.post(reverse('sync_jobs:create_step3_submit'), {
            'sync_type': 'full',
            'schedule_type': 'daily',
        }, follow=True)
        self.assertRedirects(response, reverse('sync_jobs:list'))
        
        # Verify job was created
        job = SyncJob.objects.get(name='Integration Test Job')
        self.assertEqual(job.source_connection, self.source_conn)
        self.assertEqual(job.target_connection, self.target_conn)
        self.assertEqual(job.tables.count(), 2)
        self.assertEqual(job.status, 'pending')
    
    def test_job_management_workflow(self):
        """Test complete job management workflow: Create → View → Edit → Pause → Resume → Delete"""
        self.client.login(username='testuser', password='testpass123')
        
        # Create a job
        job = SyncJob.objects.create(
            name='Management Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        SyncSchedule.objects.create(job=job, schedule_type='once', is_enabled=True)
        
        # View job detail
        response = self.client.get(reverse('sync_jobs:job_detail', args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Management Test Job')
        
        # Edit job
        response = self.client.post(reverse('sync_jobs:job_edit', args=[job.id]), {
            'job_name': 'Updated Management Job',
            'sync_type': 'full',
            'schedule_type': 'hourly',
        }, follow=True)
        job.refresh_from_db()
        self.assertEqual(job.name, 'Updated Management Job')
        self.assertEqual(job.schedule.schedule_type, 'hourly')
        
        # Pause job
        response = self.client.get(reverse('sync_jobs:job_pause', args=[job.id]), follow=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'paused')
        self.assertFalse(job.schedule.is_enabled)
        
        # Resume job
        response = self.client.get(reverse('sync_jobs:job_resume', args=[job.id]), follow=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')
        self.assertTrue(job.schedule.is_enabled)
        
        # Delete job
        response = self.client.post(reverse('sync_jobs:job_delete', args=[job.id]), follow=True)
        self.assertEqual(SyncJob.objects.filter(id=job.id).count(), 0)
    
    def test_filter_and_search_workflow(self):
        """Test filtering and searching jobs"""
        self.client.login(username='testuser', password='testpass123')
        
        # Create multiple jobs with different statuses
        job1 = SyncJob.objects.create(
            name='Pending Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        job2 = SyncJob.objects.create(
            name='Running Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            status='running',
            created_by=self.user
        )
        
        job3 = SyncJob.objects.create(
            name='Failed Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='failed',
            created_by=self.user
        )
        
        # Test status filter
        response = self.client.get(reverse('sync_jobs:list'), {'status': 'pending'})
        self.assertContains(response, 'Pending Job')
        self.assertNotContains(response, 'Running Job')
        self.assertNotContains(response, 'Failed Job')
        
        # Test sync type filter
        response = self.client.get(reverse('sync_jobs:list'), {'sync_type': 'incremental'})
        self.assertContains(response, 'Running Job')
        self.assertNotContains(response, 'Pending Job')
        
        # Test search
        response = self.client.get(reverse('sync_jobs:list'), {'search': 'Failed'})
        self.assertContains(response, 'Failed Job')
        self.assertNotContains(response, 'Pending Job')
        
        # Test sorting
        response = self.client.get(reverse('sync_jobs:list'), {'sort': 'name'})
        self.assertEqual(response.status_code, 200)
    
    def test_error_recovery_workflow(self):
        """Test error recovery in various scenarios"""
        self.client.login(username='testuser', password='testpass123')
        
        # Test accessing non-existent job
        fake_id = '00000000-0000-0000-0000-000000000000'
        response = self.client.get(reverse('sync_jobs:job_detail', args=[fake_id]), follow=True)
        # Should redirect with error message
        
        # Test invalid operations
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='running',
            created_by=self.user
        )
        
        # Try to pause running job
        response = self.client.get(reverse('sync_jobs:job_pause', args=[job.id]), follow=True)
        # Should show error message
        
        # Try to edit running job
        response = self.client.get(reverse('sync_jobs:job_edit', args=[job.id]), follow=True)
        # Should redirect with error message

