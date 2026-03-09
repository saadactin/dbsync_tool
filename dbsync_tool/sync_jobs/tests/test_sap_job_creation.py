"""
Tests for SAP job creation workflow (Step 2 view/submit, Step 3 submit).
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, APISyncState
from accounts.models import UserProfile, Role


class SAPJobCreationTests(TestCase):
    """Test SAP endpoint selection and job creation (Step 2 and Step 3)."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN, 'tenant': self.user}
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
            tenant=self.user
        )
        self.sap_conn = APIConnection.objects.create(
            name='SAP B1 API',
            api_type='sap_b1',
            sap_base_url='https://sap.example.com/b1s/v2',
            sap_username={'UserName': 'U', 'CompanyDB': 'DB'},
            sap_password='encrypted',
            sap_endpoints=[
                {'name': 'Journal Entry', 'endpoint': 'JournalEntries', 'id_field': 'JdtNum'},
                {'name': 'Items', 'endpoint': 'Items', 'id_field': 'ItemCode'},
            ],
            tenant=self.user,
            created_by=self.user
        )

    def _session_step2_sap(self):
        """Set session as if Step 1 was completed with SAP API source."""
        session = self.client.session
        session['sync_job_source_connection_type'] = 'api'
        session['sync_job_source_api_connection_id'] = str(self.sap_conn.id)
        session['sync_job_target_connection_id'] = str(self.target_conn.id)
        session['sync_job_name'] = 'My SAP Job'
        session.save()

    def test_step2_view_sap_shows_endpoints(self):
        """Step 2 with SAP source shows available_endpoints and is_sap=True."""
        self.client.login(username='testuser', password='testpass123')
        self._session_step2_sap()
        response = self.client.get(reverse('sync_jobs:create_step2'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get('is_sap'))
        available = response.context.get('available_endpoints', [])
        self.assertGreaterEqual(len(available), 2)
        endpoints = [e.get('endpoint') if isinstance(e, dict) else e for e in available]
        self.assertIn('JournalEntries', endpoints)
        self.assertIn('Items', endpoints)

    def test_step2_submit_sap_stores_sap_api_tables(self):
        """Step 2 submit with selected_endpoints stores schema_name=sap_api, table_name=endpoint."""
        self.client.login(username='testuser', password='testpass123')
        self._session_step2_sap()
        response = self.client.post(
            reverse('sync_jobs:create_step2_submit'),
            {'selected_endpoints': ['JournalEntries', 'Items']},
            follow=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('sync_jobs:create_step3'), response.get('Location', ''))
        tables = self.client.session.get('sync_job_selected_tables', [])
        self.assertEqual(len(tables), 2)
        schemas = {t['schema_name'] for t in tables}
        names = {t['table_name'] for t in tables}
        self.assertEqual(schemas, {'sap_api'})
        self.assertEqual(names, {'JournalEntries', 'Items'})

    def test_step2_submit_sap_no_selection_redirects_back(self):
        """Step 2 submit with no selected_endpoints redirects to step 2 with error."""
        self.client.login(username='testuser', password='testpass123')
        self._session_step2_sap()
        response = self.client.post(
            reverse('sync_jobs:create_step2_submit'),
            {'selected_endpoints': []},
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        tables = self.client.session.get('sync_job_selected_tables')
        self.assertIsNone(tables)
        from django.contrib.messages import get_messages
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any('at least one endpoint' in str(m).lower() for m in messages))

    def test_step3_submit_sap_creates_job_and_tables(self):
        """Step 3 submit with SAP session creates SyncJob and SyncJobTable with sap_api + endpoint names."""
        self.client.login(username='testuser', password='testpass123')
        self._session_step2_sap()
        self.client.post(
            reverse('sync_jobs:create_step2_submit'),
            {'selected_endpoints': ['JournalEntries', 'Items']}
        )
        session = self.client.session
        session['sync_job_selected_tables'] = [
            {'schema_name': 'sap_api', 'table_name': 'JournalEntries'},
            {'schema_name': 'sap_api', 'table_name': 'Items'},
        ]
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step3_submit'),
            {
                'sync_type': 'full',
                'schedule_type': 'once',
                'start_datetime': '',
            },
            follow=False
        )
        self.assertEqual(response.status_code, 302)
        job = SyncJob.objects.filter(
            source_api_connection=self.sap_conn,
            source_connection_type='api',
            name='My SAP Job'
        ).first()
        self.assertIsNotNone(job)
        tables = list(SyncJobTable.objects.filter(job=job).values_list('schema_name', 'table_name'))
        self.assertEqual(len(tables), 2)
        self.assertIn(('sap_api', 'JournalEntries'), tables)
        self.assertIn(('sap_api', 'Items'), tables)

    def test_step3_submit_sap_incremental_creates_api_sync_state(self):
        """Step 3 submit with SAP + incremental creates APISyncState per endpoint."""
        self.client.login(username='testuser', password='testpass123')
        self._session_step2_sap()
        self.client.post(
            reverse('sync_jobs:create_step2_submit'),
            {'selected_endpoints': ['JournalEntries']}
        )
        session = self.client.session
        session['sync_job_selected_tables'] = [{'schema_name': 'sap_api', 'table_name': 'JournalEntries'}]
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step3_submit'),
            {
                'sync_type': 'incremental',
                'schedule_type': 'once',
                'start_datetime': '',
                'incremental_column_sap_api.JournalEntries': 'Modified_Time',
            },
            follow=False
        )
        self.assertEqual(response.status_code, 302)
        job = SyncJob.objects.filter(
            source_api_connection=self.sap_conn,
            source_connection_type='api'
        ).order_by('-created_at').first()
        self.assertIsNotNone(job, 'SyncJob should be created after step 3 submit')
        states = APISyncState.objects.filter(job=job)
        self.assertEqual(states.count(), 1)
        self.assertEqual(states.first().module_name, 'JournalEntries')
