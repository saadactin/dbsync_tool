from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from connections.models import APIConnection, DatabaseConnection, FileSourceConnection
from sync_jobs.models import SyncJob


class SyncJobFlatFileValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='sync_user',
            email='sync_user@example.com',
            password='testpass123',
        )
        self.source_db = DatabaseConnection.objects.create(
            name='Source DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='db_user',
            password='db_pass',
            database_name='source_db',
            created_by=self.user,
            tenant=self.user,
        )
        self.target_db = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='db_user',
            password='db_pass',
            database_name='target_db',
            created_by=self.user,
            tenant=self.user,
        )
        self.api_conn = APIConnection.objects.create(
            name='Zoho Source',
            api_type='zoho_crm',
            client_id='cid',
            client_secret='csecret',
            refresh_token='rtoken',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            tenant=self.user,
            created_by=self.user,
        )
        self.file_conn = FileSourceConnection.objects.create(
            name='CSV Source',
            relative_path='imports/orders.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.user,
            created_by=self.user,
        )

    def test_flat_file_source_valid_when_only_file_fk_set(self):
        job = SyncJob(
            name='Flat File Job',
            source_connection_type='flat_file',
            source_file_connection=self.file_conn,
            target_connection=self.target_db,
            sync_type='full',
            created_by=self.user,
            tenant=self.user,
        )
        job.full_clean()  # should not raise

    def test_flat_file_source_invalid_when_db_fk_set(self):
        job = SyncJob(
            name='Invalid Flat File Job DB',
            source_connection_type='flat_file',
            source_file_connection=self.file_conn,
            source_connection=self.source_db,
            target_connection=self.target_db,
            sync_type='full',
            created_by=self.user,
            tenant=self.user,
        )
        with self.assertRaises(ValidationError):
            job.full_clean()

    def test_flat_file_source_invalid_when_api_fk_set(self):
        job = SyncJob(
            name='Invalid Flat File Job API',
            source_connection_type='flat_file',
            source_file_connection=self.file_conn,
            source_api_connection=self.api_conn,
            target_connection=self.target_db,
            sync_type='full',
            created_by=self.user,
            tenant=self.user,
        )
        with self.assertRaises(ValidationError):
            job.full_clean()

    def test_existing_database_source_still_valid(self):
        job = SyncJob(
            name='DB Job',
            source_connection_type='database',
            source_connection=self.source_db,
            target_connection=self.target_db,
            sync_type='full',
            created_by=self.user,
            tenant=self.user,
        )
        job.full_clean()  # should not raise

    def test_existing_api_source_still_valid(self):
        job = SyncJob(
            name='API Job',
            source_connection_type='api',
            source_api_connection=self.api_conn,
            target_connection=self.target_db,
            sync_type='full',
            created_by=self.user,
            tenant=self.user,
        )
        job.full_clean()  # should not raise
