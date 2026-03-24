from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from connections.models import FileSourceConnection
from sync_jobs.services.flat_file_preview_service import build_flat_file_preview


class FlatFilePreviewServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='svc_user', password='pass123')

    @override_settings(FILE_SYNC_ROOT='')
    def test_preview_raises_when_root_not_configured(self):
        src = FileSourceConnection(
            name='CSV',
            relative_path='orders.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.user,
            created_by=self.user,
        )
        with self.assertRaises(Exception):
            build_flat_file_preview(src)

    def test_preview_reads_columns_and_rows(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / 'orders.csv'
            file_path.write_text('id,name\n1,Alice\n2,Bob\n', encoding='utf-8')
            src = FileSourceConnection(
                name='CSV',
                relative_path='orders.csv',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.user,
                created_by=self.user,
            )
            with override_settings(FILE_SYNC_ROOT=str(root)):
                payload = build_flat_file_preview(src)
            self.assertEqual(payload['columns'], ['id', 'name'])
            self.assertEqual(len(payload['rows']), 2)
            self.assertIn('default_table_name', payload)

