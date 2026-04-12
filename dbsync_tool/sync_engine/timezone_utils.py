"""
Timezone handling utilities for incremental sync
Ensures accurate timestamp comparisons across different timezones
"""
from typing import Any, Optional
from datetime import datetime
import pytz
from django.utils import timezone as django_timezone
import logging

logger = logging.getLogger(__name__)

class TimezoneHandler:
    """Handles timezone conversions for checkpoint values"""
    
    @staticmethod
    def normalize_to_utc(value: Any, source_tz: Optional[str] = None) -> datetime:
        """
        Normalize timestamp value to UTC
        
        Args:
            value: Timestamp value (datetime, string, etc.)
            source_tz: Source timezone (e.g., 'America/New_York')
                     If None, assumes UTC or system default
            
        Returns:
            datetime object in UTC
            
        Raises:
            ValueError: If value cannot be parsed
        """
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            # Try to parse string
            try:
                # Try ISO format first
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                # Try common formats
                formats = [
                    '%Y-%m-%d %H:%M:%S.%f',
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d',
                    '%Y/%m/%d %H:%M:%S',
                ]
                dt = None
                for fmt in formats:
                    try:
                        dt = datetime.strptime(value, fmt)
                        break
                    except ValueError:
                        continue
                
                if dt is None:
                    raise ValueError(f"Cannot parse timestamp: {value}")
        else:
            raise ValueError(f"Unsupported timestamp type: {type(value)}")
        
        # Convert to UTC if timezone-aware
        if dt.tzinfo is None:
            # Assume source timezone if provided, else use UTC
            if source_tz:
                try:
                    source_tz_obj = pytz.timezone(source_tz)
                    dt = source_tz_obj.localize(dt)
                except pytz.exceptions.UnknownTimeZoneError:
                    logger.warning(f"Unknown timezone: {source_tz}, assuming UTC")
                    dt = pytz.UTC.localize(dt)
            else:
                # Assume UTC for naive datetimes
                dt = pytz.UTC.localize(dt)
        
        # Convert to UTC
        return dt.astimezone(pytz.UTC)
    
    @staticmethod
    def format_for_comparison(value: Any, db_type: str) -> str:
        """
        Format timestamp value for database comparison
        
        Args:
            value: Timestamp value (datetime, string, etc.)
            db_type: Database type ('postgres', 'mysql', 'sqlserver')
            
        Returns:
            Formatted string for SQL query
        """
        if isinstance(value, datetime):
            # Ensure UTC
            if value.tzinfo is None:
                value = pytz.UTC.localize(value)
            else:
                value = value.astimezone(pytz.UTC)
            
            # Format based on database type
            if db_type == 'postgres':
                # PostgreSQL timestamp format
                return value.strftime("'%Y-%m-%d %H:%M:%S.%f'::timestamp")
            elif db_type == 'mysql':
                # MySQL datetime format
                return value.strftime("'%Y-%m-%d %H:%M:%S.%f'")
            elif db_type == 'sqlserver':
                # SQL Server datetime2 format
                return value.strftime("'%Y-%m-%d %H:%M:%S.%f'")
            else:
                return value.isoformat()
        elif isinstance(value, str):
            # Try to parse and format
            try:
                dt = TimezoneHandler.normalize_to_utc(value)
                return TimezoneHandler.format_for_comparison(dt, db_type)
            except ValueError:
                # Return as-is if can't parse
                return f"'{value}'"
        else:
            return str(value)
    
    @staticmethod
    def parse_checkpoint_value(
        value_str: str,
        column_type: str = 'timestamp'
    ) -> Any:
        """
        Parse checkpoint value from string storage
        
        Args:
            value_str: Checkpoint value as string
            column_type: Column data type ('timestamp', 'integer', 'string')
            
        Returns:
            Parsed value (datetime, int, or string)
        """
        if not value_str:
            return None
        if isinstance(value_str, str) and value_str.strip().lower() in {"none", "null", "nan"}:
            return None
        
        ct = (column_type or "").lower()
        # Treat any "datetime-like" type token (including ClickHouse datetime64*) as datetime.
        datetime_like_tokens = (
            "timestamp",
            "datetime",
            "datetime64",
            "date",
            "timestamptz",
            "time",
        )
        if any(tok in ct for tok in datetime_like_tokens):
            try:
                # Try ISO format first
                return datetime.fromisoformat(value_str.replace('Z', '+00:00'))
            except ValueError:
                # Try other formats
                formats = [
                    '%Y-%m-%d %H:%M:%S.%f',
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d',
                ]
                for fmt in formats:
                    try:
                        dt = datetime.strptime(value_str, fmt)
                        # Assume UTC if naive
                        if dt.tzinfo is None:
                            dt = pytz.UTC.localize(dt)
                        return dt
                    except ValueError:
                        continue
                # Return as string if can't parse
                logger.warning(f"Could not parse timestamp: {value_str}")
                return value_str
        elif column_type in ['integer', 'int', 'bigint', 'serial']:
            try:
                return int(value_str)
            except ValueError:
                logger.warning(f"Could not parse integer: {value_str}")
                return value_str
        elif column_type in ['float', 'double', 'numeric', 'decimal']:
            try:
                return float(value_str)
            except ValueError:
                logger.warning(f"Could not parse float: {value_str}")
                return value_str
        else:
            # String or unknown type
            return value_str
    
    @staticmethod
    def get_current_utc_timestamp() -> datetime:
        """
        Get current UTC timestamp
        
        Returns:
            Current datetime in UTC
        """
        return django_timezone.now()

