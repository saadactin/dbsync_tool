from django.contrib.auth.models import User
from django.test import TestCase

from connections.forms import FileSourceConnectionForm


class FileSourceConnectionFormMultiFormatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tenantadmin2',
            password='testpass123',
            email='tenantadmin2@example.com',
        )

    def test_xml_requires_record_path(self):
        form = FileSourceConnectionForm(
            data={
                'name': 'XML Files',
                'relative_path': 'imports/customers.xml',
                'file_format': 'xml',
                'delimiter': ',',
                'encoding': 'utf-8',
                'record_path': '',
                'nested_strategy': 'flatten',
                'flatten_separator': '.',
                'has_header': True,
                'is_active': True,
            },
            tenant=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('record_path', form.errors)

    def test_json_does_not_require_delimiter(self):
        form = FileSourceConnectionForm(
            data={
                'name': 'JSON Files',
                'relative_path': 'imports/customers.json',
                'file_format': 'json',
                'delimiter': '',
                'encoding': 'utf-8',
                'record_path': 'data.items',
                'nested_strategy': 'json_blob',
                'flatten_separator': '.',
                'has_header': True,
                'is_active': True,
            },
            tenant=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
