from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from connections.models import FileSourceConnection
from sync_jobs.services.flat_file_preview_service import build_flat_file_preview


class FlatFilePreviewServiceMultiFormatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='svc_multi', password='pass123')

    def test_preview_for_json_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'orders.json').write_text(
                '[{"id":1,"customer":{"name":"A"}},{"id":2,"customer":{"name":"B"}}]',
                encoding='utf-8',
            )
            src = FileSourceConnection(
                name='JSON',
                relative_path='orders.json',
                file_format='json',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                record_path='',
                nested_strategy='flatten',
                flatten_separator='.',
                tenant=self.user,
                created_by=self.user,
            )
            with override_settings(FILE_SYNC_ROOT=str(root)):
                payload = build_flat_file_preview(src)
            self.assertEqual(payload['file_stats']['file_format'], 'json')
            self.assertIn('customer.name', payload['columns'])
            self.assertEqual(len(payload['rows']), 2)

    def test_preview_for_xml_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'items.xml').write_text(
                "<root><items><item id='1'><name>A</name></item></items></root>",
                encoding='utf-8',
            )
            src = FileSourceConnection(
                name='XML',
                relative_path='items.xml',
                file_format='xml',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                record_path='/root/items/item',
                nested_strategy='flatten',
                flatten_separator='.',
                tenant=self.user,
                created_by=self.user,
            )
            with override_settings(FILE_SYNC_ROOT=str(root)):
                payload = build_flat_file_preview(src)
            self.assertEqual(payload['file_stats']['file_format'], 'xml')
            self.assertIn('@id', payload['columns'])
