from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from connections.models import DatabaseConnection
from sync_engine.executor import SyncExecutor
from sync_jobs.models import SyncExecution, SyncJob


class _FakeConnector:
    def connect(self):
        return None

    def close(self):
        return None


class ExecutorEmailNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="exec_user",
            password="x",
            email="exec@example.com",
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
            name="exec_job",
            source_connection=self.source,
            source_connection_type="database",
            target_connection=self.target,
            sync_type="full",
            created_by=self.user,
            tenant=self.user,
        )

    @patch("sync_engine.executor.FullSyncExecutor")
    @patch.object(SyncExecutor, "_get_connector_with_retry")
    @patch.object(SyncExecutor, "_send_summary_email")
    def test_execute_sends_summary_once_on_success(
        self, mock_send_summary, mock_get_connector, mock_full_executor
    ):
        mock_get_connector.return_value = _FakeConnector()
        mock_full_executor.return_value.execute.return_value = None

        executor = SyncExecutor(self.job)
        executor.execute()

        self.assertEqual(mock_send_summary.call_count, 1)
        execution = SyncExecution.objects.filter(job=self.job).latest("started_at")
        self.assertEqual(execution.status, "completed")

    @patch("sync_engine.executor.FullSyncExecutor")
    @patch.object(SyncExecutor, "_get_connector_with_retry")
    @patch.object(SyncExecutor, "_send_summary_email")
    def test_execute_sends_summary_once_on_failed_status(
        self, mock_send_summary, mock_get_connector, mock_full_executor
    ):
        mock_get_connector.return_value = _FakeConnector()

        def _mark_failed():
            execution = SyncExecution.objects.filter(job=self.job).latest("started_at")
            execution.status = "failed"
            execution.error_message = "table failed"
            execution.save(update_fields=["status", "error_message"])

        mock_full_executor.return_value.execute.side_effect = _mark_failed

        executor = SyncExecutor(self.job)
        executor.execute()

        self.assertEqual(mock_send_summary.call_count, 1)
        execution = SyncExecution.objects.filter(job=self.job).latest("started_at")
        self.assertEqual(execution.status, "failed")

