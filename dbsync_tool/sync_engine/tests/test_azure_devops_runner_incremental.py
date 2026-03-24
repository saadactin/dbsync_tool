"""
Tests for AzureDevOpsRunner incremental/full script selection and environment.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from unittest.mock import patch, Mock

from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncExecution, SyncJobTable, SyncExecutionLog
from sync_engine.azure_devops_runner import (
    run_azure_devops_sync,
    _populate_execution_logs_from_stdout,
)


class AzureDevOpsRunnerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="runneruser",
            email="runner@example.com",
            password="testpass123",
        )

        self.db_conn = DatabaseConnection.objects.create(
            name="ClickHouse Target",
            db_type="clickhouse",
            host="127.0.0.1",
            port=8123,
            username="default",
            password="testpass",
            database_name="DEVOPS_DB",
            created_by=self.user,
            tenant=self.user,
        )

        self.api_conn = APIConnection.objects.create(
            name="Azure DevOps API",
            api_type="azure_devops",
            azure_tenant_id="11111111-1111-1111-1111-111111111111",
            azure_client_id="client-id",
            azure_client_secret="client-secret",
            organization="TORAI",
            tenant=self.user,
            created_by=self.user,
        )

        self.full_job = SyncJob.objects.create(
            name="Azure Full Job",
            source_api_connection=self.api_conn,
            source_connection_type="api",
            target_connection=self.db_conn,
            sync_type="full",
            status="pending",
            created_by=self.user,
            tenant=self.user,
        )
        self.incr_job = SyncJob.objects.create(
            name="Azure Incremental Job",
            source_api_connection=self.api_conn,
            source_connection_type="api",
            target_connection=self.db_conn,
            sync_type="incremental",
            status="pending",
            created_by=self.user,
            tenant=self.user,
        )

    @patch("sync_engine.azure_devops_runner.subprocess.run")
    def test_runner_uses_full_script_for_full_mode(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="ok", stderr="")
        execution = SyncExecution.objects.create(
            job=self.full_job,
            status="pending",
            total_tables=0,
        )

        run_azure_devops_sync(self.full_job, execution, mode="full")

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIn("devops_Full_sync.py", cmd[-1])
        env = kwargs.get("env") or {}
        self.assertEqual(env.get("DEVOPS_EXECUTION_ID"), str(execution.id))
        self.assertEqual(env.get("AZURE_ORGANIZATION"), "TORAI")
        self.assertEqual(env.get("CLICKHOUSE_DB"), "DEVOPS_DB")
        self.assertEqual(env.get("AZURE_TENANT_ID"), "11111111-1111-1111-1111-111111111111")
        self.assertEqual(env.get("AZURE_CLIENT_ID"), "client-id")
        self.assertEqual(env.get("AZURE_CLIENT_SECRET"), "client-secret")
        self.assertEqual(env.get("CLICKHOUSE_HOST"), "127.0.0.1")
        self.assertEqual(env.get("CLICKHOUSE_USER"), "default")
        self.assertEqual(env.get("CLICKHOUSE_PASS"), "testpass")
        self.assertIn("PYTHONPATH", env)
        self.assertIsNone(env.get("STRICT_INCREMENTAL_EXISTING_TABLES"))
        self.assertIsNone(env.get("TARGET_TABLE_PREFIX"))

    @patch("sync_engine.azure_devops_runner.subprocess.run")
    def test_runner_passes_target_table_prefix_when_set(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="ok", stderr="")
        self.full_job.target_table_prefix = "HR"
        self.full_job.save(update_fields=["target_table_prefix"])
        execution = SyncExecution.objects.create(
            job=self.full_job,
            status="pending",
            total_tables=0,
        )
        run_azure_devops_sync(self.full_job, execution, mode="full")
        env = mock_run.call_args.kwargs.get("env") or {}
        self.assertEqual(env.get("TARGET_TABLE_PREFIX"), "HR")

    @patch("sync_engine.azure_devops_runner.subprocess.run")
    def test_runner_uses_incremental_script_for_incremental_mode(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="ok", stderr="")
        execution = SyncExecution.objects.create(
            job=self.incr_job,
            status="pending",
            total_tables=0,
        )

        run_azure_devops_sync(self.incr_job, execution, mode="incremental")

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIn("devops_Increment_sync.py", cmd[-1])
        env = kwargs.get("env") or {}
        self.assertEqual(env.get("DEVOPS_EXECUTION_ID"), str(execution.id))
        self.assertEqual(env.get("AZURE_ORGANIZATION"), "TORAI")
        self.assertEqual(env.get("CLICKHOUSE_DB"), "DEVOPS_DB")
        self.assertEqual(env.get("AZURE_CLIENT_ID"), "client-id")
        self.assertEqual(env.get("CLICKHOUSE_HOST"), "127.0.0.1")
        self.assertIn("PYTHONPATH", env)
        self.assertEqual(env.get("STRICT_INCREMENTAL_EXISTING_TABLES"), "1")

    def test_populate_logs_adds_zero_row_projects_for_incremental(self):
        """When only one ADO project had WIQL hits, UI still shows all enabled projects."""
        for name in ("Embedded", "Platform", "Apollo"):
            SyncJobTable.objects.create(
                job=self.incr_job,
                schema_name="api",
                table_name=name,
                is_enabled=True,
            )
        execution = SyncExecution.objects.create(job=self.incr_job, status="running")
        stdout = """
📂 Project 1/3: Embedded
   • Processing 2 work items (0 new, 2 updated)
"""
        _populate_execution_logs_from_stdout(execution, stdout)
        # Runner saves execution after this helper; totals exist only on the instance here.
        logs = SyncExecutionLog.objects.filter(execution=execution).order_by("table_name")
        self.assertEqual(logs.count(), 3)
        by_name = {r.table_name: r for r in logs}
        self.assertEqual(by_name["Embedded"].rows_inserted, 2)
        self.assertEqual(by_name["Platform"].rows_inserted, 0)
        self.assertEqual(by_name["Apollo"].rows_inserted, 0)
        self.assertEqual(execution.total_tables, 3)
        self.assertEqual(execution.completed_tables, 3)
        self.assertEqual(execution.total_rows_synced, 2)

