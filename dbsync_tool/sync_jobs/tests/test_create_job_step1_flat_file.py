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

    def test_flat_file_incremental_sync_rejected(self):
        session = self.client.session
        session['sync_job_name'] = 'Flat Incremental'
        session['sync_job_source_connection_type'] = 'flat_file'
        session['sync_job_source_file_connection_id'] = str(self.file_source.id)
        session['sync_job_target_connection_id'] = str(self.target_db.id)
        session['sync_job_selected_tables'] = [{'schema_name': 'file', 'table_name': 'orders'}]
        session.save()

        response = self.client.post(
            reverse('sync_jobs:create_step4_submit'),
            {'sync_type': 'incremental', 'schedule_type': 'once'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flat-file source currently supports full sync only.')

