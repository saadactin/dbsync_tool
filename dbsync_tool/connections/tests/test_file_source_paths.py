from pathlib import Path
import tempfile

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings

from connections.file_source_paths import get_file_sync_root, resolve_safe_source_path
from connections.models import FileSourceConnection


class FileSourcePathResolverTests(TestCase):
    def test_resolve_valid_relative_path_under_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(FILE_SYNC_ROOT=tmp_dir):
                resolved = resolve_safe_source_path('nested/data.csv')
                self.assertTrue(str(resolved).startswith(str(Path(tmp_dir).resolve())))
                self.assertEqual(resolved.name, 'data.csv')

    def test_resolve_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(FILE_SYNC_ROOT=tmp_dir):
                with self.assertRaises(ValidationError):
                    resolve_safe_source_path('../escape.csv')

    def test_resolve_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(FILE_SYNC_ROOT=tmp_dir):
                absolute = str(Path(tmp_dir).resolve() / 'x.csv')
                with self.assertRaises(ValidationError):
                    resolve_safe_source_path(absolute)

    @override_settings(FILE_SYNC_ROOT='')
    def test_missing_root_raises_configuration_error(self):
        with self.assertRaises(ValidationError):
            get_file_sync_root()

    def test_empty_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(FILE_SYNC_ROOT=tmp_dir):
                with self.assertRaises(ValidationError):
                    resolve_safe_source_path('   ')


class FileSourceConnectionModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='file_user',
            email='file_user@example.com',
            password='testpass123',
        )

    def test_valid_file_source_connection_saves(self):
        conn = FileSourceConnection.objects.create(
            name='CSV Source',
            relative_path='imports/customers.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.user,
            created_by=self.user,
            is_active=True,
        )
        self.assertIsNotNone(conn.id)
        self.assertEqual(conn.relative_path, 'imports/customers.csv')

    def test_whitespace_path_rejected(self):
        conn = FileSourceConnection(
            name='Invalid Source',
            relative_path='   ',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.user,
            created_by=self.user,
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            conn.full_clean()

    def test_invalid_delimiter_rejected(self):
        conn = FileSourceConnection(
            name='Invalid Delimiter',
            relative_path='imports/items.csv',
            delimiter='||',
            encoding='utf-8',
            has_header=True,
            tenant=self.user,
            created_by=self.user,
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            conn.full_clean()

    def test_duplicate_name_per_tenant_rejected(self):
        FileSourceConnection.objects.create(
            name='Dup Source',
            relative_path='a.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.user,
            created_by=self.user,
            is_active=True,
        )
        with self.assertRaises(IntegrityError):
            FileSourceConnection.objects.create(
                name='Dup Source',
                relative_path='b.csv',
                delimiter=',',
                encoding='utf-8',
                has_header=True,
                tenant=self.user,
                created_by=self.user,
                is_active=True,
            )
