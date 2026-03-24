from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncSchedule, SyncExecution, SyncExecutionLog
from accounts.models import UserProfile, Role


class SyncJobCreationTestCase(TestCase):
    """Test cases for sync job creation flow"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Ensure user has a tenant profile so TenantService scoping works
        UserProfile.objects.update_or_create(
            user=self.user, defaults={'role': Role.ADMIN, 'tenant': self.user}
        )
        
        # Create test connections (assign tenant so tenant scoping includes them)
        self.source_conn = DatabaseConnection.objects.create(
            name='Source DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user,
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user,
        )
    
    def test_step1_access_requires_login(self):
        """Test that Step 1 requires authentication"""
        response = self.client.get(reverse('sync_jobs:create_step1'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_step1_displays_connections(self):
        """Test Step 1 displays user's connections"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:create_step1'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Source DB')
        self.assertContains(response, 'Target DB')
    
    def test_step1_validates_same_connection(self):
        """Test Step 1 prevents selecting same connection for source and target"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('sync_jobs:create_step1'), {
            'job_name': 'Test Job',
            'source_connection': str(self.source_conn.id),
            'target_connection': str(self.source_conn.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cannot be the same')
    
    def test_step1_redirects_to_step2_on_success(self):
        """Test Step 1 redirects to Step 2 on successful submission"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('sync_jobs:create_step1'), {
            'job_name': 'Test Job',
            'source_connection': str(self.source_conn.id),
            'target_connection': str(self.target_conn.id),
        }, follow=True)
        self.assertRedirects(response, reverse('sync_jobs:create_step2'))
    
    def test_step3_creates_job_successfully(self):
        """Test Step 3 creates sync job in database"""
        self.client.login(username='testuser', password='testpass123')
        
        # Set up session data
        session = self.client.session
        session['sync_job_name'] = 'Test Job'
        session['sync_job_source_connection_id'] = str(self.source_conn.id)
        session['sync_job_target_connection_id'] = str(self.target_conn.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'public', 'table_name': 'users'}
        ]
        session.save()
        
        # Submit Step 3
        response = self.client.post(reverse('sync_jobs:create_step3_submit'), {
            'sync_type': 'full',
            'schedule_type': 'once',
        }, follow=True)
        
        # Verify job was created
        self.assertEqual(SyncJob.objects.count(), 1)
        job = SyncJob.objects.first()
        self.assertEqual(job.name, 'Test Job')
        self.assertEqual(job.source_connection, self.source_conn)
        self.assertEqual(job.target_connection, self.target_conn)
        self.assertEqual(job.sync_type, 'full')
        
        # Verify tables were created
        self.assertEqual(SyncJobTable.objects.count(), 1)
        table = SyncJobTable.objects.first()
        self.assertEqual(table.schema_name, 'public')
        self.assertEqual(table.table_name, 'users')
        
        # Verify schedule was created
        self.assertEqual(SyncSchedule.objects.count(), 1)
        schedule = SyncSchedule.objects.first()
        self.assertEqual(schedule.schedule_type, 'once')

    @patch('sync_jobs.views.load_table_columns')
    def test_step3_incremental_db_does_not_require_manual_incremental_columns(self, mock_load_columns):
        """Incremental DB job creation should succeed without incremental_column_* inputs."""
        mock_load_columns.return_value = [
            {'name': 'id', 'data_type': 'int'},
            {'name': 'updated_at', 'data_type': 'timestamp'},
        ]
        self.client.login(username='testuser', password='testpass123')

        session = self.client.session
        session['sync_job_name'] = 'Auto Incremental Job'
        session['sync_job_source_connection_type'] = 'database'
        session['sync_job_source_connection_id'] = str(self.source_conn.id)
        session['sync_job_target_connection_id'] = str(self.target_conn.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'public', 'table_name': 'users'}
        ]
        session.save()

        response = self.client.post(reverse('sync_jobs:create_step4_submit'), {
            'sync_type': 'incremental',
            'schedule_type': 'once',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        job = SyncJob.objects.get(name='Auto Incremental Job')
        self.assertEqual(job.sync_type, 'incremental')
        table = SyncJobTable.objects.get(job=job, schema_name='public', table_name='users')
        self.assertIsNone(table.incremental_column)


class SyncJobManagementTestCase(TestCase):
    """Test cases for job management operations"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
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
        
        # Create test job
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        
        SyncSchedule.objects.create(
            job=self.job,
            schedule_type='once',
            is_enabled=True
        )
        
        SyncJobTable.objects.create(
            job=self.job,
            schema_name='public',
            table_name='users',
            is_enabled=True
        )

        # Azure DevOps API connection and job for listing/filter tests
        self.azure_api_conn = APIConnection.objects.create(
            name='Azure DevOps API',
            api_type='azure_devops',
            organization='MyOrg',
            azure_tenant_id='tenant-guid-123',
            azure_client_id='client-guid-456',
            azure_client_secret='secret-789',
            selected_modules=['ProjA', 'ProjB'],
            tenant=self.user,
            created_by=self.user
        )
        self.azure_job = SyncJob.objects.create(
            name='Azure DevOps Job',
            source_connection=None,
            source_api_connection=self.azure_api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        SyncJobTable.objects.create(
            job=self.azure_job,
            schema_name='api',
            table_name='ProjA',
            is_enabled=True
        )
    
    def test_job_list_requires_login(self):
        """Test that job list requires authentication"""
        response = self.client.get(reverse('sync_jobs:list'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_job_list_displays_jobs(self):
        """Test job list displays user's jobs"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Job')
        self.assertContains(response, 'Azure DevOps Job')

    def test_job_list_marks_azure_devops_jobs(self):
        """Job list shows Azure DevOps badge for Azure API jobs."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Azure DevOps Job')
        self.assertContains(response, 'Azure DevOps')

    def test_job_list_filter_by_azure_devops(self):
        """Filter by Azure DevOps source type returns only Azure DevOps jobs."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'), {'source_type': 'azure_devops'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Azure DevOps Job')
        self.assertNotContains(response, 'Test Job')
    
    def test_job_list_filtering_by_status(self):
        """Test job list filtering by status"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'), {'status': 'pending'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Job')
    
    def test_job_list_search(self):
        """Test job list search functionality"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:list'), {'search': 'Test'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Job')
    
    def test_job_detail_requires_login(self):
        """Test that job detail requires authentication"""
        response = self.client.get(reverse('sync_jobs:job_detail', args=[self.job.id]))
        self.assertEqual(response.status_code, 302)
    
    def test_job_detail_displays_job(self):
        """Test job detail displays job information"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:job_detail', args=[self.job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Job')
        self.assertContains(response, 'Source DB')
        self.assertContains(response, 'Target DB')
    
    def test_job_detail_permission_check(self):
        """Test job detail only shows jobs owned by user"""
        self.client.login(username='otheruser', password='otherpass123')
        response = self.client.get(reverse('sync_jobs:job_detail', args=[self.job.id]))
        self.assertEqual(response.status_code, 302)  # Redirected
    
    def test_job_delete_requires_login(self):
        """Test that job delete requires authentication"""
        response = self.client.get(reverse('sync_jobs:job_delete', args=[self.job.id]))
        self.assertEqual(response.status_code, 302)
    
    def test_job_delete_confirmation_page(self):
        """Test job delete shows confirmation page"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:job_delete', args=[self.job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Confirm Deletion')
        self.assertContains(response, 'Test Job')
    
    def test_job_delete_success(self):
        """Test job delete removes job from database"""
        self.client.login(username='testuser', password='testpass123')
        job_id = self.job.id
        response = self.client.post(reverse('sync_jobs:job_delete', args=[job_id]), follow=True)
        self.assertRedirects(response, reverse('sync_jobs:list'))
        self.assertEqual(SyncJob.objects.filter(id=job_id).count(), 0)
    
    def test_job_delete_permission_check(self):
        """Test job delete only works for job owner"""
        self.client.login(username='otheruser', password='otherpass123')
        job_id = self.job.id
        response = self.client.post(reverse('sync_jobs:job_delete', args=[job_id]))
        self.assertEqual(response.status_code, 302)  # Redirected
        self.assertEqual(SyncJob.objects.filter(id=job_id).count(), 1)  # Job still exists
    
    def test_job_pause_success(self):
        """Test job pause changes status to paused"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'pending'
        self.job.save()
        response = self.client.get(reverse('sync_jobs:job_pause', args=[self.job.id]), follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'paused')
        self.assertFalse(self.job.schedule.is_enabled)
    
    def test_job_pause_running_job_fails(self):
        """Test cannot pause a running job"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'running'
        self.job.save()
        response = self.client.get(reverse('sync_jobs:job_pause', args=[self.job.id]), follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'running')  # Status unchanged
    
    def test_job_resume_success(self):
        """Test job resume changes status from paused to pending"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'paused'
        self.job.save()
        self.job.schedule.is_enabled = False
        self.job.schedule.save()
        response = self.client.get(reverse('sync_jobs:job_resume', args=[self.job.id]), follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'pending')
        self.assertTrue(self.job.schedule.is_enabled)
    
    def test_job_resume_non_paused_fails(self):
        """Test cannot resume a non-paused job"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'pending'
        self.job.save()
        response = self.client.get(reverse('sync_jobs:job_resume', args=[self.job.id]), follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'pending')  # Status unchanged
    
    def test_job_edit_requires_login(self):
        """Test that job edit requires authentication"""
        response = self.client.get(reverse('sync_jobs:job_edit', args=[self.job.id]))
        self.assertEqual(response.status_code, 302)
    
    def test_job_edit_displays_form(self):
        """Test job edit displays form with current values"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:job_edit', args=[self.job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Job')
    
    def test_job_edit_updates_job(self):
        """Test job edit updates job successfully"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('sync_jobs:job_edit', args=[self.job.id]), {
            'job_name': 'Updated Job Name',
            'sync_type': 'full',
            'schedule_type': 'daily',
        }, follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.name, 'Updated Job Name')
        self.job.schedule.refresh_from_db()
        self.assertEqual(self.job.schedule.schedule_type, 'daily')
    
    def test_job_edit_running_job_fails(self):
        """Test cannot edit a running job"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'running'
        self.job.save()
        response = self.client.get(reverse('sync_jobs:job_edit', args=[self.job.id]), follow=True)
        # Should redirect with error message
    
    def test_job_run_now_success(self):
        """Test run now triggers job execution"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'pending'
        self.job.save()
        response = self.client.get(reverse('sync_jobs:job_run_now', args=[self.job.id]), follow=True)
        # Job status should be updated (placeholder for Week 3)
    
    def test_job_run_now_running_job_fails(self):
        """Test cannot run a job that is already running"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'running'
        self.job.save()
        response = self.client.get(reverse('sync_jobs:job_run_now', args=[self.job.id]), follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'running')  # Status unchanged
    
    def test_job_run_now_paused_job_fails(self):
        """Test cannot run a paused job"""
        self.client.login(username='testuser', password='testpass123')
        self.job.status = 'paused'
        self.job.save()
        response = self.client.get(reverse('sync_jobs:job_run_now', args=[self.job.id]), follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'paused')  # Status unchanged

