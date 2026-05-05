"""
Env-gated integration tests for Postgres -> ClickHouse reliable sync.

These tests are skipped unless the following environment variables are set:

  RELIABLE_SYNC_TEST_PG_HOST
  RELIABLE_SYNC_TEST_PG_PORT
  RELIABLE_SYNC_TEST_PG_USER
  RELIABLE_SYNC_TEST_PG_PASSWORD
  RELIABLE_SYNC_TEST_PG_DB

  RELIABLE_SYNC_TEST_CH_HOST
  RELIABLE_SYNC_TEST_CH_PORT
  RELIABLE_SYNC_TEST_CH_USER
  RELIABLE_SYNC_TEST_CH_PASSWORD
  RELIABLE_SYNC_TEST_CH_DB

Scenarios to validate (when wired end-to-end):
  1) New rows: incremental sync inserts new identity tuples with 0 duplicates.
  2) Updated rows: incremental sync replaces identity tuples correctly (hash parity).
  3) Non-monotonic update recovery:
     - simulate an update where the watermark is not monotonic
     - strict verification should detect drift and trigger immediate repair-full
     - after repair, ClickHouse must match Postgres by strict hash parity
"""

import os
import unittest

import pytest


REQUIRED_ENV = (
    "RELIABLE_SYNC_TEST_PG_HOST",
    "RELIABLE_SYNC_TEST_PG_PORT",
    "RELIABLE_SYNC_TEST_PG_USER",
    "RELIABLE_SYNC_TEST_PG_PASSWORD",
    "RELIABLE_SYNC_TEST_PG_DB",
    "RELIABLE_SYNC_TEST_CH_HOST",
    "RELIABLE_SYNC_TEST_CH_PORT",
    "RELIABLE_SYNC_TEST_CH_USER",
    "RELIABLE_SYNC_TEST_CH_PASSWORD",
    "RELIABLE_SYNC_TEST_CH_DB",
)


def _has_env() -> bool:
    return all(os.environ.get(name) for name in REQUIRED_ENV)


pytestmark = pytest.mark.skipif(
    not _has_env(),
    reason="Postgres -> ClickHouse reliable sync env not configured",
)


class PostgresToClickHouseReliableSyncTests(unittest.TestCase):
    """Integration tests; scaffolded unless env is configured."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not _has_env():
            raise unittest.SkipTest("Required env vars not set; skipping integration tests")

    def test_new_rows_are_inserted_without_duplicates(self):
        # TODO (when wiring real envs):
        # - create a SyncJob (source=Postgres, target=ClickHouse) with:
        #     - verification_mode='strict'
        #     - incremental sync enabled using an incremental column
        #     - identity keys defined (single or composite)
        # - create/clean tables
        # - insert new identity tuples in Postgres
        # - run incremental sync job once
        # - assert:
        #     - COUNT(*) by identity equals Postgres
        #     - strict hash parity passes (verifier)
        self.skipTest("Integration scaffold only. Wire a real PG+ClickHouse pair via env vars.")

    def test_updated_rows_are_replaced_correctly(self):
        # TODO (when wiring real envs):
        # - insert baseline rows in Postgres
        # - run incremental sync
        # - update values for existing identity tuples in Postgres
        # - run incremental sync again
        # - assert strict hash parity and 0 duplicates by identity in ClickHouse
        self.skipTest("Integration scaffold only. Wire a real PG+ClickHouse pair via env vars.")

    def test_non_monotonic_update_triggers_strict_repair_full(self):
        # TODO (when wiring real envs):
        # - configure strict verification
        # - insert baseline
        # - simulate a non-monotonic watermark scenario for updates
        # - run incremental sync
        # - assert strict verification detected drift and incremental strict repair-full ran
        # - assert strict parity after repair
        self.skipTest("Integration scaffold only. Wire a real PG+ClickHouse pair via env vars.")

