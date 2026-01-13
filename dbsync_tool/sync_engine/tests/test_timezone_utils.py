"""
Tests for timezone utilities
"""
from django.test import TestCase
from datetime import datetime
import pytz
from sync_engine.timezone_utils import TimezoneHandler

class TimezoneHandlerTestCase(TestCase):
    """Test cases for TimezoneHandler"""
    
    def test_normalize_to_utc_datetime(self):
        """Test normalizing datetime to UTC"""
        # Naive datetime
        dt = datetime(2024, 1, 1, 12, 0, 0)
        utc_dt = TimezoneHandler.normalize_to_utc(dt)
        self.assertIsNotNone(utc_dt.tzinfo)
        self.assertEqual(utc_dt.tzinfo, pytz.UTC)
    
    def test_normalize_to_utc_string(self):
        """Test normalizing string timestamp to UTC"""
        # ISO format
        dt = TimezoneHandler.normalize_to_utc('2024-01-01T12:00:00Z')
        self.assertEqual(dt.tzinfo, pytz.UTC)
        
        # Custom format
        dt = TimezoneHandler.normalize_to_utc('2024-01-01 12:00:00')
        self.assertEqual(dt.tzinfo, pytz.UTC)
    
    def test_normalize_with_timezone(self):
        """Test normalizing with source timezone"""
        # EST timezone (UTC-5)
        dt = TimezoneHandler.normalize_to_utc(
            '2024-01-01 12:00:00',
            source_tz='America/New_York'
        )
        self.assertEqual(dt.tzinfo, pytz.UTC)
        # Should be 5 hours ahead (EST is UTC-5 in January)
        self.assertEqual(dt.hour, 17)  # 12 + 5 = 17
    
    def test_normalize_timezone_aware_datetime(self):
        """Test normalizing timezone-aware datetime"""
        # Create timezone-aware datetime
        est = pytz.timezone('America/New_York')
        dt = est.localize(datetime(2024, 1, 1, 12, 0, 0))
        utc_dt = TimezoneHandler.normalize_to_utc(dt)
        self.assertEqual(utc_dt.tzinfo, pytz.UTC)
        self.assertEqual(utc_dt.hour, 17)
    
    def test_normalize_invalid_timezone(self):
        """Test normalizing with invalid timezone"""
        # Should fall back to UTC
        dt = TimezoneHandler.normalize_to_utc(
            '2024-01-01 12:00:00',
            source_tz='Invalid/Timezone'
        )
        self.assertEqual(dt.tzinfo, pytz.UTC)
    
    def test_normalize_invalid_format(self):
        """Test normalizing with invalid format"""
        with self.assertRaises(ValueError):
            TimezoneHandler.normalize_to_utc('invalid-date')
    
    def test_format_for_comparison_postgres(self):
        """Test formatting for PostgreSQL"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        formatted = TimezoneHandler.format_for_comparison(dt, 'postgres')
        self.assertIn('::timestamp', formatted)
        self.assertIn('2024-01-01', formatted)
    
    def test_format_for_comparison_mysql(self):
        """Test formatting for MySQL"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        formatted = TimezoneHandler.format_for_comparison(dt, 'mysql')
        self.assertIn('2024-01-01', formatted)
        self.assertNotIn('::timestamp', formatted)
    
    def test_format_for_comparison_sqlserver(self):
        """Test formatting for SQL Server"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        formatted = TimezoneHandler.format_for_comparison(dt, 'sqlserver')
        self.assertIn('2024-01-01', formatted)
    
    def test_format_for_comparison_string(self):
        """Test formatting string timestamp"""
        formatted = TimezoneHandler.format_for_comparison(
            '2024-01-01 12:00:00',
            'postgres'
        )
        self.assertIn('2024-01-01', formatted)
    
    def test_format_for_comparison_naive_datetime(self):
        """Test formatting naive datetime"""
        dt = datetime(2024, 1, 1, 12, 0, 0)
        formatted = TimezoneHandler.format_for_comparison(dt, 'postgres')
        self.assertIn('2024-01-01', formatted)
        # Should be converted to UTC
        self.assertIn('::timestamp', formatted)
    
    def test_parse_checkpoint_value_timestamp(self):
        """Test parsing timestamp checkpoint value"""
        value = TimezoneHandler.parse_checkpoint_value(
            '2024-01-01 12:00:00',
            'timestamp'
        )
        self.assertIsInstance(value, datetime)
    
    def test_parse_checkpoint_value_timestamp_iso(self):
        """Test parsing ISO format timestamp"""
        value = TimezoneHandler.parse_checkpoint_value(
            '2024-01-01T12:00:00Z',
            'timestamp'
        )
        self.assertIsInstance(value, datetime)
    
    def test_parse_checkpoint_value_integer(self):
        """Test parsing integer checkpoint value"""
        value = TimezoneHandler.parse_checkpoint_value('100', 'integer')
        self.assertEqual(value, 100)
        self.assertIsInstance(value, int)
    
    def test_parse_checkpoint_value_float(self):
        """Test parsing float checkpoint value"""
        value = TimezoneHandler.parse_checkpoint_value('100.5', 'float')
        self.assertEqual(value, 100.5)
        self.assertIsInstance(value, float)
    
    def test_parse_checkpoint_value_string(self):
        """Test parsing string checkpoint value"""
        value = TimezoneHandler.parse_checkpoint_value('test_value', 'varchar')
        self.assertEqual(value, 'test_value')
    
    def test_parse_checkpoint_value_none(self):
        """Test parsing None checkpoint value"""
        value = TimezoneHandler.parse_checkpoint_value('', 'timestamp')
        self.assertIsNone(value)
    
    def test_parse_checkpoint_value_invalid_integer(self):
        """Test parsing invalid integer"""
        value = TimezoneHandler.parse_checkpoint_value('not_a_number', 'integer')
        # Should return as string
        self.assertEqual(value, 'not_a_number')
    
    def test_get_current_utc_timestamp(self):
        """Test getting current UTC timestamp"""
        dt = TimezoneHandler.get_current_utc_timestamp()
        self.assertIsNotNone(dt.tzinfo)
        # Django timezone.now() returns timezone-aware datetime
        self.assertIsNotNone(dt.tzinfo)

