"""
Tests for API sync job creation views (Step 1, Step 2, Step 3)
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, APISyncState
from accounts.models import UserProfile, Role


class APISyncJobCreationViewsTests(TestCase):
    """Test cases for API sync job creation flow"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create or update user profile (handles auto-created profiles via signals)
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN, 'tenant': self.user}
        )
        
        # Create database connections
        self.db_conn1 = DatabaseConnection.objects.create(
            name='PostgreSQL DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        self.db_conn2 = DatabaseConnection.objects.create(
            name='MySQL DB',
            db_type='mysql',
            host='localhost',
            port=3306,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create API connection
        self.api_conn = APIConnection.objects.create(
            name='Zoho CRM API',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            selected_modules=['Leads', 'Contacts', 'Accounts'],
            tenant=self.user,
            created_by=self.user
        )

        # Azure DevOps API connection for Azure-specific tests
        self.azure_conn = APIConnection.objects.create(
            name='Azure DevOps API',
            api_type='azure_devops',
            organization='MyOrg',
            azure_tenant_id='tenant-guid-123',
            azure_client_id='client-guid-456',
            azure_client_secret='secret-789',
            selected_modules=['ProjA', 'ProjB'],
            tenant=self.user,
            created_by=self.user,
        )

        # Mark connections as tested so Step 1 validation passes
        now = timezone.now()
        for conn in (self.db_conn1, self.db_conn2):
            conn.last_tested_at = now
            conn.save(update_fields=['last_tested_at'])
        for api_conn in (self.api_conn, self.azure_conn):
            api_conn.last_tested_at = now
            api_conn.save(update_fields=['last_tested_at'])
    
    def test_step1_displays_api_connections(self):
        """Test Step 1 displays API connections"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('sync_jobs:create_step1'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Zoho CRM API')
        self.assertContains(response, 'PostgreSQL DB')
        self.assertContains(response, 'MySQL DB')
    
    def test_step1_creates_job_with_api_source(self):
        """Test Step 1 creates job with API source"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.post(reverse('sync_jobs:create_step1'), {
            'job_name': 'Test API Job',
            'source_connection': str(self.api_conn.id),
            'source_connection_type': 'api',
            'target_connection': str(self.db_conn1.id)
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect to step 2
        self.assertEqual(response.url, reverse('sync_jobs:create_step2'))
        
        # Check session data
        session = self.client.session
        self.assertEqual(session['sync_job_name'], 'Test API Job')
        self.assertEqual(session['sync_job_source_connection_type'], 'api')
        self.assertEqual(session['sync_job_source_api_connection_id'], str(self.api_conn.id))
        self.assertEqual(session['sync_job_target_connection_id'], str(self.db_conn1.id))
    
    def test_step1_validates_api_cannot_be_target(self):
        """Test Step 1 validates API cannot be target"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.post(reverse('sync_jobs:create_step1'), {
            'job_name': 'Test Job',
            'source_connection': str(self.db_conn1.id),
            'source_connection_type': 'database',
            'target_connection': str(self.api_conn.id)  # API as target - should fail
        })
        
        # Should show error (API connections are not in target list, but test validation)
        # The view should only show database connections for target
        self.assertNotEqual(response.status_code, 302)
    
    def test_step2_shows_modules_for_api_source(self):
        """Test Step 2 shows module selection for API source"""
        self.client.login(username='testuser', password='testpass123')
        
        # Set up session for API source
        session = self.client.session
        session['sync_job_name'] = 'Test API Job'
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.api_conn.id)
        session['sync_job_target_connection_id'] = str(self.db_conn1.id)
        session.save()
        
        response = self.client.get(reverse('sync_jobs:create_step2'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select Modules')
        self.assertContains(response, 'Leads')
        self.assertContains(response, 'Contacts')
        self.assertContains(response, 'Accounts')

    def test_step2_shows_projects_for_azure_devops_source(self):
        """Test Step 2 shows project selection label for Azure DevOps source"""
        self.client.login(username='testuser', password='testpass123')

        # Set up session for Azure DevOps API source
        session = self.client.session
        session['sync_job_name'] = 'Azure DevOps Job'
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.azure_conn.id)
        session['sync_job_target_connection_id'] = str(self.db_conn1.id)
        session.save()

        response = self.client.get(reverse('sync_jobs:create_step2'))

        self.assertEqual(response.status_code, 200)
        # Header and helper text mention projects
        self.assertContains(response, 'Select Projects to Sync')
        self.assertContains(response, 'Projects Available')
        # Projects from selected_modules are listed
        self.assertContains(response, 'ProjA')
        self.assertContains(response, 'ProjB')
    
    def test_step2_shows_tables_for_database_source(self):
        """Test Step 2 shows table selection for database source"""
        self.client.login(username='testuser', password='testpass123')
        
        # Set up session for database source
        session = self.client.session
        session['sync_job_name'] = 'Test DB Job'
        session['sync_job_source_connection_type'] = 'database'
        session['sync_job_source_connection_id'] = str(self.db_conn1.id)
        session['sync_job_target_connection_id'] = str(self.db_conn2.id)
        session.save()
        
        response = self.client.get(reverse('sync_jobs:create_step2'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select Tables')
    
    def test_step2_submit_with_modules(self):
        """Test Step 2 submit with module selection"""
        self.client.login(username='testuser', password='testpass123')
        
        # Set up session for API source
        session = self.client.session
        session['sync_job_name'] = 'Test API Job'
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.api_conn.id)
        session['sync_job_target_connection_id'] = str(self.db_conn1.id)
        session.save()
        
        response = self.client.post(reverse('sync_jobs:create_step2_submit'), {
            'selected_modules': ['Leads', 'Contacts']
        })
        
        # For API sources we now skip mapping and go directly to Step 4 (configure)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('sync_jobs:create_step4'))
        
        # Check session data
        session = self.client.session
        selected_tables = session['sync_job_selected_tables']
        self.assertEqual(len(selected_tables), 2)
        self.assertEqual(selected_tables[0]['schema_name'], 'api')
        self.assertEqual(selected_tables[0]['table_name'], 'Leads')
        self.assertEqual(selected_tables[1]['table_name'], 'Contacts')
    
    def test_step3_creates_job_with_api_source(self):
        """Test Step 3 creates sync job with API source"""
        self.client.login(username='testuser', password='testpass123')
        
        # Set up session for API source
        session = self.client.session
        session['sync_job_name'] = 'Test API Job'
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.api_conn.id)
        session['sync_job_target_connection_id'] = str(self.db_conn1.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'api', 'table_name': 'Leads'},
            {'schema_name': 'api', 'table_name': 'Contacts'}
        ]
        session.save()
        
        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {
                'sync_type': 'full',
                'schedule_type': 'once',
            },
        )
        
        self.assertEqual(response.status_code, 302)  # Redirect to job list
        
        # Verify job was created
        job = SyncJob.objects.get(name='Test API Job')
        self.assertEqual(job.source_connection_type, 'api')
        self.assertEqual(job.source_api_connection, self.api_conn)
        self.assertIsNone(job.source_connection)
        self.assertEqual(job.target_connection, self.db_conn1)
        
        # Verify SyncJobTable entries were created
        job_tables = job.tables.all()
        self.assertEqual(job_tables.count(), 2)
        
        leads_table = job_tables.get(table_name='Leads')
        self.assertEqual(leads_table.schema_name, 'api')
        
        contacts_table = job_tables.get(table_name='Contacts')
        self.assertEqual(contacts_table.schema_name, 'api')

    def test_step4_submit_saves_target_table_prefix_for_api_job(self):
        """Step 4 stores target_table_prefix when provided."""
        self.client.login(username='testuser', password='testpass123')

        session = self.client.session
        session['sync_job_name'] = 'Test API Prefix Job'
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.api_conn.id)
        session['sync_job_target_connection_id'] = str(self.db_conn1.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'api', 'table_name': 'Leads'}
        ]
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {
                'sync_type': 'full',
                'schedule_type': 'once',
                'target_table_prefix': 'POST',
            },
        )

        self.assertEqual(response.status_code, 302)
        job = SyncJob.objects.get(name='Test API Prefix Job')
        self.assertEqual(job.target_table_prefix, 'POST')

    def test_step4_submit_rejects_invalid_target_table_prefix(self):
        """Step 4 rejects invalid prefix characters."""
        self.client.login(username='testuser', password='testpass123')

        session = self.client.session
        session['sync_job_name'] = 'Test API Invalid Prefix Job'
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.api_conn.id)
        session['sync_job_target_connection_id'] = str(self.db_conn1.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'api', 'table_name': 'Leads'}
        ]
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {
                'sync_type': 'full',
                'schedule_type': 'once',
                'target_table_prefix': 'BAD-PREFIX',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SyncJob.objects.filter(name='Test API Invalid Prefix Job').exists())
        self.assertContains(response, 'Target table prefix may only contain letters, numbers, and underscores.')
    
    def test_step3_creates_apisyncstate_for_incremental(self):
        """Test Step 3 creates APISyncState for incremental sync"""
        self.client.login(username='testuser', password='testpass123')
        
        # Set up session for API source
        session = self.client.session
        session['sync_job_name'] = 'Test API Incremental Job'
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.api_conn.id)
        session['sync_job_target_connection_id'] = str(self.db_conn1.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'api', 'table_name': 'Leads'}
        ]
        session.save()
        
        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {
                'sync_type': 'incremental',
                'schedule_type': 'once',
            },
        )
        
        self.assertEqual(response.status_code, 302)
        
        # Verify job was created
        job = SyncJob.objects.get(name='Test API Incremental Job')
        self.assertEqual(job.sync_type, 'incremental')
        
        # Verify APISyncState was created
        sync_states = job.api_sync_states.all()
        self.assertEqual(sync_states.count(), 1)
        
        sync_state = sync_states.first()
        self.assertEqual(sync_state.module_name, 'Leads')
        self.assertIsNone(sync_state.last_sync_time)
        self.assertEqual(sync_state.records_synced, 0)
