"""
Unit tests for query result verification (Day 4)

Tests comprehensive query result verification:
- Query result structure verification
- Query result data verification
- Transformation verification
- Query result comparison with target
- Edge case handling (NULL values, special characters, large datasets)
"""
from django.test import TestCase
from unittest.mock import Mock
from connections.connectors.base import DBConnector
from sync_engine.query_result_verifier import QueryResultVerifier
import logging

logger = logging.getLogger(__name__)


class QueryResultVerificationTest(TestCase):
    """Test query result verification"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_connector = Mock(spec=DBConnector)
        self.mock_connector.__class__.__name__ = 'PostgresConnector'
        self.verifier = QueryResultVerifier(self.mock_connector)
    
    def test_verify_structure_with_empty_result(self):
        """Test structure verification with empty result set"""
        is_valid, error_msg, structure_report = self.verifier.verify_query_result_structure(
            query_result=[],
            column_names=['id', 'name', 'email'],
            expected_row_count=0
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)
        self.assertEqual(structure_report['actual_row_count'], 0)
        self.assertTrue(structure_report['column_count_match'])
    
    def test_verify_structure_with_null_values(self):
        """Test structure verification with NULL values in data"""
        query_result = [
            (1, None, 'john@example.com'),
            (2, 'Jane Smith', None)
        ]
        
        is_valid, error_msg, structure_report = self.verifier.verify_query_result_structure(
            query_result=query_result,
            column_names=['id', 'name', 'email'],
            expected_row_count=2
        )
        
        self.assertTrue(is_valid)
        self.assertTrue(structure_report['row_count_match'])
        self.assertTrue(structure_report['column_count_match'])
    
    def test_verify_data_with_special_characters(self):
        """Test data verification with special characters and Unicode"""
        query_result = [
            (1, 'José García', 'josé@example.com'),
            (2, 'Müller', 'müller@example.com'),
            (3, '测试用户', 'test@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        is_valid, error_msg, data_report = self.verifier.verify_query_result_data(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertGreater(data_report['special_characters_found'], 0)
    
    def test_verify_data_with_mixed_data_types(self):
        """Test data verification with mixed data types"""
        from decimal import Decimal
        from datetime import datetime, date
        
        query_result = [
            (1, 'John Doe', Decimal('1000.50'), 30, True, date(2024, 1, 1), datetime(2024, 1, 1, 12, 0, 0)),
            (2, 'Jane Smith', Decimal('2000.75'), 35, False, date(2024, 2, 1), datetime(2024, 2, 1, 13, 0, 0))
        ]
        column_names = ['id', 'name', 'salary', 'age', 'is_active', 'hire_date', 'created_at']
        column_transformations = {}
        
        is_valid, error_msg, data_report = self.verifier.verify_query_result_data(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertEqual(data_report['rows_verified'], 2)
        self.assertTrue(data_report['data_types_verified'])
    
    def test_verify_transformations_with_multiple_columns(self):
        """Test transformation verification with multiple transformed columns"""
        query_result = [
            (1, 'JOHN DOE', 'john@example.com', '  trimmed  '),
            (2, 'JANE SMITH', 'jane@example.com', '  also trimmed  ')
        ]
        column_names = ['id', 'name', 'email', 'description']
        column_transformations = {
            'name': 'UPPER',
            'email': 'LOWER',
            'description': 'TRIM'
        }
        
        is_valid, error_msg = self.verifier.verify_transformations_applied(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)
    
    def test_compare_results_handles_decimal_precision(self):
        """Test comparison handles Decimal precision correctly"""
        from decimal import Decimal
        
        source_query_result = [
            (1, Decimal('1000.50')),
            (2, Decimal('2000.75'))
        ]
        target_rows = [
            (1, 1000.50),  # Float instead of Decimal
            (2, 2000.75)
        ]
        column_names = ['id', 'amount']
        column_transformations = {}
        
        matches, error_msg, comparison_report = self.verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # Should match despite type difference (normalized)
        self.assertTrue(matches)
    
    def test_compare_results_handles_datetime(self):
        """Test comparison handles datetime objects correctly"""
        from datetime import datetime
        
        source_query_result = [
            (1, datetime(2024, 1, 1, 12, 0, 0)),
            (2, datetime(2024, 2, 1, 13, 0, 0))
        ]
        target_rows = [
            (1, datetime(2024, 1, 1, 12, 0, 0)),
            (2, datetime(2024, 2, 1, 13, 0, 0))
        ]
        column_names = ['id', 'created_at']
        column_transformations = {}
        
        matches, error_msg, comparison_report = self.verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(matches)
    
    def test_compare_results_handles_null_values(self):
        """Test comparison handles NULL values correctly"""
        source_query_result = [
            (1, None, 'john@example.com'),
            (2, 'Jane Smith', None)
        ]
        target_rows = [
            (1, None, 'john@example.com'),
            (2, 'Jane Smith', None)
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        matches, error_msg, comparison_report = self.verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(matches)
    
    def test_compare_results_detects_null_mismatch(self):
        """Test comparison detects NULL value mismatches"""
        source_query_result = [
            (1, None, 'john@example.com'),
            (2, 'Jane Smith', None)
        ]
        target_rows = [
            (1, 'John Doe', 'john@example.com'),  # NULL vs non-NULL
            (2, 'Jane Smith', 'jane@example.com')  # NULL vs non-NULL
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        matches, error_msg, comparison_report = self.verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertFalse(matches)
        self.assertGreater(len(comparison_report['mismatched_rows']), 0)
    
    def test_compare_results_handles_large_datasets(self):
        """Test comparison handles large datasets efficiently"""
        # Create large result sets
        source_query_result = [(i, f'User {i}', f'user{i}@example.com') for i in range(1000)]
        target_rows = [(i, f'User {i}', f'user{i}@example.com') for i in range(1000)]
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        matches, error_msg, comparison_report = self.verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(matches)
        self.assertTrue(comparison_report['rows_match'])
    
    def test_normalize_value_for_comparison_trim(self):
        """Test value normalization with TRIM transformation"""
        normalized = self.verifier._normalize_value_for_comparison('  test  ', 'TRIM')
        self.assertEqual(normalized, 'test')
    
    def test_normalize_value_for_comparison_upper(self):
        """Test value normalization with UPPER transformation"""
        normalized = self.verifier._normalize_value_for_comparison('test', 'UPPER')
        self.assertEqual(normalized, 'TEST')
    
    def test_normalize_value_for_comparison_lower(self):
        """Test value normalization with LOWER transformation"""
        normalized = self.verifier._normalize_value_for_comparison('TEST', 'LOWER')
        self.assertEqual(normalized, 'test')
    
    def test_normalize_value_for_comparison_decimal(self):
        """Test value normalization with Decimal"""
        from decimal import Decimal
        
        normalized = self.verifier._normalize_value_for_comparison(Decimal('1000.50'), None)
        self.assertEqual(normalized, 1000.50)
        self.assertIsInstance(normalized, float)
    
    def test_values_equal_handles_floating_point(self):
        """Test value equality handles floating point precision"""
        # Should allow small differences
        self.assertTrue(self.verifier._values_equal(1000.50, 1000.5001))
        self.assertFalse(self.verifier._values_equal(1000.50, 1000.60))
    
    def test_values_equal_handles_none(self):
        """Test value equality handles None values"""
        self.assertTrue(self.verifier._values_equal(None, None))
        self.assertFalse(self.verifier._values_equal(None, 'value'))
        self.assertFalse(self.verifier._values_equal('value', None))
