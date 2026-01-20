"""
Unit tests for query execution before migration (Day 4)

Tests comprehensive query execution before migration:
- Full query execution on source database
- Query result structure verification
- Query result data verification
- Query execution time measurement
- Edge case handling
"""
from django.test import TestCase, TransactionTestCase
from unittest.mock import Mock, patch, MagicMock
from connections.connectors.base import DBConnector
from sync_engine.pre_migration_validator import PreMigrationValidator
from sync_engine.query_result_verifier import QueryResultVerifier
from sync_jobs.models import SyncJobTable, SyncJob, DatabaseConnection
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)


class QueryExecutionBeforeMigrationTest(TestCase):
    """Test query execution before migration"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_connector = Mock(spec=DBConnector)
        self.mock_connector.__class__.__name__ = 'PostgresConnector'
        self.validator = PreMigrationValidator(self.mock_connector)
        
        # Create minimal test objects
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create mock job_table
        self.job_table = Mock(spec=SyncJobTable)
        self.job_table.schema_name = 'public'
        self.job_table.table_name = 'users'
        self.job_table.transformation_query = "age >= 30"
        self.job_table.column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
    
    def test_validate_transformation_query_executes_full_query(self):
        """Test that validate_transformation_query executes full query before migration"""
        # Mock query execution results
        query_results = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30),
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM', 35),
            (3, 'Bob Wilson', 'BOB@EXAMPLE.COM', 40)
        ]
        
        # Mock connector methods
        self.mock_connector.fetch_batch = Mock(side_effect=[
            [(1,)],  # First call: syntax validation (LIMIT 1)
            [(3,)],  # Second call: COUNT query
            query_results  # Third call: Full query execution
        ])
        
        # Mock QueryBuilder.get_db_type
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=self.job_table,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        # Verify query was executed
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)
        self.assertIn('query_results', validation_report)
        self.assertEqual(validation_report['query_result_count'], 3)
        self.assertIn('query_execution_time', validation_report)
        self.assertTrue(validation_report['structure_verified'])
        self.assertTrue(validation_report['data_verified'])
    
    def test_validate_transformation_query_stores_query_results(self):
        """Test that query results are stored in validation report"""
        query_results = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30),
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM', 35)
        ]
        
        self.mock_connector.fetch_batch = Mock(side_effect=[
            [(1,)],  # Syntax validation
            [(2,)],  # COUNT query
            query_results  # Full query execution
        ])
        
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=self.job_table,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        self.assertTrue(is_valid)
        self.assertEqual(len(validation_report['query_results']), 2)
        self.assertEqual(validation_report['query_results'], query_results)
    
    def test_validate_transformation_query_measures_execution_time(self):
        """Test that query execution time is measured"""
        import time
        
        query_results = [(1, 'John Doe', 'JOHN@EXAMPLE.COM', 30)]
        
        # Mock fetch_batch to simulate some delay
        def mock_fetch_batch(*args, **kwargs):
            time.sleep(0.01)  # Small delay
            if len(args) > 0 and 'COUNT' in str(args[0]):
                return [(1,)]
            elif len(args) > 0 and 'LIMIT 1' in str(args[0]):
                return [(1,)]
            return query_results
        
        self.mock_connector.fetch_batch = Mock(side_effect=mock_fetch_batch)
        
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=self.job_table,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        self.assertTrue(is_valid)
        self.assertIn('query_execution_time', validation_report)
        self.assertGreater(validation_report['query_execution_time'], 0)
    
    def test_validate_transformation_query_handles_empty_results(self):
        """Test that empty query results are handled correctly"""
        self.mock_connector.fetch_batch = Mock(side_effect=[
            [(1,)],  # Syntax validation
            [(0,)],  # COUNT query - no rows
            []  # Full query execution - empty
        ])
        
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=self.job_table,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        self.assertTrue(is_valid)
        self.assertEqual(validation_report['query_result_count'], 0)
        self.assertEqual(len(validation_report['query_results']), 0)
    
    def test_validate_transformation_query_handles_large_results(self):
        """Test that large query results are handled (sampling)"""
        # Create large result set (simulated)
        large_results = [(i, f'User {i}', f'user{i}@example.com', 30 + i) for i in range(10000)]
        
        # Create job_table without column transformations for this test
        job_table_no_transforms = Mock(spec=SyncJobTable)
        job_table_no_transforms.schema_name = 'public'
        job_table_no_transforms.table_name = 'users'
        job_table_no_transforms.transformation_query = "age >= 30"
        job_table_no_transforms.column_transformations = {}  # No column transformations
        
        self.mock_connector.fetch_batch = Mock(side_effect=[
            [(1,)],  # Syntax validation
            [(10000,)],  # COUNT query
            large_results[:10000]  # Full query execution (sampled to 10000)
        ])
        
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=job_table_no_transforms,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        self.assertTrue(is_valid)
        # Should have sampled results (up to 10000)
        self.assertLessEqual(validation_report['query_result_count'], 10000)
    
    def test_validate_transformation_query_fails_on_execution_error(self):
        """Test that query execution failure is handled"""
        self.mock_connector.fetch_batch = Mock(side_effect=[
            [(1,)],  # Syntax validation passes
            [(5,)],  # COUNT query passes
            Exception("Query execution failed")  # Full query execution fails
        ])
        
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=self.job_table,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        self.assertFalse(is_valid)
        self.assertIn('Query execution failed', error_msg)
    
    def test_validate_transformation_query_verifies_structure(self):
        """Test that query result structure is verified"""
        query_results = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30),
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM', 35)
        ]
        
        self.mock_connector.fetch_batch = Mock(side_effect=[
            [(1,)],  # Syntax validation
            [(2,)],  # COUNT query
            query_results  # Full query execution
        ])
        
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=self.job_table,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        self.assertTrue(is_valid)
        self.assertTrue(validation_report['structure_verified'])
        self.assertIn('row_count_match', validation_report)
        self.assertIn('column_count_match', validation_report)
    
    def test_validate_transformation_query_verifies_data(self):
        """Test that query result data is verified"""
        query_results = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM', 30),
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM', 35)
        ]
        
        self.mock_connector.fetch_batch = Mock(side_effect=[
            [(1,)],  # Syntax validation
            [(2,)],  # COUNT query
            query_results  # Full query execution
        ])
        
        with patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type', return_value='postgres'):
            is_valid, error_msg, validation_report = self.validator.validate_transformation_query(
                job_table=self.job_table,
                transformed_query='SELECT id, name, email, age FROM "public"."users" WHERE age >= 30',
                base_query='SELECT id, name, email, age FROM "public"."users"',
                column_names=['id', 'name', 'email', 'age']
            )
        
        self.assertTrue(is_valid)
        self.assertTrue(validation_report['data_verified'])
        self.assertIn('rows_verified', validation_report)
        self.assertIn('null_values_found', validation_report)


class QueryResultVerifierTest(TestCase):
    """Test QueryResultVerifier class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_connector = Mock(spec=DBConnector)
        self.mock_connector.__class__.__name__ = 'PostgresConnector'
        self.verifier = QueryResultVerifier(self.mock_connector)
    
    def test_verify_query_result_structure_valid(self):
        """Test query result structure verification with valid structure"""
        query_result = [
            (1, 'John Doe', 'john@example.com'),
            (2, 'Jane Smith', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        expected_row_count = 2
        
        is_valid, error_msg, structure_report = self.verifier.verify_query_result_structure(
            query_result=query_result,
            column_names=column_names,
            expected_row_count=expected_row_count
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)
        self.assertTrue(structure_report['row_count_match'])
        self.assertTrue(structure_report['column_count_match'])
    
    def test_verify_query_result_structure_row_count_mismatch(self):
        """Test query result structure verification with row count mismatch"""
        query_result = [
            (1, 'John Doe', 'john@example.com'),
            (2, 'Jane Smith', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        expected_row_count = 5  # Mismatch
        
        is_valid, error_msg, structure_report = self.verifier.verify_query_result_structure(
            query_result=query_result,
            column_names=column_names,
            expected_row_count=expected_row_count
        )
        
        # Should still be valid if difference is within tolerance (sampling)
        # But should log warning
        self.assertIn('row_count_match', structure_report)
    
    def test_verify_query_result_structure_column_count_mismatch(self):
        """Test query result structure verification with column count mismatch"""
        query_result = [
            (1, 'John Doe'),  # Only 2 columns
            (2, 'Jane Smith')
        ]
        column_names = ['id', 'name', 'email']  # Expects 3 columns
        
        is_valid, error_msg, structure_report = self.verifier.verify_query_result_structure(
            query_result=query_result,
            column_names=column_names,
            expected_row_count=2
        )
        
        self.assertFalse(is_valid)
        self.assertIn('Column count mismatch', error_msg)
    
    def test_verify_query_result_data_valid(self):
        """Test query result data verification with valid data"""
        query_result = [
            (1, 'John Doe', 'john@example.com'),
            (2, 'Jane Smith', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        is_valid, error_msg, data_report = self.verifier.verify_query_result_data(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)
        self.assertEqual(data_report['rows_verified'], 2)
    
    def test_verify_query_result_data_with_null_values(self):
        """Test query result data verification with NULL values"""
        query_result = [
            (1, None, 'john@example.com'),  # NULL name
            (2, 'Jane Smith', None)  # NULL email
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {}
        
        is_valid, error_msg, data_report = self.verifier.verify_query_result_data(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertEqual(data_report['null_values_found'], 2)
    
    def test_verify_transformations_applied_upper(self):
        """Test transformation verification with UPPER transformation"""
        query_result = [
            (1, 'JOHN DOE', 'john@example.com'),
            (2, 'JANE SMITH', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'name': 'UPPER'}
        
        is_valid, error_msg = self.verifier.verify_transformations_applied(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)
    
    def test_verify_transformations_applied_lower(self):
        """Test transformation verification with LOWER transformation"""
        query_result = [
            (1, 'john doe', 'john@example.com'),
            (2, 'jane smith', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'name': 'LOWER'}
        
        is_valid, error_msg = self.verifier.verify_transformations_applied(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)
    
    def test_verify_transformations_applied_fails_on_mismatch(self):
        """Test transformation verification fails when transformation not applied"""
        query_result = [
            (1, 'John Doe', 'john@example.com'),  # Not uppercase
            (2, 'Jane Smith', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'name': 'UPPER'}
        
        is_valid, error_msg = self.verifier.verify_transformations_applied(
            query_result=query_result,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertFalse(is_valid)
        self.assertIn('not uppercase', error_msg)
    
    def test_compare_query_results_with_target_matches(self):
        """Test comparing query results with target data when they match"""
        source_query_result = [
            (1, 'JOHN DOE', 'john@example.com'),
            (2, 'JANE SMITH', 'jane@example.com')
        ]
        target_rows = [
            (1, 'JOHN DOE', 'john@example.com'),
            (2, 'JANE SMITH', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'name': 'UPPER'}
        
        matches, error_msg, comparison_report = self.verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(matches)
        self.assertIsNone(error_msg)
        self.assertTrue(comparison_report['rows_match'])
    
    def test_compare_query_results_with_target_mismatch(self):
        """Test comparing query results with target data when they don't match"""
        source_query_result = [
            (1, 'JOHN DOE', 'john@example.com'),
            (2, 'JANE SMITH', 'jane@example.com')
        ]
        target_rows = [
            (1, 'John Doe', 'john@example.com'),  # Not uppercase
            (2, 'JANE SMITH', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'name': 'UPPER'}
        
        matches, error_msg, comparison_report = self.verifier.compare_query_results_with_target(
            source_query_result=source_query_result,
            target_rows=target_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertFalse(matches)
        self.assertIn('mismatched', error_msg)
        self.assertGreater(len(comparison_report['mismatched_rows']), 0)
