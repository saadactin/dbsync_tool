from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection, FileSourceConnection


class CreateJobStep3FlatFileMappingTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='flat_step3_user', password='pass123')
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

    def _seed_step3_session(self):
        session = self.client.session
        session['sync_job_name'] = 'Flat Job'
        session['sync_job_source_connection_type'] = 'flat_file'
        session['sync_job_source_file_connection_id'] = str(self.file_source.id)
        session['sync_job_target_connection_id'] = str(self.target_db.id)
        session['sync_job_selected_tables'] = [{'schema_name': 'file', 'table_name': 'orders_import'}]
        session.save()

    def test_step3_flat_file_renders_mapping_ui(self):
        self._seed_step3_session()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'orders.csv').write_text('Order ID,Customer Name\n1,Alice\n', encoding='utf-8')
            with override_settings(FILE_SYNC_ROOT=str(root)):
                response = self.client.get(reverse('sync_jobs:create_step3'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flat file')
        self.assertContains(response, 'Order ID')

    def test_step3_flat_file_missing_session_redirects(self):
        response = self.client.get(reverse('sync_jobs:create_step3'))
        self.assertRedirects(response, reverse('sync_jobs:create_step1'))

    def test_step3_flat_file_submit_persists_name_overrides(self):
        self._seed_step3_session()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'orders.csv').write_text('Order ID,Customer Name\n1,Alice\n', encoding='utf-8')
            with override_settings(FILE_SYNC_ROOT=str(root)):
                render_resp = self.client.get(reverse('sync_jobs:create_step3'))
                self.assertEqual(render_resp.status_code, 200)
                response = self.client.post(
                    reverse('sync_jobs:create_step3_submit'),
                    {
                        'override_colname_file.orders_import.Order ID': 'order_id',
                        'override_colname_file.orders_import.Customer Name': 'customer_name',
                    },
                )
        self.assertRedirects(response, reverse('sync_jobs:create_step4'), fetch_redirect_response=False)
        overrides = self.client.session.get('sync_job_column_name_overrides', {})
        self.assertIn('file.orders_import', overrides)
        self.assertEqual(overrides['file.orders_import']['order id'], 'order_id')
        self.assertEqual(overrides['file.orders_import']['customer name'], 'customer_name')

    def test_step3_flat_file_duplicate_target_names_rejected(self):
        self._seed_step3_session()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'orders.csv').write_text('Order ID,Customer Name\n1,Alice\n', encoding='utf-8')
            with override_settings(FILE_SYNC_ROOT=str(root)):
                self.client.get(reverse('sync_jobs:create_step3'))
                response = self.client.post(
                    reverse('sync_jobs:create_step3_submit'),
                    {
                        'override_colname_file.orders_import.Order ID': 'dup_name',
                        'override_colname_file.orders_import.Customer Name': 'dup_name',
                    },
                )
        self.assertRedirects(response, reverse('sync_jobs:create_step3'), fetch_redirect_response=False)
