"""
Unit tests for PreMigrationValidator service
"""
from django.test import TestCase
from unittest.mock import Mock, patch
from connections.connectors.base import DBConnector
from sync_engine.pre_migration_validator import PreMigrationValidator
from sync_jobs.models import SyncJobTable
from django.contrib.auth.models import User


class PreMigrationValidatorTest(TestCase):
    """Test PreMigrationValidator class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_connector = Mock(spec=DBConnector)
        self.mock_connector.__class__.__name__ = 'PostgresConnector'
        self.validator = PreMigrationValidator(self.mock_connector)
        
        # Create minimal test objects for tests that need them
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create a mock job_table for tests that need it
        # We'll use Mock instead of creating real database objects for unit tests
        self.job_table = Mock(spec=SyncJobTable)
        self.job_table.schema_name = 'public'
        self.job_table.table_name = 'users'
        self.job_table.transformation_query = "age >= 30"
        self.job_table.column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
    
    def test_init(self):
        """Test PreMigrationValidator initialization"""
        validator = PreMigrationValidator(self.mock_connector)
        self.assertEqual(validator.source_connector, self.mock_connector)
        self.assertIsNotNone(validator.query_builder)
        self.assertIsNotNone(validator.transformation_engine)
    
    def test_get_expected_row_count_with_where_clause(self):
        """Test getting expected row count with WHERE clause"""
        # Mock connector methods
        self.mock_connector.fetch_batch = Mock(return_value=[(5,)])
        
        count = self.validator._get_expected_row_count(
            schema='public',
            table='users',
            where_clause="age >= 30",
            column_transformations={}
        )
        
        self.assertEqual(count, 5)
        self.mock_connector.fetch_batch.assert_called_once()
    
    def test_get_expected_row_count_without_where_clause(self):
        """Test getting expected row count without WHERE clause"""
        self.mock_connector.fetch_batch = Mock(return_value=[(10,)])
        
        count = self.validator._get_expected_row_count(
            schema='public',
            table='users',
            where_clause=None,
            column_transformations={}
        )
        
        self.assertEqual(count, 10)
    
    def test_fetch_sample_rows(self):
        """Test fetching sample rows"""
        sample_data = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM'),
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM')
        ]
        self.mock_connector.fetch_batch = Mock(return_value=sample_data)
        
        rows = self.validator._fetch_sample_rows(
            transformed_query='SELECT id, name, email FROM "public"."users"',
            sample_size=2
        )
        
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows, sample_data)
    
    def test_verify_transformations_applied_trim(self):
        """Test verifying TRIM transformation"""
        sample_rows = [
            (1, 'John Doe', 'john@example.com'),  # No leading/trailing spaces
            (2, 'Jane Smith', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'name': 'TRIM'}
        
        is_valid, error = self.validator._verify_transformations_applied(
            sample_rows=sample_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # TRIM verification is lenient (may be applied in SQL)
        self.assertTrue(is_valid)
    
    def test_verify_transformations_applied_upper(self):
        """Test verifying UPPER transformation"""
        sample_rows = [
            (1, 'John Doe', 'JOHN@EXAMPLE.COM'),  # Uppercase email
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'email': 'UPPER'}
        
        is_valid, error = self.validator._verify_transformations_applied(
            sample_rows=sample_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_verify_transformations_applied_upper_failure(self):
        """Test verifying UPPER transformation failure"""
        sample_rows = [
            (1, 'John Doe', 'john@example.com'),  # Lowercase email (should be uppercase)
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'email': 'UPPER'}
        
        is_valid, error = self.validator._verify_transformations_applied(
            sample_rows=sample_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
        self.assertIn('not uppercase', error)
    
    def test_verify_transformations_applied_lower(self):
        """Test verifying LOWER transformation"""
        sample_rows = [
            (1, 'John Doe', 'john@example.com'),  # Lowercase email
            (2, 'Jane Smith', 'jane@example.com')
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'email': 'LOWER'}
        
        is_valid, error = self.validator._verify_transformations_applied(
            sample_rows=sample_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_verify_transformations_applied_with_null(self):
        """Test verifying transformations with NULL values"""
        sample_rows = [
            (1, None, 'JOHN@EXAMPLE.COM'),  # NULL name, uppercase email (UPPER applied)
            (2, 'Jane Smith', None)  # name present, NULL email (skipped)
        ]
        column_names = ['id', 'name', 'email']
        column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        is_valid, error = self.validator._verify_transformations_applied(
            sample_rows=sample_rows,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # NULL values should be skipped, non-NULL values should have transformations applied
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    @patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type')
    def test_validate_transformation_query_success(self, mock_get_db_type):
        """Test successful transformation query validation"""
        mock_get_db_type.return_value = 'postgres'
        
        # Mock all methods
        self.validator._get_expected_row_count = Mock(return_value=5)
        self.validator._fetch_sample_rows = Mock(return_value=[
            (1, 'John Doe', 'JOHN@EXAMPLE.COM'),
            (2, 'Jane Smith', 'JANE@EXAMPLE.COM')
        ])
        self.validator._verify_transformations_applied = Mock(return_value=(True, None))
        
        # Mock connector for syntax check
        self.mock_connector.fetch_batch = Mock(return_value=[(1, 'John Doe', 'JOHN@EXAMPLE.COM')])
        
        is_valid, error, report = self.validator.validate_transformation_query(
            job_table=self.job_table,
            transformed_query='SELECT id, name, email FROM "public"."users" WHERE age >= 30',
            base_query='SELECT id, name, email FROM "public"."users"',
            column_names=['id', 'name', 'email']
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
        self.assertIsNotNone(report)
        self.assertEqual(report['expected_row_count'], 5)
        self.assertEqual(len(report['sample_rows']), 2)
    
    @patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type')
    def test_validate_transformation_query_syntax_failure(self, mock_get_db_type):
        """Test validation failure due to syntax error"""
        mock_get_db_type.return_value = 'postgres'
        
        # Mock connector to raise error
        self.mock_connector.fetch_batch = Mock(side_effect=Exception("SQL syntax error"))
        
        is_valid, error, report = self.validator.validate_transformation_query(
            job_table=self.job_table,
            transformed_query='SELECT * FROM invalid_table',
            base_query='SELECT * FROM invalid_table',
            column_names=['id', 'name', 'email']
        )
        
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
        self.assertIn('syntax', error.lower())
    
    @patch('sync_engine.pre_migration_validator.QueryBuilder.get_db_type')
    def test_validate_transformation_query_no_transformations(self, mock_get_db_type):
        """Test validation with no transformations"""
        mock_get_db_type.return_value = 'postgres'
        
        job_table_no_transforms = Mock(spec=SyncJobTable)
        job_table_no_transforms.schema_name = 'public'
        job_table_no_transforms.table_name = 'users'
        job_table_no_transforms.transformation_query = None
        job_table_no_transforms.column_transformations = None
        
        self.mock_connector.fetch_batch = Mock(return_value=[(1,)])
        
        is_valid, error, report = self.validator.validate_transformation_query(
            job_table=job_table_no_transforms,
            transformed_query='SELECT * FROM "public"."users"',
            base_query='SELECT * FROM "public"."users"',
            column_names=['id', 'name', 'email']
        )
        
        # Should still validate (syntax check)
        self.assertTrue(is_valid)
        self.assertIsNotNone(report)
