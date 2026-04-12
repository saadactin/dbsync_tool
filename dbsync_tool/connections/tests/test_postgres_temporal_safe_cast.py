"""Tests for PostgreSQL date/timestamp decoding without Python datetime year overflow."""
from datetime import date, datetime

from django.test import TestCase

from connections.connectors.postgres import (
    _pg_temporal_leading_iso_year,
    _safe_pg_date_cast,
    _safe_pg_timestamp_cast,
)


class PostgresTemporalSafeCastTests(TestCase):
    def test_leading_iso_year(self):
        self.assertEqual(_pg_temporal_leading_iso_year("2024-01-01"), 2024)
        self.assertEqual(_pg_temporal_leading_iso_year("10000-01-01"), 10000)
        self.assertEqual(_pg_temporal_leading_iso_year("-4713-01-01"), -4713)

    def test_safe_date_cast_in_range(self):
        self.assertEqual(_safe_pg_date_cast("2024-06-15", None), date(2024, 6, 15))

    def test_safe_date_cast_year_10000_returns_string(self):
        s = "10000-01-01"
        self.assertEqual(_safe_pg_date_cast(s, None), s)

    def test_safe_timestamp_cast_in_range(self):
        dt = _safe_pg_timestamp_cast("9999-12-31 23:59:59.999999+00:00", None)
        self.assertIsInstance(dt, datetime)
        self.assertEqual(dt.year, 9999)

    def test_safe_timestamp_cast_year_10000_returns_string(self):
        s = "10000-01-01 00:00:00+00"
        self.assertEqual(_safe_pg_timestamp_cast(s, None), s)

    def test_safe_timestamp_cast_infinity_string(self):
        self.assertEqual(_safe_pg_timestamp_cast("infinity", None), "infinity")
