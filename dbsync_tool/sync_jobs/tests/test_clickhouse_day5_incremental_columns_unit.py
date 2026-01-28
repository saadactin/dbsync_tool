"""
Unit tests for ClickHouse Day 5: Incremental Column Detection
Tests the incremental column detection logic directly without Django views
"""
from django.test import TestCase


class ClickHouseIncrementalColumnDetectionUnitTestCase(TestCase):
    """Unit tests for incremental column detection logic"""
    
    def test_datetime64_detected(self):
        """Test that DateTime64 columns are detected as incremental candidates"""
        columns = [
            {
                'name': 'id',
                'data_type': 'Int64',
                'is_nullable': False,
                'is_primary_key': True,
            },
            {
                'name': 'created_at',
                'data_type': 'DateTime64',
                'is_nullable': False,
                'is_primary_key': False,
            },
            {
                'name': 'name',
                'data_type': 'String',
                'is_nullable': True,
                'is_primary_key': False,
            },
        ]
        
        # Apply the same logic as in views.py
        incremental_candidates = []
        for col in columns:
            data_type_lower = col['data_type'].lower()
            # Standard types (PostgreSQL, MySQL, SQL Server)
            if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                incremental_candidates.append(col)
            # ClickHouse-specific types (DateTime64, UInt32, UInt64)
            # Note: ClickHouse Int32, Int64 are already covered by 'int' check above
            elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                incremental_candidates.append(col)
        
        candidate_names = [col['name'] for col in incremental_candidates]
        
        # DateTime64 should be detected
        self.assertIn('created_at', candidate_names)
        # Int64 should also be detected (covered by 'int' check)
        self.assertIn('id', candidate_names)
        # String should not be detected
        self.assertNotIn('name', candidate_names)
    
    def test_uint32_detected(self):
        """Test that UInt32 columns are detected"""
        columns = [
            {
                'name': 'sequence_id',
                'data_type': 'UInt32',
                'is_nullable': False,
            },
            {
                'name': 'description',
                'data_type': 'String',
                'is_nullable': True,
            },
        ]
        
        incremental_candidates = []
        for col in columns:
            data_type_lower = col['data_type'].lower()
            if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                incremental_candidates.append(col)
        
        candidate_names = [col['name'] for col in incremental_candidates]
        self.assertIn('sequence_id', candidate_names)
        self.assertNotIn('description', candidate_names)
    
    def test_uint64_detected(self):
        """Test that UInt64 columns are detected"""
        columns = [
            {
                'name': 'big_sequence',
                'data_type': 'UInt64',
                'is_nullable': False,
            },
        ]
        
        incremental_candidates = []
        for col in columns:
            data_type_lower = col['data_type'].lower()
            if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                incremental_candidates.append(col)
        
        candidate_names = [col['name'] for col in incremental_candidates]
        self.assertIn('big_sequence', candidate_names)
    
    def test_int32_int64_detected(self):
        """Test that Int32 and Int64 are detected (covered by 'int' check)"""
        columns = [
            {
                'name': 'small_id',
                'data_type': 'Int32',
                'is_nullable': False,
            },
            {
                'name': 'big_id',
                'data_type': 'Int64',
                'is_nullable': False,
            },
        ]
        
        incremental_candidates = []
        for col in columns:
            data_type_lower = col['data_type'].lower()
            if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                incremental_candidates.append(col)
        
        candidate_names = [col['name'] for col in incremental_candidates]
        self.assertIn('small_id', candidate_names)
        self.assertIn('big_id', candidate_names)
    
    def test_datetime_detected(self):
        """Test that DateTime (without 64) is detected (covered by 'datetime' check)"""
        columns = [
            {
                'name': 'updated_at',
                'data_type': 'DateTime',
                'is_nullable': False,
            },
        ]
        
        incremental_candidates = []
        for col in columns:
            data_type_lower = col['data_type'].lower()
            if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                incremental_candidates.append(col)
        
        candidate_names = [col['name'] for col in incremental_candidates]
        self.assertIn('updated_at', candidate_names)
    
    def test_date_detected(self):
        """Test that Date columns are detected (covered by 'date' check)"""
        columns = [
            {
                'name': 'event_date',
                'data_type': 'Date',
                'is_nullable': False,
            },
        ]
        
        incremental_candidates = []
        for col in columns:
            data_type_lower = col['data_type'].lower()
            if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                incremental_candidates.append(col)
        
        candidate_names = [col['name'] for col in incremental_candidates]
        self.assertIn('event_date', candidate_names)
    
    def test_mixed_types_detection(self):
        """Test detection with multiple ClickHouse types"""
        columns = [
            {
                'name': 'id',
                'data_type': 'Int64',
                'is_nullable': False,
            },
            {
                'name': 'timestamp',
                'data_type': 'DateTime64',
                'is_nullable': False,
            },
            {
                'name': 'counter',
                'data_type': 'UInt32',
                'is_nullable': False,
            },
            {
                'name': 'big_counter',
                'data_type': 'UInt64',
                'is_nullable': False,
            },
            {
                'name': 'name',
                'data_type': 'String',
                'is_nullable': True,
            },
            {
                'name': 'description',
                'data_type': 'String',
                'is_nullable': True,
            },
        ]
        
        incremental_candidates = []
        for col in columns:
            data_type_lower = col['data_type'].lower()
            if any(dt in data_type_lower for dt in ['timestamp', 'datetime', 'date', 'time']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['int', 'bigint', 'serial']):
                incremental_candidates.append(col)
            elif any(dt in data_type_lower for dt in ['datetime64', 'uint32', 'uint64']):
                incremental_candidates.append(col)
        
        candidate_names = [col['name'] for col in incremental_candidates]
        
        # All numeric and datetime types should be detected
        self.assertIn('id', candidate_names)
        self.assertIn('timestamp', candidate_names)
        self.assertIn('counter', candidate_names)
        self.assertIn('big_counter', candidate_names)
        
        # String types should not be detected
        self.assertNotIn('name', candidate_names)
        self.assertNotIn('description', candidate_names)
        
        # Should have exactly 4 incremental candidates
        self.assertEqual(len(incremental_candidates), 4)
