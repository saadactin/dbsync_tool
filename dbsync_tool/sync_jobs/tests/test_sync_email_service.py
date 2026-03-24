from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from connections.models import DatabaseConnection
from sync_jobs.models import SyncExecution, SyncExecutionLog, SyncJob
from sync_jobs.services.sync_email_service import (
    resolve_summary_recipients,
    send_execution_summary_email,
)


class SyncEmailServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="email_user",
            password="x",
            email="creator@example.com",
        )
        self.source = DatabaseConnection.objects.create(
            name="src",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="u",
            password="p",
            database_name="db_src",
            created_by=self.user,
            tenant=self.user,
        )
        self.target = DatabaseConnection.objects.create(
            name="dst",
            db_type="clickhouse",
            host="ch.local",
            port=8123,
            username="u",
            password="p",
            database_name="db_dst",
            created_by=self.user,
            tenant=self.user,
        )
        self.job = SyncJob.objects.create(
            name="job_email",
            source_connection=self.source,
            source_connection_type="database",
            target_connection=self.target,
            sync_type="full",
            created_by=self.user,
            tenant=self.user,
        )
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status="completed",
            total_tables=1,
            completed_tables=1,
            total_rows_synced=16,
        )
        SyncExecutionLog.objects.create(
            execution=self.execution,
            schema_name="api",
            table_name="Embedded",
            status="completed",
            rows_fetched=16,
            rows_inserted=16,
            batch_number=1,
        )

    @override_settings(
        ADMIN_EMAILS=["saadpractice4@gmail.com", "creator@example.com", "bad-email"]
    )
    def test_resolve_recipients_admins_plus_creator_dedup(self):
        recipients = resolve_summary_recipients(self.execution)
        self.assertEqual(
            recipients,
            ["saadpractice4@gmail.com", "creator@example.com"],
        )

    @override_settings(ADMIN_EMAILS=["saadpractice4@gmail.com"])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_send_execution_summary_email_success(self, mock_send_mail):
        result = send_execution_summary_email(self.execution)
        self.assertTrue(result["sent"])
        mock_send_mail.assert_called_once()
        kwargs = mock_send_mail.call_args.kwargs
        self.assertIn("[DB Sync] Completed", kwargs["subject"])
        self.assertIn("creator@example.com", kwargs["recipient_list"])
        self.assertIn("saadpractice4@gmail.com", kwargs["recipient_list"])

    @override_settings(ADMIN_EMAILS=["saadpractice4@gmail.com"])
    @patch("sync_jobs.services.sync_email_service.send_mail")
    def test_send_execution_summary_email_catches_errors(self, mock_send_mail):
        mock_send_mail.side_effect = RuntimeError("smtp down")
        result = send_execution_summary_email(self.execution)
        self.assertFalse(result["sent"])
        self.assertIn("smtp down", result["error_message"])

