from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection, FileSourceConnection


class CreateJobStep1FlatFileTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin1', password='pass123')
        UserProfile.objects.update_or_create(
            user=self.user, defaults={'role': Role.ADMIN, 'tenant': self.user}
        )
        self.other = User.objects.create_user(username='admin2', password='pass123')
        UserProfile.objects.update_or_create(
            user=self.other, defaults={'role': Role.ADMIN, 'tenant': self.other}
        )

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
        self.target_db.last_tested_at = self.target_db.created_at
        self.target_db.save(update_fields=['last_tested_at'])

        self.file_source = FileSourceConnection.objects.create(
            name='CSV Source',
            relative_path='daily/orders.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )
        self.other_file_source = FileSourceConnection.objects.create(
            name='Other CSV Source',
            relative_path='daily/other.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            is_active=True,
            created_by=self.other,
            tenant=self.other,
        )
        self.client.force_login(self.user)

    def test_step1_renders_flat_file_option(self):
        response = self.client.get(reverse('sync_jobs:create_step1'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flat File Source')

    def test_step1_flat_file_success_redirects_to_step2(self):
        response = self.client.post(
            reverse('sync_jobs:create_step1'),
            {
                'job_name': 'Flat Import Job',
                'source_connection_type': 'flat_file',
                'source_file_connection': str(self.file_source.id),
                'target_connection': str(self.target_db.id),
            },
            follow=True,
        )
        self.assertRedirects(response, reverse('sync_jobs:create_step2'))
        session = self.client.session
        self.assertEqual(session.get('sync_job_source_connection_type'), 'flat_file')
        self.assertEqual(session.get('sync_job_source_file_connection_id'), str(self.file_source.id))

    def test_step1_flat_file_missing_source_id_stays_on_step1(self):
        response = self.client.post(
            reverse('sync_jobs:create_step1'),
            {
                'job_name': 'Flat Import Job',
                'source_connection_type': 'flat_file',
                'target_connection': str(self.target_db.id),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'File source is required.')

    def test_step1_flat_file_cross_tenant_blocked(self):
        response = self.client.post(
            reverse('sync_jobs:create_step1'),
            {
                'job_name': 'Flat Import Job',
                'source_connection_type': 'flat_file',
                'source_file_connection': str(self.other_file_source.id),
                'target_connection': str(self.target_db.id),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Selected connection not found or inactive.')

    def test_flat_file_incremental_sync_rejected_without_stable_key(self):
        session = self.client.session
        session['sync_job_name'] = 'Flat Incremental'
        session['sync_job_source_connection_type'] = 'flat_file'
        session['sync_job_source_file_connection_id'] = str(self.file_source.id)
        session['sync_job_target_connection_id'] = str(self.target_db.id)
        session['sync_job_selected_tables'] = [{'schema_name': 'file', 'table_name': 'orders'}]
        session['sync_job_protected_columns'] = {}
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {'sync_type': 'incremental', 'schedule_type': 'once'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'select at least one Protected column to use as stable upsert key',
        )

    def test_flat_file_incremental_sync_accepts_with_stable_key(self):
        session = self.client.session
        session['sync_job_name'] = 'Flat Incremental'
        session['sync_job_source_connection_type'] = 'flat_file'
        session['sync_job_source_file_connection_id'] = str(self.file_source.id)
        session['sync_job_target_connection_id'] = str(self.target_db.id)
        session['sync_job_selected_tables'] = [{'schema_name': 'file', 'table_name': 'orders'}]
        session['sync_job_protected_columns'] = {'file.orders': ['Order ID']}
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {'sync_type': 'incremental', 'schedule_type': 'once'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'created successfully')

    def test_flat_file_hybrid_fields_persist_to_syncjobtable(self):
        session = self.client.session
        session['sync_job_name'] = 'Flat Incremental Hybrid'
        session['sync_job_source_connection_type'] = 'flat_file'
        session['sync_job_source_file_connection_id'] = str(self.file_source.id)
        session['sync_job_target_connection_id'] = str(self.target_db.id)
        session['sync_job_selected_tables'] = [{'schema_name': 'file', 'table_name': 'orders'}]
        session['sync_job_protected_columns'] = {'file.orders': ['Order ID']}
        session['sync_job_flat_file_headers'] = ['Order ID', 'Customer Name', 'Amount']
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {
                'sync_type': 'incremental',
                'schedule_type': 'once',
                'flat_file_incremental_mode_file.orders': 'hybrid_hash_control',
                'flat_file_hash_algorithm_file.orders': 'sha256',
                'flat_file_hash_columns_file.orders': 'Order ID, Amount',
                'flat_file_allow_hash_only_without_key_file.orders': '1',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'created successfully')

        from sync_jobs.models import SyncJobTable

        table = SyncJobTable.objects.filter(job__name='Flat Incremental Hybrid').first()
        self.assertIsNotNone(table)
        self.assertEqual(table.flat_file_incremental_mode, 'hybrid_hash_control')
        self.assertEqual(table.flat_file_hash_algorithm, 'sha256')
        self.assertEqual(table.flat_file_hash_columns, ['Order ID', 'Amount'])
        self.assertFalse(table.flat_file_allow_hash_only_without_key)

