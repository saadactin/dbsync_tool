"""
Unit tests for scripts/devops_config.py (Azure DevOps script env + table prefix).
"""
import os
import sys
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import devops_config  # noqa: E402


class DevOpsConfigTests(SimpleTestCase):
    def test_prefix_strips_underscore_and_builds_table_names(self):
        env = {
            "TARGET_TABLE_PREFIX": "HR_",
            "AZURE_ORGANIZATION": "MyOrg",
            "CLICKHOUSE_HOST": "h",
            "CLICKHOUSE_USER": "u",
            "CLICKHOUSE_PASS": "p",
            "CLICKHOUSE_DB": "db",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = devops_config.load_devops_script_config()
        self.assertEqual(cfg.table_prefix, "HR")
        self.assertEqual(cfg.table_main, "HR_DEVOPS_WORKITEMS_MAIN")
        self.assertEqual(cfg.table_sprints, "HR_DEVOPS_SPRINTS")

    def test_prefix_devops_is_treated_as_redundant(self):
        env = {
            "TARGET_TABLE_PREFIX": "DEVOPS",
            "AZURE_ORGANIZATION": "MyOrg",
            "CLICKHOUSE_HOST": "h",
            "CLICKHOUSE_USER": "u",
            "CLICKHOUSE_PASS": "p",
            "CLICKHOUSE_DB": "db",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = devops_config.load_devops_script_config()
        # Base names already include "DEVOPS_" so TARGET_TABLE_PREFIX=DEVOPS
        # should not create "DEVOPS_DEVOPS_*".
        self.assertEqual(cfg.table_prefix, "")
        self.assertEqual(cfg.table_main, "DEVOPS_WORKITEMS_MAIN")
        self.assertEqual(cfg.table_sprints, "DEVOPS_SPRINTS")

    def test_no_prefix_uses_base_names(self):
        env = {
            "AZURE_ORGANIZATION": "X",
            "CLICKHOUSE_HOST": "h",
            "CLICKHOUSE_USER": "u",
            "CLICKHOUSE_PASS": "p",
            "CLICKHOUSE_DB": "db",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = devops_config.load_devops_script_config()
        self.assertEqual(cfg.table_prefix, "")
        self.assertEqual(cfg.table_main, "DEVOPS_WORKITEMS_MAIN")
        self.assertEqual(cfg.table_teams, "DEVOPS_TEAMS")

    def test_strict_incremental_flag(self):
        base = {
            "AZURE_ORGANIZATION": "X",
            "CLICKHOUSE_HOST": "h",
            "CLICKHOUSE_USER": "u",
            "CLICKHOUSE_PASS": "p",
            "CLICKHOUSE_DB": "db",
        }
        with mock.patch.dict(os.environ, {**base, "STRICT_INCREMENTAL_EXISTING_TABLES": "1"}, clear=True):
            self.assertTrue(devops_config.load_devops_script_config().strict_incremental_existing_tables)
        with mock.patch.dict(os.environ, {**base, "STRICT_INCREMENTAL_EXISTING_TABLES": "0"}, clear=True):
            self.assertFalse(devops_config.load_devops_script_config().strict_incremental_existing_tables)

    def test_work_item_table_names_order(self):
        env = {
            "TARGET_TABLE_PREFIX": "P",
            "AZURE_ORGANIZATION": "X",
            "CLICKHOUSE_HOST": "h",
            "CLICKHOUSE_USER": "u",
            "CLICKHOUSE_PASS": "p",
            "CLICKHOUSE_DB": "db",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = devops_config.load_devops_script_config()
        names = devops_config.work_item_table_names(cfg)
        self.assertEqual(
            names,
            (
                "P_DEVOPS_WORKITEMS_MAIN",
                "P_DEVOPS_WORKITEMS_UPDATES",
                "P_DEVOPS_WORKITEMS_COMMENTS",
                "P_DEVOPS_WORKITEMS_RELATIONS",
                "P_DEVOPS_WORKITEMS_REVISIONS",
            ),
        )

    def test_redis_defaults_overridable(self):
        base = {
            "AZURE_ORGANIZATION": "X",
            "CLICKHOUSE_HOST": "h",
            "CLICKHOUSE_USER": "u",
            "CLICKHOUSE_PASS": "p",
            "CLICKHOUSE_DB": "db",
            "REDIS_HOST": "redis.example",
            "REDIS_PORT": "6380",
            "REDIS_DB": "2",
            "REDIS_KEY_PREFIX": "custom",
        }
        with mock.patch.dict(os.environ, base, clear=True):
            cfg = devops_config.load_devops_script_config()
        self.assertEqual(cfg.redis_host, "redis.example")
        self.assertEqual(cfg.redis_port, 6380)
        self.assertEqual(cfg.redis_db, 2)
        self.assertEqual(cfg.redis_key_prefix, "custom")
