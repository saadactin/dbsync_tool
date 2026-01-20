"""
Unit tests for DataIntegrityVerifier service
"""
from django.test import TestCase
from unittest.mock import Mock, patch
from connections.connectors.base import DBConnector
from sync_engine.data_integrity_verifier import DataIntegrityVerifier
from sync_jobs.models import SyncJobTable
from decimal import Decimal


class DataIntegrityVerifierTest(TestCase):
    """Test DataIntegrityVerifier class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.source_connector = Mock(spec=DBConnector)
        self.source_connector.__class__.__name__ = 'PostgresConnector'
        self.target_connector = Mock(spec=DBConnector)
        self.target_connector.__class__.__name__ = 'PostgresConnector'
        
        self.verifier = DataIntegrityVerifier(
            self.source_connector,
            self.target_connector
        )
        
        # Create a mock job_table for tests that need it
        self.job_table = Mock(spec=SyncJobTable)
        self.job_table.schema_name = 'public'
        self.job_table.table_name = 'users'
        self.job_table.transformation_query = "age >= 30"
        self.job_table.column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
    
    def test_init(self):
        """Test DataIntegrityVerifier initialization"""
        verifier = DataIntegrityVerifier(
            self.source_connector,
            self.target_connector
        )
        self.assertEqual(verifier.source_connector, self.source_connector)
        self.assertEqual(verifier.target_connector, self.target_connector)
    
    def test_compare_row_counts_match(self):
        """Test row count comparison when counts match"""
        self.target_connector.get_row_count = Mock(return_value=5)
        
        matches, error, actual_count = self.verifier._compare_row_counts(
            target_schema='public',
            table='users',
            expected_count=5
        )
        
        self.assertTrue(matches)
        self.assertIsNone(error)
        self.assertEqual(actual_count, 5)
    
    def test_compare_row_counts_mismatch(self):
        """Test row count comparison when counts don't match"""
        self.target_connector.get_row_count = Mock(return_value=3)
        
        matches, error, actual_count = self.verifier._compare_row_counts(
            target_schema='public',
            table='users',
            expected_count=5
        )
        
        self.assertFalse(matches)
        self.assertIsNotNone(error)
        self.assertIn('mismatch', error.lower())
        self.assertEqual(actual_count, 3)
    
    def test_normalize_value_trim(self):
        """Test value normalization with TRIM transformation"""
        value = "  John Doe  "
        normalized = self.verifier._normalize_value(value, 'TRIM')
        self.assertEqual(normalized, "John Doe")
    
    def test_normalize_value_upper(self):
        """Test value normalization with UPPER transformation"""
        value = "john@example.com"
        normalized = self.verifier._normalize_value(value, 'UPPER')
        self.assertEqual(normalized, "JOHN@EXAMPLE.COM")
    
    def test_normalize_value_lower(self):
        """Test value normalization with LOWER transformation"""
        value = "JOHN@EXAMPLE.COM"
        normalized = self.verifier._normalize_value(value, 'LOWER')
        self.assertEqual(normalized, "john@example.com")
    
    def test_normalize_value_decimal(self):
        """Test value normalization with Decimal"""
        value = Decimal('100.50')
        normalized = self.verifier._normalize_value(value, None)
        self.assertEqual(normalized, 100.5)
        self.assertIsInstance(normalized, float)
    
    def test_normalize_value_null(self):
        """Test value normalization with NULL"""
        normalized = self.verifier._normalize_value(None, None)
        self.assertIsNone(normalized)
    
    def test_values_equal_numeric(self):
        """Test value equality for numeric types"""
        self.assertTrue(self.verifier._values_equal(100, 100))
        self.assertTrue(self.verifier._values_equal(100.0, 100))
        self.assertTrue(self.verifier._values_equal(Decimal('100.0'), 100))
        self.assertFalse(self.verifier._values_equal(100, 101))
    
    def test_values_equal_string(self):
        """Test value equality for string types"""
        self.assertTrue(self.verifier._values_equal("test", "test"))
        self.assertFalse(self.verifier._values_equal("test", "TEST"))
    
    def test_values_equal_null(self):
        """Test value equality with NULL values"""
        self.assertTrue(self.verifier._values_equal(None, None))
        self.assertFalse(self.verifier._values_equal(None, "test"))
        self.assertFalse(self.verifier._values_equal("test", None))
    
    def test_compare_row_values_match(self):
        """Test row value comparison when values match"""
        source_row = (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30)
        target_row = (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30)
        column_names = ['id', 'name', 'email', 'age']
        column_transformations = {}
        
        matches, error = self.verifier._compare_row_values(
            source_row=source_row,
            target_row=target_row,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(matches)
        self.assertIsNone(error)
    
    def test_compare_row_values_mismatch(self):
        """Test row value comparison when values don't match"""
        source_row = (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30)
        target_row = (1, 'John Doe', 'john@example.com', 30)  # Different email
        column_names = ['id', 'name', 'email', 'age']
        column_transformations = {}
        
        matches, error = self.verifier._compare_row_values(
            source_row=source_row,
            target_row=target_row,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertFalse(matches)
        self.assertIsNotNone(error)
        self.assertIn('email', error.lower())
    
    def test_compare_row_values_with_transformations(self):
        """Test row value comparison with transformations"""
        # Source has transformations applied (UPPER email)
        source_row = (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30)
        # Target should match (email already uppercase)
        target_row = (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30)
        column_names = ['id', 'name', 'email', 'age']
        column_transformations = {'email': 'UPPER'}
        
        matches, error = self.verifier._compare_row_values(
            source_row=source_row,
            target_row=target_row,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(matches)
    
    @patch('sync_engine.data_integrity_verifier.QueryBuilder.get_db_type')
    def test_verify_data_accuracy_success(self, mock_get_db_type):
        """Test successful data accuracy verification"""
        mock_get_db_type.return_value = 'postgres'
        
        # Mock row count comparison
        self.verifier._compare_row_counts = Mock(return_value=(True, None, 5))
        
        # Mock row-by-row comparison
        self.verifier._compare_rows = Mock(return_value=(
            True,
            None,
            {'mismatched_rows': [], 'mismatched_columns': []}
        ))
        
        is_accurate, error, report = self.verifier.verify_data_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=5,
            column_names=['id', 'name', 'email', 'age']
        )
        
        self.assertTrue(is_accurate)
        self.assertIsNone(error)
        self.assertIsNotNone(report)
        self.assertTrue(report['row_count_match'])
        self.assertTrue(report['all_rows_match'])
    
    @patch('sync_engine.data_integrity_verifier.QueryBuilder.get_db_type')
    def test_verify_data_accuracy_row_count_mismatch(self, mock_get_db_type):
        """Test data accuracy verification with row count mismatch"""
        mock_get_db_type.return_value = 'postgres'
        
        # Mock row count comparison to fail
        self.verifier._compare_row_counts = Mock(return_value=(
            False,
            "Row count mismatch: expected 5, got 3",
            3
        ))
        
        is_accurate, error, report = self.verifier.verify_data_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=5,
            column_names=['id', 'name', 'email', 'age']
        )
        
        self.assertFalse(is_accurate)
        self.assertIsNotNone(error)
        self.assertIn('mismatch', error.lower())
        self.assertFalse(report['row_count_match'])
    
    @patch('sync_engine.data_integrity_verifier.QueryBuilder.get_db_type')
    def test_verify_data_accuracy_row_comparison_failure(self, mock_get_db_type):
        """Test data accuracy verification with row comparison failure"""
        mock_get_db_type.return_value = 'postgres'
        
        # Mock row count comparison to succeed
        self.verifier._compare_row_counts = Mock(return_value=(True, None, 5))
        
        # Mock row-by-row comparison to fail
        self.verifier._compare_rows = Mock(return_value=(
            False,
            "Row mismatch at row 0",
            {'mismatched_rows': [{'row_index': 0, 'error': 'Column mismatch'}], 'mismatched_columns': []}
        ))
        
        is_accurate, error, report = self.verifier.verify_data_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=5,
            column_names=['id', 'name', 'email', 'age']
        )
        
        self.assertFalse(is_accurate)
        self.assertIsNotNone(error)
        self.assertIn('comparison', error.lower())
        self.assertFalse(report['all_rows_match'])
