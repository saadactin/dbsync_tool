from django.contrib.auth.models import User
from django.test import TestCase

from connections.forms import FileSourceConnectionForm
from connections.models import FileSourceConnection


class FileSourceConnectionFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tenantadmin',
            password='testpass123',
            email='tenantadmin@example.com',
        )

    def test_valid_form_data(self):
        form = FileSourceConnectionForm(
            data={
                'name': 'CSV Files',
                'relative_path': 'imports/customers.csv',
                'delimiter': ',',
                'encoding': 'utf-8',
                'has_header': True,
                'is_active': True,
            },
            tenant=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_delimiter_too_long_rejected(self):
        form = FileSourceConnectionForm(
            data={
                'name': 'CSV Files',
                'relative_path': 'imports/customers.csv',
                'delimiter': '||',
                'encoding': 'utf-8',
                'has_header': True,
                'is_active': True,
            },
            tenant=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('delimiter', form.errors)

    def test_whitespace_relative_path_rejected(self):
        form = FileSourceConnectionForm(
            data={
                'name': 'CSV Files',
                'relative_path': '   ',
                'delimiter': ',',
                'encoding': 'utf-8',
                'has_header': True,
                'is_active': True,
            },
            tenant=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('relative_path', form.errors)

    def test_duplicate_name_per_tenant_rejected(self):
        FileSourceConnection.objects.create(
            name='CSV Files',
            relative_path='imports/first.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.user,
            created_by=self.user,
        )
        form = FileSourceConnectionForm(
            data={
                'name': 'CSV Files',
                'relative_path': 'imports/second.csv',
                'delimiter': ',',
                'encoding': 'utf-8',
                'has_header': True,
                'is_active': True,
            },
            tenant=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
