"""
Tests for Step 4 schedule: date/time fields and validate_schedule_start_inputs.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from sync_jobs.validators import (
    validate_interval_hours,
    validate_schedule_start_inputs,
)


class ValidateIntervalHoursTests(TestCase):
    def test_non_hourly_returns_one(self):
        self.assertEqual(validate_interval_hours("99", "daily"), 1)

    def test_hourly_empty_defaults_one(self):
        self.assertEqual(validate_interval_hours("", "hourly"), 1)

    def test_hourly_valid(self):
        self.assertEqual(validate_interval_hours("3", "hourly"), 3)

    def test_hourly_out_of_range(self):
        with self.assertRaises(ValidationError):
            validate_interval_hours("0", "hourly")
        with self.assertRaises(ValidationError):
            validate_interval_hours("25", "hourly")


class ValidateScheduleStartInputsTests(TestCase):
    def test_once_returns_none(self):
        self.assertIsNone(
            validate_schedule_start_inputs("", "", "", "once"),
        )

    def test_empty_date_time_returns_now_for_daily(self):
        dt = validate_schedule_start_inputs("", "", "", "daily")
        self.assertIsNotNone(dt)
        self.assertLessEqual(
            abs((dt - timezone.now()).total_seconds()),
            5.0,
        )

    def test_date_and_time_24h_future(self):
        future_date = (timezone.now() + timedelta(days=2)).date().isoformat()
        out = validate_schedule_start_inputs(
            "", future_date, "15:30", "daily"
        )
        self.assertEqual(out.hour, 15)
        self.assertEqual(out.minute, 30)

    def test_hidden_combined_string(self):
        future_date = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        combined = f"{future_date}T09:45"
        out = validate_schedule_start_inputs(combined, "", "", "hourly")
        self.assertEqual(out.hour, 9)
        self.assertEqual(out.minute, 45)

    def test_weekly_preserves_wall_time_with_normalize(self):
        from scheduler.utils import normalize_initial_next_run_for_schedule

        future_date = (timezone.now() + timedelta(days=10)).date().isoformat()
        raw = validate_schedule_start_inputs(
            "", future_date, "14:05", "weekly"
        )
        norm = normalize_initial_next_run_for_schedule("weekly", raw)
        self.assertEqual(norm.hour, 14)
        self.assertEqual(norm.minute, 5)
        self.assertGreater(norm, timezone.now())
