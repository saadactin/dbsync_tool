"""
Tests for data validators
"""
import unittest
from sync_engine.validators import DataValidator
from sync_engine.exceptions import ValidationError as SyncValidationError
from connections.connectors.base import ColumnInfo


class TestDataValidator(unittest.TestCase):
    """Test cases for DataValidator"""
    
    def test_validate_row_count_match(self):
        """Test row count validation when counts match"""
        # Should not raise any exception
        DataValidator.validate_row_count(100, 100, 'test_table')
    
    def test_validate_row_count_mismatch_non_strict(self):
        """Test row count validation when counts don't match (non-strict)"""
        # Should log warning but not raise exception
        DataValidator.validate_row_count(100, 90, 'test_table', strict=False)
    
    def test_validate_row_count_mismatch_strict(self):
        """Test row count validation when counts don't match (strict)"""
        with self.assertRaises(SyncValidationError):
            DataValidator.validate_row_count(100, 90, 'test_table', strict=True)
    
    def test_validate_data_types_match(self):
        """Test data type validation when row length matches columns"""
        row = (1, 'test', 3.14)
        columns = [
            ColumnInfo('id', 'int', False),
            ColumnInfo('name', 'varchar', True),
            ColumnInfo('value', 'float', True)
        ]
        # Should not raise any exception
        DataValidator.validate_data_types(row, columns, 'test_table')
    
    def test_validate_data_types_mismatch(self):
        """Test data type validation when row length doesn't match columns"""
        row = (1, 'test')
        columns = [
            ColumnInfo('id', 'int', False),
            ColumnInfo('name', 'varchar', True),
            ColumnInfo('value', 'float', True)
        ]
        with self.assertRaises(SyncValidationError):
            DataValidator.validate_data_types(row, columns, 'test_table')
    
    def test_sanitize_batch_within_limit(self):
        """Test batch sanitization when batch is within limit"""
        rows = [(1,), (2,), (3,)]
        result = DataValidator.sanitize_batch(rows, max_batch_size=5000)
        self.assertEqual(len(result), 3)
        self.assertEqual(result, rows)
    
    def test_sanitize_batch_exceeds_limit(self):
        """Test batch sanitization when batch exceeds limit"""
        rows = [(i,) for i in range(10000)]
        result = DataValidator.sanitize_batch(rows, max_batch_size=5000)
        self.assertEqual(len(result), 5000)
        self.assertEqual(result, rows[:5000])
    
    def test_validate_batch_not_empty_with_rows(self):
        """Test batch validation when batch has rows"""
        rows = [(1,), (2,), (3,)]
        # Should not raise any exception
        DataValidator.validate_batch_not_empty(rows, 'test_table')
    
    def test_validate_batch_not_empty_empty(self):
        """Test batch validation when batch is empty"""
        rows = []
        with self.assertRaises(SyncValidationError):
            DataValidator.validate_batch_not_empty(rows, 'test_table')


if __name__ == '__main__':
    unittest.main()

