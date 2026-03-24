from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection, FileSourceConnection


class CreateJobStep2FlatFileTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='flat_user', password='pass123')
        UserProfile.objects.update_or_create(
            user=self.user, defaults={'role': Role.ADMIN, 'tenant': self.user}
        )
        self.client.force_login(self.user)
        self.target_db = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='u',
            password='p',
            database_name='d',
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )
        self.file_source = FileSourceConnection.objects.create(
            name='CSV Source',
            relative_path='orders.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )

    def _seed_step1_session(self):
        session = self.client.session
        session['sync_job_name'] = 'Flat Job'
        session['sync_job_source_connection_type'] = 'flat_file'
        session['sync_job_source_file_connection_id'] = str(self.file_source.id)
        session['sync_job_target_connection_id'] = str(self.target_db.id)
        session.save()

    def test_step2_flat_file_renders_preview_mode(self):
        self._seed_step1_session()
        response = self.client.get(reverse('sync_jobs:create_step2'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flat File Preview')

    def test_preview_endpoint_returns_columns_rows(self):
        self._seed_step1_session()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'orders.csv').write_text('id,name\n1,Alice\n', encoding='utf-8')
            with override_settings(FILE_SYNC_ROOT=str(root)):
                response = self.client.get(reverse('sync_jobs:create_step2_flat_file_preview'))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['columns'], ['id', 'name'])

    def test_step2_flat_file_submit_persists_selected_table_payload(self):
        self._seed_step1_session()
        response = self.client.post(
            reverse('sync_jobs:create_step2_submit'),
            {'target_table_name': 'Orders Import'},
        )
        self.assertRedirects(response, reverse('sync_jobs:create_step3'), fetch_redirect_response=False)
        tables = self.client.session.get('sync_job_selected_tables', [])
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]['schema_name'], 'file')
        self.assertEqual(tables[0]['table_name'], 'orders_import')

