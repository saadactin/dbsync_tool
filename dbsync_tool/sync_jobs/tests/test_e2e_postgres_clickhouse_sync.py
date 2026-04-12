"""
Opt-in live E2E: PostgreSQL → ClickHouse full sync + incremental sync.

Enable with environment variable (any truthy value):
  E2E_PG_TO_CH=1

Required when enabled:
  E2E_PG_HOST, E2E_PG_PORT, E2E_PG_DB, E2E_PG_USER, E2E_PG_PASSWORD
  E2E_CH_HOST, E2E_CH_PORT, E2E_CH_DB, E2E_CH_USER, E2E_CH_PASSWORD

Notes (incremental semantics, from code audit):
  - Source is PostgreSQL: QueryBuilder.build_incremental_query uses
    WHERE incremental_col > checkpoint (no IS NOT NULL on source; first run uses WHERE 1=1).
  - Target ClickHouse: upserts use ClickHouseConnector.upsert_dataframe (DELETE by key + INSERT).
  - Incremental sync does not create the target table; run full sync first (or pre-create).

Frontend checklist (manual, no secrets in repo):
  1. Connections → add/edit PostgreSQL and ClickHouse with the same values as your E2E_* env vars;
     use Test Connection for both.
  2. Sync Jobs → create job PostgreSQL → ClickHouse, select the E2E table, Full sync, run;
     open execution details and confirm the table log is completed and row counts match expectations.
  3. Create an Incremental job (or edit) with incremental column `updated_at`, run once, insert new rows
     in PostgreSQL, run again; confirm only new rows appear in ClickHouse (check execution log / CH count).

Run (example, PowerShell):
  $env:E2E_PG_TO_CH='1'
  $env:E2E_PG_HOST='localhost'
  ... set remaining variables ...
  python manage.py test sync_jobs.tests.test_e2e_postgres_clickhouse_sync -v 2

After changing PostgreSQL→ClickHouse temporal types (e.g. Date→Date32, DateTime→DateTime64):
  Drop the target ClickHouse table (or rely on schema mismatch auto-drop in table creation)
  before re-running a job whose target was built with older Date/DateTime column types.
"""

from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth.models import User
from django.test import TransactionTestCase

from connections.connectors.factory import get_connector
from sync_engine.executor import SyncExecutor
from sync_jobs.models import SyncCheckpoint, SyncJob, SyncJobTable, SyncExecution
from psycopg2.extras import Json as PsycopgJson

from sync_jobs.tests.e2e_pg_ch_helpers import create_e2e_pg_ch_connections


def _e2e_enabled() -> bool:
    v = (os.environ.get("E2E_PG_TO_CH") or "").strip().lower()
    return v in ("1", "true", "yes", "y")


def _require_pg_ch_config():
    keys = [
        "E2E_PG_HOST",
        "E2E_PG_PORT",
        "E2E_PG_DB",
        "E2E_PG_USER",
        "E2E_PG_PASSWORD",
        "E2E_CH_HOST",
        "E2E_CH_PORT",
        "E2E_CH_DB",
        "E2E_CH_USER",
        "E2E_CH_PASSWORD",
    ]
    missing = [k for k in keys if not (os.environ.get(k) or "").strip()]
    if missing:
        raise unittest.SkipTest(
            f"E2E_PG_TO_CH is set but missing environment variables: {', '.join(missing)}"
        )


@skipUnless(_e2e_enabled(), "Set E2E_PG_TO_CH=1 and database env vars to run live PG→CH E2E tests")
class PostgresClickHouseE2ETests(TransactionTestCase):
    """Live tests against real PostgreSQL and ClickHouse (opt-in)."""

    def setUp(self):
        _require_pg_ch_config()
        from accounts.models import Role, UserProfile

        suffix = uuid.uuid4().hex[:10]
        self.pg_table = f"dbsync_e2e_pgch_{suffix}"
        self.pg_schema = "public"

        self.user = User.objects.create_user(
            username=f"e2e_pgch_{suffix}",
            password="e2e-test-pass-unchanged",
            email=f"e2e_pgch_{suffix}@example.com",
        )
        profile, _ = UserProfile.objects.get_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": None},
        )
        if profile.tenant is not None or profile.role != Role.ADMIN:
            profile.role = Role.ADMIN
            profile.tenant = None
            profile.save()

        self.pg_cfg = {
            "host": os.environ["E2E_PG_HOST"].strip(),
            "port": int(os.environ["E2E_PG_PORT"].strip()),
            "database_name": os.environ["E2E_PG_DB"].strip(),
            "username": os.environ["E2E_PG_USER"].strip(),
            "password": os.environ["E2E_PG_PASSWORD"],
        }
        self.ch_cfg = {
            "host": os.environ["E2E_CH_HOST"].strip(),
            "port": int(os.environ["E2E_CH_PORT"].strip()),
            "database_name": os.environ["E2E_CH_DB"].strip(),
            "username": os.environ["E2E_CH_USER"].strip(),
            "password": os.environ["E2E_CH_PASSWORD"],
        }

        self.pg_conn_model, self.ch_conn_model = create_e2e_pg_ch_connections(
            self.user, pg=self.pg_cfg, ch=self.ch_cfg
        )

        self._ddl_pg_table()
        self._seed_pg_rows()
        self.addCleanup(self._drop_pg_table)
        self.addCleanup(self._drop_ch_table)

    def _connectors(self):
        pg = get_connector(self.pg_conn_model)
        ch = get_connector(self.ch_conn_model)
        return pg, ch

    def _ddl_pg_table(self):
        pg, _ = self._connectors()
        pg.connect()
        try:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {self.pg_schema}.{self.pg_table} (
                id INTEGER PRIMARY KEY,
                c_small SMALLINT,
                c_int INTEGER,
                c_big BIGINT,
                c_real REAL,
                c_double DOUBLE PRECISION,
                c_numeric NUMERIC(18,4),
                c_text TEXT,
                c_varchar VARCHAR(64),
                c_bool BOOLEAN,
                c_date DATE,
                c_time TIME,
                c_ts TIMESTAMP WITHOUT TIME ZONE,
                c_tstz TIMESTAMPTZ,
                c_bytea BYTEA,
                c_uuid UUID,
                c_json JSONB,
                updated_at TIMESTAMPTZ NOT NULL
            );
            """
            pg.execute_query(ddl)
        finally:
            pg.close()

    def _seed_pg_rows(self):
        pg, _ = self._connectors()
        pg.connect()
        try:
            base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
            uid = uuid.UUID("11111111-1111-1111-1111-111111111111")
            columns = [
                "id",
                "c_small",
                "c_int",
                "c_big",
                "c_real",
                "c_double",
                "c_numeric",
                "c_text",
                "c_varchar",
                "c_bool",
                "c_date",
                "c_time",
                "c_ts",
                "c_tstz",
                "c_bytea",
                "c_uuid",
                "c_json",
                "updated_at",
            ]
            rows = []
            for i in range(1, 6):
                rows.append(
                    (
                        i,
                        i,
                        100 + i,
                        1_000_000 + i,
                        float(i) + 0.25,
                        float(i) + 0.75,
                        Decimal(f"{i}.4321"),
                        f"text_{i}",
                        f"v{i:02d}",
                        True,
                        date(2024, 1, i),
                        time(10 + i, 30, 0),
                        datetime(2024, 2, i, 8, 0, 0),
                        base + timedelta(minutes=i),
                        bytes([i, i + 1]),
                        uid,
                        PsycopgJson({"row": i, "tag": "e2e"}),
                        base + timedelta(minutes=i),
                    )
                )
            pg.bulk_insert(self.pg_schema, self.pg_table, columns, rows)
        finally:
            pg.close()

    def _drop_pg_table(self):
        try:
            pg, _ = self._connectors()
            pg.connect()
            try:
                pg.execute_query(f'DROP TABLE IF EXISTS "{self.pg_schema}"."{self.pg_table}" CASCADE;')
            finally:
                pg.close()
        except Exception:
            pass

    def _drop_ch_table(self):
        ch_db = self.ch_cfg["database_name"]
        try:
            _, ch = self._connectors()
            ch.connect()
            try:
                ch.execute_query(f"DROP TABLE IF EXISTS `{ch_db}`.`{self.pg_table}`")
            finally:
                ch.close()
        except Exception:
            pass

    def _ch_row_count(self) -> int:
        ch_db = self.ch_cfg["database_name"]
        _, ch = self._connectors()
        ch.connect()
        try:
            return ch.get_row_count(ch_db, self.pg_table)
        finally:
            ch.close()

    def _run_job(self, job: SyncJob) -> SyncExecution:
        ex = SyncExecutor(job)
        ex.execute()
        return SyncExecution.objects.filter(job=job).order_by("-started_at").first()

    def test_full_sync_then_incremental_pg_to_clickhouse(self):
        """Full sync creates CH table and loads rows; incremental upserts new rows only."""
        ch_db = self.ch_cfg["database_name"]

        full_job = SyncJob.objects.create(
            name=f"E2E full PG→CH {self.pg_table}",
            source_connection=self.pg_conn_model,
            target_connection=self.ch_conn_model,
            sync_type="full",
            created_by=self.user,
            tenant=self.user,
            source_connection_type="database",
        )
        SyncJobTable.objects.create(
            job=full_job,
            schema_name=self.pg_schema,
            table_name=self.pg_table,
            incremental_column="updated_at",
            is_enabled=True,
        )

        full_exec = self._run_job(full_job)
        self.assertIsNotNone(full_exec)
        self.assertEqual(
            full_exec.status,
            "completed",
            getattr(full_exec, "error_message", None) or full_exec.status,
        )

        log = full_exec.logs.filter(table_name=self.pg_table).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "completed", log.error_message or log.status)

        self.assertEqual(self._ch_row_count(), 5)

        _, ch = self._connectors()
        ch.connect()
        try:
            sample = ch.execute_query_fetchall(
                f"SELECT id, c_text, c_numeric FROM `{ch_db}`.`{self.pg_table}` WHERE id = 1 LIMIT 1"
            )
            self.assertEqual(len(sample), 1)
            self.assertEqual(sample[0][0], 1)
            self.assertEqual(sample[0][1], "text_1")
        finally:
            ch.close()

        inc_job = SyncJob.objects.create(
            name=f"E2E incremental PG→CH {self.pg_table}",
            source_connection=self.pg_conn_model,
            target_connection=self.ch_conn_model,
            sync_type="incremental",
            created_by=self.user,
            tenant=self.user,
            source_connection_type="database",
            incremental_overlap_seconds=0,
        )
        SyncJobTable.objects.create(
            job=inc_job,
            schema_name=self.pg_schema,
            table_name=self.pg_table,
            incremental_column="updated_at",
            is_enabled=True,
        )

        inc_exec1 = self._run_job(inc_job)
        self.assertEqual(inc_exec1.status, "completed", inc_exec1.error_message)
        self.assertEqual(self._ch_row_count(), 5)
        cp = SyncCheckpoint.objects.filter(
            job=inc_job, schema_name=self.pg_schema, table_name=self.pg_table
        ).first()
        self.assertIsNotNone(cp, "Checkpoint should exist after first incremental run")

        base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        uid = uuid.UUID("22222222-2222-2222-2222-222222222222")
        pg, _ = self._connectors()
        pg.connect()
        try:
            extra_cols = [
                "id",
                "c_small",
                "c_int",
                "c_big",
                "c_real",
                "c_double",
                "c_numeric",
                "c_text",
                "c_varchar",
                "c_bool",
                "c_date",
                "c_time",
                "c_ts",
                "c_tstz",
                "c_bytea",
                "c_uuid",
                "c_json",
                "updated_at",
            ]
            extra_rows = [
                (
                    6,
                    6,
                    106,
                    1_000_006,
                    6.25,
                    6.75,
                    Decimal("6.4321"),
                    "text_6",
                    "v06",
                    False,
                    date(2024, 1, 6),
                    time(16, 30, 0),
                    datetime(2024, 2, 6, 8, 0, 0),
                    base + timedelta(hours=2),
                    b"\xaa\xbb",
                    uid,
                    PsycopgJson({"row": 6}),
                    base + timedelta(hours=2),
                ),
                (
                    7,
                    7,
                    107,
                    1_000_007,
                    7.25,
                    7.75,
                    Decimal("7.4321"),
                    "text_7",
                    "v07",
                    True,
                    date(2024, 1, 7),
                    time(17, 30, 0),
                    datetime(2024, 2, 7, 8, 0, 0),
                    base + timedelta(hours=3),
                    b"\xcc\xdd",
                    uid,
                    PsycopgJson({"row": 7}),
                    base + timedelta(hours=3),
                ),
                (
                    8,
                    8,
                    108,
                    1_000_008,
                    8.25,
                    8.75,
                    Decimal("8.4321"),
                    "text_8",
                    "v08",
                    False,
                    date(2024, 1, 8),
                    time(18, 30, 0),
                    datetime(2024, 2, 8, 8, 0, 0),
                    base + timedelta(hours=4),
                    b"\xee\xff",
                    uid,
                    PsycopgJson({"row": 8}),
                    base + timedelta(hours=4),
                ),
            ]
            pg.bulk_insert(self.pg_schema, self.pg_table, extra_cols, extra_rows)
        finally:
            pg.close()

        inc_exec2 = self._run_job(inc_job)
        self.assertEqual(inc_exec2.status, "completed", inc_exec2.error_message)
        self.assertEqual(self._ch_row_count(), 8)

        inc_exec3 = self._run_job(inc_job)
        self.assertEqual(inc_exec3.status, "completed", inc_exec3.error_message)
        self.assertEqual(self._ch_row_count(), 8)

        _, ch = self._connectors()
        ch.connect()
        try:
            jrow = ch.execute_query_fetchall(
                f"SELECT c_json FROM `{ch_db}`.`{self.pg_table}` WHERE id = 6 LIMIT 1"
            )
            self.assertEqual(len(jrow), 1)
            parsed = json.loads(jrow[0][0]) if isinstance(jrow[0][0], str) else jrow[0][0]
            self.assertEqual(parsed.get("row"), 6)
        finally:
            ch.close()


@skipUnless(_e2e_enabled(), "Set E2E_PG_TO_CH=1 and database env vars to run live PG→CH E2E tests")
class PostgresClickHouseWideTemporalE2ETests(TransactionTestCase):
    """Live test: PostgreSQL dates/timestamps through year 9999 insert into ClickHouse Date32/DateTime64."""

    def setUp(self):
        _require_pg_ch_config()
        from accounts.models import Role, UserProfile

        suffix = uuid.uuid4().hex[:10]
        self.pg_table = f"dbsync_e2e_wide_{suffix}"
        self.pg_schema = "public"

        self.user = User.objects.create_user(
            username=f"e2e_wide_{suffix}",
            password="e2e-test-pass-unchanged",
            email=f"e2e_wide_{suffix}@example.com",
        )
        profile, _ = UserProfile.objects.get_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": None},
        )
        if profile.tenant is not None or profile.role != Role.ADMIN:
            profile.role = Role.ADMIN
            profile.tenant = None
            profile.save()

        self.pg_cfg = {
            "host": os.environ["E2E_PG_HOST"].strip(),
            "port": int(os.environ["E2E_PG_PORT"].strip()),
            "database_name": os.environ["E2E_PG_DB"].strip(),
            "username": os.environ["E2E_PG_USER"].strip(),
            "password": os.environ["E2E_PG_PASSWORD"],
        }
        self.ch_cfg = {
            "host": os.environ["E2E_CH_HOST"].strip(),
            "port": int(os.environ["E2E_CH_PORT"].strip()),
            "database_name": os.environ["E2E_CH_DB"].strip(),
            "username": os.environ["E2E_CH_USER"].strip(),
            "password": os.environ["E2E_CH_PASSWORD"],
        }

        self.pg_conn_model, self.ch_conn_model = create_e2e_pg_ch_connections(
            self.user, pg=self.pg_cfg, ch=self.ch_cfg
        )

        self._ddl_pg_wide_table()
        self._seed_pg_wide_row()
        self.addCleanup(self._drop_pg_wide_table)
        self.addCleanup(self._drop_ch_wide_table)

    def _connectors(self):
        pg = get_connector(self.pg_conn_model)
        ch = get_connector(self.ch_conn_model)
        return pg, ch

    def _ddl_pg_wide_table(self):
        pg, _ = self._connectors()
        pg.connect()
        try:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {self.pg_schema}.{self.pg_table} (
                id INTEGER PRIMARY KEY,
                c_date DATE NOT NULL,
                c_tstz TIMESTAMPTZ NOT NULL
            );
            """
            pg.execute_query(ddl)
        finally:
            pg.close()

    def _seed_pg_wide_row(self):
        pg, _ = self._connectors()
        pg.connect()
        try:
            row = (
                1,
                date(9999, 12, 31),
                datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
            )
            pg.bulk_insert(
                self.pg_schema,
                self.pg_table,
                ["id", "c_date", "c_tstz"],
                [row],
            )
        finally:
            pg.close()

    def _drop_pg_wide_table(self):
        try:
            pg, _ = self._connectors()
            pg.connect()
            try:
                pg.execute_query(
                    f'DROP TABLE IF EXISTS "{self.pg_schema}"."{self.pg_table}" CASCADE;'
                )
            finally:
                pg.close()
        except Exception:
            pass

    def _drop_ch_wide_table(self):
        ch_db = self.ch_cfg["database_name"]
        try:
            _, ch = self._connectors()
            ch.connect()
            try:
                ch.execute_query(f"DROP TABLE IF EXISTS `{ch_db}`.`{self.pg_table}`")
            finally:
                ch.close()
        except Exception:
            pass

    def _ch_row_count(self) -> int:
        ch_db = self.ch_cfg["database_name"]
        _, ch = self._connectors()
        ch.connect()
        try:
            return ch.get_row_count(ch_db, self.pg_table)
        finally:
            ch.close()

    def test_full_sync_wide_temporal_year_9999(self):
        """Target DDL uses Date32/DateTime64; one row with 9999-12-31 loads successfully."""
        full_job = SyncJob.objects.create(
            name=f"E2E wide temporal PG→CH {self.pg_table}",
            source_connection=self.pg_conn_model,
            target_connection=self.ch_conn_model,
            sync_type="full",
            created_by=self.user,
            tenant=self.user,
            source_connection_type="database",
        )
        SyncJobTable.objects.create(
            job=full_job,
            schema_name=self.pg_schema,
            table_name=self.pg_table,
            is_enabled=True,
        )

        ex = SyncExecutor(full_job)
        ex.execute()
        last = SyncExecution.objects.filter(job=full_job).order_by("-started_at").first()
        self.assertIsNotNone(last)
        self.assertEqual(
            last.status,
            "completed",
            getattr(last, "error_message", None) or last.status,
        )
        self.assertEqual(self._ch_row_count(), 1)
