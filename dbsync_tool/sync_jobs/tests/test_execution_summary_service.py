from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from connections.models import DatabaseConnection
from sync_jobs.models import SyncExecution, SyncExecutionLog, SyncJob
from sync_jobs.services.execution_summary_service import build_execution_summary


class ExecutionSummaryServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="summary_user",
            password="x",
            email="summary@example.com",
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
            name="job1",
            source_connection=self.source,
            source_connection_type="database",
            target_connection=self.target,
            sync_type="incremental",
            created_by=self.user,
            tenant=self.user,
        )

    def test_build_execution_summary_with_logs(self):
        execution = SyncExecution.objects.create(
            job=self.job,
            status="completed",
            started_at=timezone.now(),
            completed_at=timezone.now(),
            total_tables=2,
            completed_tables=1,
            total_rows_synced=20,
        )
        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name="api",
            table_name="a",
            status="completed",
            rows_fetched=20,
            rows_inserted=20,
            batch_number=1,
        )
        SyncExecutionLog.objects.create(
            execution=execution,
            schema_name="api",
            table_name="b",
            status="failed",
            rows_fetched=1,
            rows_inserted=0,
            batch_number=1,
            error_message="boom",
        )

        summary = build_execution_summary(execution)
        self.assertEqual(summary["job_name"], "job1")
        self.assertEqual(summary["total_rows_synced"], 20)
        self.assertEqual(summary["tables_changed"], 1)
        self.assertEqual(summary["failed_tables"], 1)
        self.assertEqual(summary["completed_tables"], 1)
        self.assertTrue(summary["has_table_logs"])
        self.assertIn("->", summary["migration_path"])

    def test_build_execution_summary_without_logs(self):
        execution = SyncExecution.objects.create(
            job=self.job,
            status="failed",
            total_tables=3,
            completed_tables=0,
            total_rows_synced=0,
        )
        summary = build_execution_summary(execution)
        self.assertFalse(summary["has_table_logs"])
        self.assertEqual(summary["tables_changed"], 0)
        self.assertIn("No table logs available", summary["notes"][0])

