"""
Tests for Zoho external-script runner: log parsing and execution log population.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import UserProfile, Role
from connections.models import APIConnection, DatabaseConnection
from sync_jobs.models import SyncExecution, SyncExecutionLog, SyncJob
from sync_engine.zoho_runner import (
    _parse_migration_summary_text,
    _populate_execution_logs_from_stdout,
    _resolve_parse_source,
)


class ZohoLogParsingTests(TestCase):
    """Unit tests for MIGRATION SUMMARY and legacy line formats."""

    def test_parse_optimized_migration_summary(self):
        text = """
2026-03-22 16:05:22,187 - INFO - ------------------------------------------------------------
2026-03-22 16:05:22,187 - INFO - ZOHO_activities                     ✓ SUCCESS        50,890   210.8s
2026-03-22 16:05:22,187 - INFO - ZOHO_leads                          ✓ SUCCESS        11,146    62.9s
2026-03-22 16:05:22,189 - INFO - ZOHO_projects                       ⚠ NO_ACCESS            0     0.1s
"""
        parsed = _parse_migration_summary_text(text)
        self.assertEqual(parsed["activities"].rows, 50890)
        self.assertAlmostEqual(parsed["activities"].duration_s, 210.8)
        self.assertTrue(parsed["activities"].access_ok)

        self.assertEqual(parsed["leads"].rows, 11146)
        self.assertTrue(parsed["leads"].access_ok)

        self.assertEqual(parsed["projects"].rows, 0)
        self.assertFalse(parsed["projects"].access_ok)

    def test_parse_legacy_success_line(self):
        text = "ZOHO_contacts  ✓ SUCCESS  +3055 / -0 ( 19.2s)\n"
        parsed = _parse_migration_summary_text(text)
        self.assertEqual(parsed["contacts"].rows, 3055)
        self.assertAlmostEqual(parsed["contacts"].duration_s, 19.2)
        self.assertTrue(parsed["contacts"].access_ok)

    def test_last_wins_same_suffix(self):
        text = (
            "ZOHO_x  ✓ SUCCESS  +1 / -0 ( 1.0s)\n"
            "ZOHO_x                     ✓ SUCCESS        99   2.0s\n"
        )
        parsed = _parse_migration_summary_text(text)
        self.assertEqual(parsed["x"].rows, 99)
        self.assertAlmostEqual(parsed["x"].duration_s, 2.0)


class ZohoPopulateExecutionLogsTests(TestCase):
    """Integration tests for SyncExecutionLog creation."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="zoho_parse_user",
            email="z@example.com",
            password="x",
        )
        UserProfile.objects.get_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN},
        )
        self.target = DatabaseConnection.objects.create(
            name="CH",
            db_type="clickhouse",
            host="h",
            port=8123,
            username="u",
            password="p",
            database_name="db",
            created_by=self.user,
            tenant=self.user,
        )
        self.api = APIConnection.objects.create(
            name="Zoho",
            api_type="zoho_crm",
            client_id="a",
            client_secret="b",
            refresh_token="c",
            api_domain="https://www.zohoapis.com",
            token_url="https://accounts.zoho.com/oauth/v2/token",
            tenant=self.user,
            created_by=self.user,
        )
        self.job = SyncJob.objects.create(
            name="zoho_full",
            source_api_connection=self.api,
            source_connection_type="api",
            target_connection=self.target,
            sync_type="full",
            status="pending",
            created_by=self.user,
            tenant=self.user,
        )
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status="running",
            started_at=timezone.now(),
            total_tables=0,
        )

    def test_populate_creates_rows_and_totals(self):
        text = (
            "2026-03-22 16:05:22,187 - INFO - "
            "ZOHO_activities                     ✓ SUCCESS        50,890   210.8s\n"
        )
        _populate_execution_logs_from_stdout(self.execution, text)
        self.execution.refresh_from_db()

        logs = SyncExecutionLog.objects.filter(execution=self.execution).order_by("table_name")
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.table_name, "activities")
        self.assertEqual(log.rows_fetched, 50890)
        self.assertEqual(log.rows_inserted, 50890)
        self.assertEqual(log.verification_summary, "Duration: 210.8s")
        self.assertEqual(self.execution.total_rows_synced, 50890)
        self.assertEqual(self.execution.completed_tables, 1)
        self.assertEqual(self.execution.total_tables, 1)

    def test_populate_no_access_verification(self):
        text = "ZOHO_projects                       ⚠ NO_ACCESS            0     0.1s\n"
        _populate_execution_logs_from_stdout(self.execution, text)
        log = SyncExecutionLog.objects.get(execution=self.execution, table_name="projects")
        self.assertEqual(log.verification_summary, "NO_ACCESS")
        self.assertEqual(log.rows_fetched, 0)


class ZohoResolveParseSourceTests(TestCase):
    """Fallback log file resolution."""

    def test_resolve_prefers_stdout(self):
        root = Path(__file__).resolve().parents[1]
        out = _resolve_parse_source(root, "full", "ZOHO_a  ✓ SUCCESS  +1 / -0 ( 1.0s)\n")
        self.assertIn("ZOHO_a", out)

    def test_resolve_full_optimized_file(self):
        root = Path(__file__).resolve().parents[1]
        logs_dir = root / "logs"
        logs_dir.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        path = logs_dir / f"zoho_full_optimized_{today}.log"
        try:
            path.write_text(
                "ZOHO_testtable  ✓ SUCCESS        100   5.0s\n",
                encoding="utf-8",
            )
            out = _resolve_parse_source(root, "full", "")
            self.assertIn("ZOHO_testtable", out)
        finally:
            if path.exists():
                path.unlink()


class ZohoRunSyncPopenTests(TestCase):
    """run_zoho_sync uses Popen and final parse; script path must exist."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="zoho_run_user",
            email="r@example.com",
            password="x",
        )
        UserProfile.objects.get_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN},
        )
        self.target = DatabaseConnection.objects.create(
            name="CH2",
            db_type="clickhouse",
            host="h",
            port=8123,
            username="u",
            password="p",
            database_name="db",
            created_by=self.user,
            tenant=self.user,
        )
        self.api = APIConnection.objects.create(
            name="Zoho2",
            api_type="zoho_crm",
            client_id="a",
            client_secret="b",
            refresh_token="c",
            api_domain="https://www.zohoapis.com",
            token_url="https://accounts.zoho.com/oauth/v2/token",
            tenant=self.user,
            created_by=self.user,
        )
        self.job = SyncJob.objects.create(
            name="zoho_run",
            source_api_connection=self.api,
            source_connection_type="api",
            target_connection=self.target,
            sync_type="full",
            status="pending",
            created_by=self.user,
            tenant=self.user,
        )
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status="pending",
            total_tables=0,
        )

    def _fake_popen(self, *args, **kwargs):
        """Emit one structured line and one summary line."""
        lines = [
            "ZOHO_SYNC_LOG v1|table=leads|status=success|rows=100|seconds=2.5\n",
            "2026-03-22 16:05:22,187 - INFO - "
            "ZOHO_leads                          ✓ SUCCESS        100   2.5s\n",
        ]

        class _Stdout:
            def __iter__(self_inner):
                return iter(lines)

            def close(self_inner):
                pass

        proc = MagicMock()
        proc.stdout = _Stdout()
        proc.stderr = MagicMock()
        proc.stderr.read = MagicMock(return_value="")
        proc.wait = MagicMock(return_value=0)
        return proc

    @patch("sync_engine.zoho_runner.subprocess.Popen")
    def test_run_zoho_sync_popen_and_parse(self, mock_popen):
        mock_popen.side_effect = self._fake_popen

        real_exists = Path.exists

        def exists_side_effect(self_path):
            s = str(self_path).replace("\\", "/")
            if s.endswith("zoho_full.py"):
                return True
            return real_exists(self_path)

        from sync_engine import zoho_runner

        with patch.object(Path, "exists", exists_side_effect):
            zoho_runner.run_zoho_sync(self.job, self.execution, mode="full")

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, "completed")
        log = SyncExecutionLog.objects.get(execution=self.execution, table_name="leads")
        self.assertEqual(log.rows_fetched, 100)
        self.assertEqual(log.verification_summary, "Duration: 2.5s")

    def test_run_zoho_sync_parses_summary_from_disk_when_stdout_missing(self):
        """Regression: stdout is non-empty but contains no summary lines."""
        today = datetime.now().strftime("%Y%m%d")
        project_root = Path(__file__).resolve().parents[2]
        logs_dir = project_root / "logs"

        disk_path = logs_dir / f"zoho_full_optimized_{today}.log"
        logs_dir.mkdir(exist_ok=True)

        rows = 123
        duration_s = 1.0
        disk_content = (
            f"ZOHO_activities                     ✓ SUCCESS        {rows}   {duration_s}s\n"
        )

        backup_text = None
        if disk_path.exists():
            backup_text = disk_path.read_text(encoding="utf-8", errors="ignore")

        try:
            disk_path.write_text(disk_content, encoding="utf-8")

            def _fake_popen_no_summary(*args, **kwargs):
                # stdout is intentionally "noisy" but does not include any
                # ZOHO_* MIGRATION SUMMARY or structured UI lines.
                lines = ["Some progress...\n", "Still running...\n"]

                class _Stdout:
                    def __iter__(self_inner):
                        return iter(lines)

                    def close(self_inner):
                        pass

                proc = MagicMock()
                proc.stdout = _Stdout()
                proc.stderr = MagicMock()
                proc.stderr.read = MagicMock(return_value="")
                proc.wait = MagicMock(return_value=0)
                return proc

            with patch("sync_engine.zoho_runner.subprocess.Popen") as mock_popen:
                mock_popen.side_effect = _fake_popen_no_summary

                real_exists = Path.exists

                def exists_side_effect(self_path):
                    s = str(self_path).replace("\\", "/")
                    if s.endswith("zoho_full.py"):
                        return True
                    return real_exists(self_path)

                from sync_engine import zoho_runner

                with patch.object(Path, "exists", exists_side_effect):
                    zoho_runner.run_zoho_sync(
                        self.job, self.execution, mode="full"
                    )

            self.execution.refresh_from_db()
            self.assertEqual(self.execution.status, "completed")

            log = SyncExecutionLog.objects.get(
                execution=self.execution, table_name="activities"
            )
            self.assertEqual(log.rows_fetched, rows)
            self.assertEqual(log.rows_inserted, rows)
            self.assertEqual(log.verification_summary, "Duration: 1s")
            self.assertEqual(self.execution.total_rows_synced, rows)
            self.assertEqual(self.execution.completed_tables, 1)
            self.assertEqual(self.execution.total_tables, 1)
        finally:
            if backup_text is None:
                if disk_path.exists():
                    disk_path.unlink()
            else:
                disk_path.write_text(backup_text, encoding="utf-8")
