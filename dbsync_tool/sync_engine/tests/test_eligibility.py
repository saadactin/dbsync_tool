"""Unit tests for IncrementalEligibility classifier."""
from django.test import TestCase

from connections.connectors.base import ColumnInfo
from sync_engine.eligibility import IncrementalEligibility


def _col(name: str, dtype: str, *, nullable: bool = True, pk: bool = False) -> ColumnInfo:
    return ColumnInfo(name=name, data_type=dtype, is_nullable=nullable, is_primary_key=pk)


class IncrementalEligibilityTests(TestCase):
    def test_picks_incremental_for_pk_plus_datetime2(self):
        cols = [
            _col("id", "int", nullable=False, pk=True),
            _col("name", "varchar"),
            _col("updated_at", "datetime2"),
        ]
        decision = IncrementalEligibility.evaluate(
            configured_incremental_column=None,
            configured_key_columns=None,
            columns=cols,
            pk_columns=["id"],
        )
        self.assertEqual(decision.mode, "incremental")
        self.assertEqual(decision.upsert_keys, ["id"])
        self.assertEqual(decision.chosen_incremental_column, "updated_at")

    def test_picks_incremental_for_rowversion_priority(self):
        cols = [
            _col("id", "int", nullable=False, pk=True),
            _col("rv", "rowversion"),
            _col("updated_at", "datetime2"),
        ]
        decision = IncrementalEligibility.evaluate(
            configured_incremental_column=None,
            configured_key_columns=None,
            columns=cols,
            pk_columns=["id"],
        )
        self.assertEqual(decision.mode, "incremental")
        self.assertEqual(decision.chosen_incremental_column, "rv")

    def test_falls_back_to_full_when_no_pk_or_keys(self):
        cols = [
            _col("name", "varchar"),
            _col("updated_at", "datetime2"),
        ]
        decision = IncrementalEligibility.evaluate(
            configured_incremental_column=None,
            configured_key_columns=None,
            columns=cols,
            pk_columns=[],
        )
        self.assertEqual(decision.mode, "full")
        self.assertIn("no_upsert_key_available", decision.reasons)

    def test_falls_back_to_full_for_date_only_configured_column(self):
        cols = [
            _col("id", "int", nullable=False, pk=True),
            _col("event_date", "date"),
        ]
        decision = IncrementalEligibility.evaluate(
            configured_incremental_column="event_date",
            configured_key_columns=None,
            columns=cols,
            pk_columns=["id"],
        )
        self.assertEqual(decision.mode, "full")

    def test_uses_configured_keys_when_no_pk(self):
        cols = [
            _col("client_id", "varchar"),
            _col("updated_at", "datetime2"),
        ]
        decision = IncrementalEligibility.evaluate(
            configured_incremental_column=None,
            configured_key_columns=["client_id"],
            columns=cols,
            pk_columns=[],
        )
        self.assertEqual(decision.mode, "incremental")
        self.assertEqual(decision.upsert_keys, ["client_id"])

    def test_assume_monotonic_false_disables_datetime2_incremental(self):
        cols = [
            _col("id", "int", nullable=False, pk=True),
            _col("updated_at", "datetime2"),
        ]
        decision = IncrementalEligibility.evaluate(
            configured_incremental_column=None,
            configured_key_columns=None,
            columns=cols,
            pk_columns=["id"],
            assume_incremental_monotonic=False,
        )
        self.assertEqual(decision.mode, "full")
        self.assertTrue(
            any("monotonic_unknown_disallow_non_rowversion" in r for r in decision.reasons)
        )
