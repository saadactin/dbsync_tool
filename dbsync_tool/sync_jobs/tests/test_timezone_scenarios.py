"""
Timezone scenario tests for incremental sync
Tests incremental sync behavior with different timezones
"""
import unittest
from datetime import datetime, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone as django_timezone
import pytz

from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncCheckpoint
from connections.models import DatabaseConnection
from sync_engine.timezone_utils import TimezoneHandler
from sync_engine.checkpoint_manager import CheckpointManager


class TimezoneScenarioTestCase(TestCase):
    """Test timezone handling scenarios for incremental sync"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.timezone_handler = TimezoneHandler()
    
    def test_normalize_to_utc_naive_datetime(self):
        """Test normalizing naive datetime to UTC"""
        naive_dt = datetime(2024, 1, 1, 12, 0, 0)
        utc_dt = self.timezone_handler.normalize_to_utc(naive_dt)
        
        self.assertIsNotNone(utc_dt.tzinfo)
        self.assertEqual(utc_dt.tzinfo, pytz.UTC)
        self.assertEqual(utc_dt.replace(tzinfo=None), naive_dt)
    
    def test_normalize_to_utc_with_timezone(self):
        """Test normalizing datetime with timezone to UTC"""
        # Create datetime in America/New_York timezone
        ny_tz = pytz.timezone('America/New_York')
        ny_dt = ny_tz.localize(datetime(2024, 1, 1, 12, 0, 0))
        
        utc_dt = self.timezone_handler.normalize_to_utc(ny_dt)
        
        self.assertEqual(utc_dt.tzinfo, pytz.UTC)
        # Should be 5 hours ahead (EST is UTC-5)
        self.assertEqual(utc_dt.hour, 17)  # 12 + 5 = 17
    
    def test_normalize_to_utc_with_source_tz(self):
        """Test normalizing with specified source timezone"""
        naive_dt = datetime(2024, 1, 1, 12, 0, 0)
        utc_dt = self.timezone_handler.normalize_to_utc(
            naive_dt,
            source_tz='America/New_York'
        )
        
        self.assertEqual(utc_dt.tzinfo, pytz.UTC)
        self.assertEqual(utc_dt.hour, 17)  # EST is UTC-5
    
    def test_normalize_to_utc_string_iso_format(self):
        """Test normalizing ISO format string to UTC"""
        iso_string = '2024-01-01T12:00:00Z'
        utc_dt = self.timezone_handler.normalize_to_utc(iso_string)
        
        self.assertEqual(utc_dt.tzinfo, pytz.UTC)
        self.assertEqual(utc_dt.year, 2024)
        self.assertEqual(utc_dt.month, 1)
        self.assertEqual(utc_dt.day, 1)
        self.assertEqual(utc_dt.hour, 12)
    
    def test_normalize_to_utc_string_common_format(self):
        """Test normalizing common format string to UTC"""
        date_string = '2024-01-01 12:00:00'
        utc_dt = self.timezone_handler.normalize_to_utc(date_string)
        
        self.assertEqual(utc_dt.tzinfo, pytz.UTC)
        self.assertEqual(utc_dt.year, 2024)
        self.assertEqual(utc_dt.month, 1)
        self.assertEqual(utc_dt.day, 1)
    
    def test_format_for_comparison_postgres(self):
        """Test formatting checkpoint value for PostgreSQL"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        formatted = self.timezone_handler.format_for_comparison(dt, 'postgres')
        
        self.assertIn("'2024-01-01 12:00:00", formatted)
        self.assertIn("::timestamp", formatted)
    
    def test_format_for_comparison_mysql(self):
        """Test formatting checkpoint value for MySQL"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        formatted = self.timezone_handler.format_for_comparison(dt, 'mysql')
        
        self.assertIn("'2024-01-01 12:00:00", formatted)
        self.assertNotIn("::timestamp", formatted)
    
    def test_format_for_comparison_sqlserver(self):
        """Test formatting checkpoint value for SQL Server"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        formatted = self.timezone_handler.format_for_comparison(dt, 'sqlserver')
        
        self.assertIn("'2024-01-01 12:00:00", formatted)
        self.assertNotIn("::timestamp", formatted)
    
    def test_parse_checkpoint_value_timestamp(self):
        """Test parsing checkpoint value as timestamp"""
        # ISO format
        value = '2024-01-01T12:00:00+00:00'
        parsed = self.timezone_handler.parse_checkpoint_value(value, 'timestamp')
        
        self.assertIsInstance(parsed, datetime)
        self.assertEqual(parsed.year, 2024)
        self.assertEqual(parsed.month, 1)
        self.assertEqual(parsed.day, 1)
    
    def test_parse_checkpoint_value_integer(self):
        """Test parsing checkpoint value as integer"""
        value = '100'
        parsed = self.timezone_handler.parse_checkpoint_value(value, 'integer')
        
        self.assertIsInstance(parsed, int)
        self.assertEqual(parsed, 100)
    
    def test_parse_checkpoint_value_string(self):
        """Test parsing checkpoint value as string"""
        value = 'some_string_value'
        parsed = self.timezone_handler.parse_checkpoint_value(value, 'string')
        
        self.assertEqual(parsed, 'some_string_value')
    
    def test_parse_checkpoint_value_empty_string(self):
        """Test parsing empty checkpoint value"""
        value = ''
        parsed = self.timezone_handler.parse_checkpoint_value(value, 'timestamp')
        
        self.assertIsNone(parsed)
    
    def test_daylight_saving_time_transition(self):
        """Test handling daylight saving time transition"""
        # DST transition in America/New_York is typically in March/November
        ny_tz = pytz.timezone('America/New_York')
        
        # Before DST (EST, UTC-5)
        dt_before = ny_tz.localize(datetime(2024, 3, 9, 2, 0, 0))
        utc_before = self.timezone_handler.normalize_to_utc(dt_before)
        
        # After DST (EDT, UTC-4)
        dt_after = ny_tz.localize(datetime(2024, 3, 10, 2, 0, 0))
        utc_after = self.timezone_handler.normalize_to_utc(dt_after)
        
        # UTC difference should be 24 hours (not 25)
        self.assertEqual((utc_after - utc_before).total_seconds(), 86400)
    
    def test_mixed_timezone_normalization(self):
        """Test normalizing multiple timestamps with different timezones"""
        times = [
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC),
            pytz.timezone('America/New_York').localize(datetime(2024, 1, 1, 12, 0, 0)),
            pytz.timezone('Asia/Tokyo').localize(datetime(2024, 1, 1, 12, 0, 0)),
        ]
        
        normalized_times = [self.timezone_handler.normalize_to_utc(t) for t in times]
        
        # All should be UTC
        for dt in normalized_times:
            self.assertEqual(dt.tzinfo, pytz.UTC)
        
        # Times should be different in UTC
        self.assertNotEqual(normalized_times[0].hour, normalized_times[1].hour)
        self.assertNotEqual(normalized_times[0].hour, normalized_times[2].hour)
    
    def test_checkpoint_value_with_timezone(self):
        """Test checkpoint value handling with timezone information"""
        # Create job for testing
        source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user
        )
        
        target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user
        )
        
        job = SyncJob.objects.create(
            name='Test Timezone Job',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        checkpoint_manager = CheckpointManager(job)
        
        # Test with UTC datetime
        utc_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        checkpoint_manager.create_or_update_checkpoint(
            'public', 'test_table', utc_dt
        )
        
        checkpoint = checkpoint_manager.get_checkpoint('public', 'test_table')
        self.assertIsNotNone(checkpoint)
        self.assertIn('2024-01-01', checkpoint.last_value)
        
        # Parse back
        parsed = self.timezone_handler.parse_checkpoint_value(
            checkpoint.last_value, 'timestamp'
        )
        self.assertIsInstance(parsed, datetime)


if __name__ == '__main__':
    unittest.main()

