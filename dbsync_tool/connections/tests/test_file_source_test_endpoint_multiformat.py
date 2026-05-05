import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import FileSourceConnection


class FileSourceTestEndpointMultiFormatTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='tenantadminmf', password='testpass123', email='adminmf@example.com'
        )
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={'role': Role.ADMIN, 'tenant': self.admin}
        )
        self.client.login(username='tenantadminmf', password='testpass123')

    def test_json_file_source_test_success(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sample.json').write_text('[{"id":1},{"id":2}]', encoding='utf-8')
            source = FileSourceConnection.objects.create(
                name='JSON Source',
                relative_path='sample.json',
                file_format='json',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.admin,
                created_by=self.admin,
            )
            with override_settings(FILE_SYNC_ROOT=tmp):
                response = self.client.post(reverse('connections:file_source_test', args=[source.id]))
            self.assertEqual(response.status_code, 200)
            body = json.loads(response.content)
            self.assertTrue(body['success'])
