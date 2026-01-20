"""
Unit tests for Day 6 - Perfect Migration (no database required)

Tests the logic of perfect migration features using mocks:
- Query execution before migration
- Query result storage and comparison
- Perfect accuracy verification
"""
from django.test import TestCase
from unittest.mock import Mock, patch, MagicMock
from connections.connectors.base import DBConnector
from sync_engine.pre_migration_validator import PreMigrationValidator
from sync_engine.query_result_verifier import QueryResultVerifier
from sync_engine.data_integrity_verifier import DataIntegrityVerifier
from sync_jobs.models import SyncJobTable
import logging

logger = logging.getLogger(__name__)


class PerfectMigrationUnitDay6Test(TestCase):
    """Unit tests for perfect migration (no database required)"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_connector = Mock(spec=DBConnector)
        self.mock_connector.__class__.__name__ = 'PostgresConnector'
        
        # Create mock job_table
        self.job_table = Mock(spec=SyncJobTable)
        self.job_table.schema_name = 'public'
        self.job_table.table_name = 'users'
        self.job_table.transformation_query = "age >= 30"
        self.job_table.column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
    
    def test_pre_migration_validator_stores_query_results(self):
        """Test that pre-migration validator stores query results"""
        validator = PreMigrationValidator(self.mock_connector)
        
        # Mock query execution
        mock_query_results = [
            (1, 'John Doe', 'john@example.com', 35),
            (2, 'Jane Smith', 'jane@example.com', 40),
            (3, 'Bob Wilson', 'bob@example.com', 45)
        ]
        
        self.mock_connector.fetch_batch.return_value = mock_query_results
        
        # Mock QueryBuilder
        with patch('sync_engine.pre_migration_validator.QueryBuilder') as mock_qb:
            mock_qb.get_db_type.return_value = 'postgres'
            
            # Mock query result verifier (it's imported inside the method)
            with patch('sync_engine.query_result_verifier.QueryResultVerifier') as mock_qrv_class:
                mock_verifier = Mock()
                mock_verifier.verify_query_result_structure.return_value = (True, None, {'row_count_match': True})
                mock_verifier.verify_query_result_data.return_value = (True, None, {'rows_verified': 3})
                mock_verifier.verify_transformations_applied.return_value = (True, None)
                mock_qrv_class.return_value = mock_verifier
                
                # Mock _get_expected_row_count
                validator._get_expected_row_count = Mock(return_value=3)
                
                # Call validate_transformation_query
                is_valid, error_msg, validation_report = validator.validate_transformation_query(
                    job_table=self.job_table,
                    transformed_query="SELECT * FROM users WHERE age >= 30",
                    base_query="SELECT * FROM users",
                    column_names=['id', 'name', 'email', 'age']
                )
                
                # Verify query results were stored
                self.assertTrue(is_valid)
                self.assertIn('query_results', validation_report)
                self.assertEqual(len(validation_report['query_results']), 3)
                self.assertEqual(validation_report['query_result_count'], 3)
                self.assertIn('query_execution_time', validation_report)
                self.assertTrue(validation_report.get('structure_verified', False))
                self.assertTrue(validation_report.get('data_verified', False))
    
    def test_query_result_verifier_compares_correctly(self):
        """Test that query result verifier compares results correctly"""
        verifier = QueryResultVerifier(self.mock_connector)
        
        # Create mock query results
        source_query_result = [
            (1, 'John Doe', 'john@example.com'),
            (2, 'Jane Smith', 'jane@example.com')
        ]
        
        target_rows = [
            (1, 'John Doe', 'john@example.com'),
            (2, 'Jane Smith', 'jane@example.com')
        ]
        
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        # Compare
        matches, error, comparison_report = verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # Verify comparison passed
        self.assertTrue(matches)
        self.assertIsNone(error)
        self.assertTrue(comparison_report.get('rows_match', False))
        self.assertEqual(comparison_report['source_row_count'], 2)
        self.assertEqual(comparison_report['target_row_count'], 2)
    
    def test_query_result_verifier_detects_mismatch(self):
        """Test that query result verifier detects mismatches"""
        verifier = QueryResultVerifier(self.mock_connector)
        
        # Create mock query results with mismatch
        source_query_result = [
            (1, 'John Doe', 'john@example.com'),
            (2, 'Jane Smith', 'jane@example.com')
        ]
        
        target_rows = [
            (1, 'John Doe', 'john@example.com'),
            (2, 'Jane Wrong', 'jane@example.com')  # Mismatch
        ]
        
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        # Compare
        matches, error, comparison_report = verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # Verify mismatch detected
        self.assertFalse(matches)
        self.assertIsNotNone(error)
        self.assertGreater(len(comparison_report.get('mismatched_rows', [])), 0)
    
    def test_query_result_verifier_handles_null_values(self):
        """Test that query result verifier handles NULL values correctly"""
        verifier = QueryResultVerifier(self.mock_connector)
        
        # Create mock query results with NULL values
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
        
        # Compare
        matches, error, comparison_report = verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # Verify NULL values handled correctly
        self.assertTrue(matches)
        self.assertIsNone(error)
    
    def test_query_result_verifier_handles_transformations(self):
        """Test that query result verifier handles transformations correctly"""
        verifier = QueryResultVerifier(self.mock_connector)
        
        # Create mock query results with transformations
        # Source has transformations applied (TRIM, UPPER)
        source_query_result = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM'),  # UPPER applied
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM')  # UPPER applied
        ]
        
        # Target should match (transformations already applied)
        target_rows = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM'),
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM')
        ]
        
        column_names = ['id', 'name', 'email']
        column_transformations = {'email': 'UPPER'}  # UPPER transformation
        
        # Compare
        matches, error, comparison_report = verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # Verify transformations handled correctly
        self.assertTrue(matches)
        self.assertIsNone(error)
    
    def test_data_integrity_verifier_verifies_accuracy(self):
        """Test that data integrity verifier verifies accuracy correctly"""
        mock_source_connector = Mock(spec=DBConnector)
        mock_target_connector = Mock(spec=DBConnector)
        
        verifier = DataIntegrityVerifier(mock_source_connector, mock_target_connector)
        
        # Mock row count comparison
        verifier._compare_row_counts = Mock(return_value=(True, None, 10))
        
        # Mock row comparison
        verifier._compare_rows = Mock(return_value=(True, None, {'mismatched_rows': []}))
        
        # Call verify_data_accuracy
        is_accurate, error_msg, accuracy_report = verifier.verify_data_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=10,
            column_names=['id', 'name', 'email', 'age']
        )
        
        # Verify accuracy
        self.assertTrue(is_accurate)
        self.assertIsNone(error_msg)
        self.assertTrue(accuracy_report.get('row_count_match', False))
        self.assertTrue(accuracy_report.get('all_rows_match', False))
    
    def test_data_integrity_verifier_detects_row_count_mismatch(self):
        """Test that data integrity verifier detects row count mismatch"""
        mock_source_connector = Mock(spec=DBConnector)
        mock_target_connector = Mock(spec=DBConnector)
        
        verifier = DataIntegrityVerifier(mock_source_connector, mock_target_connector)
        
        # Mock row count comparison with mismatch
        verifier._compare_row_counts = Mock(return_value=(False, "Row count mismatch", 8))
        
        # Call verify_data_accuracy
        is_accurate, error_msg, accuracy_report = verifier.verify_data_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=10,
            column_names=['id', 'name', 'email', 'age']
        )
        
        # Verify mismatch detected
        self.assertFalse(is_accurate)
        self.assertIsNotNone(error_msg)
        self.assertFalse(accuracy_report.get('row_count_match', True))
        self.assertEqual(accuracy_report.get('actual_row_count'), 8)
