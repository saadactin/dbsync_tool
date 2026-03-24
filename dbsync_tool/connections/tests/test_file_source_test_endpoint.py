import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import FileSourceConnection


class FileSourceTestEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='tenantadmin', password='testpass123', email='admin@example.com'
        )
        self.other_tenant = User.objects.create_user(
            username='tenant2', password='testpass123', email='tenant2@example.com'
        )
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={'role': Role.ADMIN, 'tenant': self.admin}
        )
        UserProfile.objects.update_or_create(
            user=self.other_tenant, defaults={'role': Role.ADMIN, 'tenant': self.other_tenant}
        )

    def test_success_response_contains_latency_and_details(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / 'sample.csv'
            csv_path.write_text('id,name\n1,Alice\n2,Bob\n', encoding='utf-8')
            source = FileSourceConnection.objects.create(
                name='CSV Source',
                relative_path='sample.csv',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.admin,
                created_by=self.admin,
            )
            self.client.login(username='tenantadmin', password='testpass123')
            with override_settings(FILE_SYNC_ROOT=tmp):
                response = self.client.post(reverse('connections:file_source_test', args=[source.id]))
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertTrue(data['success'])
            self.assertIn('latency_ms', data)
            self.assertGreaterEqual(data['latency_ms'], 0)
            self.assertIn('details', data)
            self.assertEqual(data['details']['name'], 'CSV Source')

    def test_missing_file_returns_success_false(self):
        with TemporaryDirectory() as tmp:
            source = FileSourceConnection.objects.create(
                name='Missing Source',
                relative_path='missing.csv',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.admin,
                created_by=self.admin,
            )
            self.client.login(username='tenantadmin', password='testpass123')
            with override_settings(FILE_SYNC_ROOT=tmp):
                response = self.client.post(reverse('connections:file_source_test', args=[source.id]))
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertFalse(data['success'])
            self.assertIn('not found', data['message'].lower())

    def test_traversal_path_returns_400(self):
        with TemporaryDirectory() as tmp:
            source = FileSourceConnection.objects.create(
                name='Traversal Source',
                relative_path='safe.csv',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.admin,
                created_by=self.admin,
            )
            source.relative_path = '../escape.csv'
            source.save(update_fields=['relative_path'])
            self.client.login(username='tenantadmin', password='testpass123')
            with override_settings(FILE_SYNC_ROOT=tmp):
                response = self.client.post(reverse('connections:file_source_test', args=[source.id]))
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.content)
            self.assertFalse(data['success'])

    def test_bad_encoding_returns_success_false(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / 'bad.csv'
            csv_path.write_bytes('id,name\n1,Alice\n'.encode('utf-16'))
            source = FileSourceConnection.objects.create(
                name='Bad Encoding Source',
                relative_path='bad.csv',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.admin,
                created_by=self.admin,
            )
            self.client.login(username='tenantadmin', password='testpass123')
            with override_settings(FILE_SYNC_ROOT=tmp):
                response = self.client.post(reverse('connections:file_source_test', args=[source.id]))
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertFalse(data['success'])
            self.assertIn('encoding', data['message'].lower())

    def test_cross_tenant_request_gets_404(self):
        with TemporaryDirectory() as tmp:
            source = FileSourceConnection.objects.create(
                name='Other Tenant Source',
                relative_path='sample.csv',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.other_tenant,
                created_by=self.other_tenant,
            )
            self.client.login(username='tenantadmin', password='testpass123')
            with override_settings(FILE_SYNC_ROOT=tmp):
                response = self.client.post(reverse('connections:file_source_test', args=[source.id]))
            self.assertEqual(response.status_code, 404)
