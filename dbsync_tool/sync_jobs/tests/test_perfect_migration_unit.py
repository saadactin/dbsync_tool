"""
Unit tests for perfect migration verification logic
Tests the enhanced verification methods without requiring database connections
"""
from django.test import TestCase
from unittest.mock import Mock, MagicMock, patch
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from connections.connectors.base import DBConnector
from django.contrib.auth.models import User
from connections.models import DatabaseConnection


class PerfectMigrationVerificationUnitTest(TestCase):
    """Unit tests for perfect migration verification logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create mock connectors
        self.mock_source_connector = Mock(spec=DBConnector)
        self.mock_target_connector = Mock(spec=DBConnector)
        self.mock_source_connector.__class__.__name__ = 'PostgresConnector'
        self.mock_target_connector.__class__.__name__ = 'PostgresConnector'
        
        # Create test job and execution
        source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user
        )
        
        target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user
        )
        
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='full',
            created_by=self.user
        )
        
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status='running'
        )
        
        self.job_table = SyncJobTable.objects.create(
            job=self.job,
            schema_name='public',
            table_name='test_table',
            transformation_query="age >= 30",
            column_transformations={'name': 'TRIM', 'email': 'LOWER'}
        )
    
    @patch('sync_engine.query_result_verifier.QueryResultVerifier')
    def test_verify_post_migration_accuracy_with_query_results(self, mock_query_verifier_class):
        """Test enhanced post-migration verification with pre-migration query results"""
        # Setup mocks
        mock_data_verifier = Mock()
        mock_data_verifier.verify_data_accuracy.return_value = (
            True, None, {
                'actual_row_count': 2,
                'row_count_match': True,
                'all_rows_match': True
            }
        )
        
        mock_query_verifier = Mock()
        mock_query_verifier.compare_query_results_with_target.return_value = (
            True, None, {
                'rows_match': True,
                'mismatched_rows': []
            }
        )
        mock_query_verifier_class.return_value = mock_query_verifier
        
        # Mock target connector fetch
        self.mock_target_connector.fetch_batch.return_value = [
            (1, 'John Doe', 'john@example.com', 30),
            (2, 'Jane Smith', 'jane@example.com', 35)
        ]
        
        # Create executor
        executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.mock_source_connector,
            target_connector=self.mock_target_connector
        )
        
        # Mock data integrity verifier
        executor.data_integrity_verifier = mock_data_verifier
        
        # Mock query builder
        executor.query_builder = Mock()
        executor.query_builder.build_select_query.return_value = 'SELECT * FROM public.test_table ORDER BY id'
        
        # Pre-migration query results
        pre_migration_query_results = [
            (1, 'John Doe', 'john@example.com', 30),
            (2, 'Jane Smith', 'jane@example.com', 35)
        ]
        
        # Test verification
        is_accurate, error_msg, accuracy_report = executor._verify_post_migration_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=2,
            column_names=['id', 'name', 'email', 'age'],
            pre_migration_query_results=pre_migration_query_results
        )
        
        # Verify results
        self.assertTrue(is_accurate, "Verification should pass")
        self.assertIsNone(error_msg, "No error should be returned")
        self.assertIsNotNone(accuracy_report, "Accuracy report should be returned")
        self.assertTrue(accuracy_report.get('perfect_accuracy', False), "Perfect accuracy should be True")
        
        # Verify query verifier was called
        mock_query_verifier.compare_query_results_with_target.assert_called_once()
    
    def test_verify_post_migration_accuracy_without_query_results(self):
        """Test post-migration verification without pre-migration query results (backward compatibility)"""
        # Setup mocks
        mock_data_verifier = Mock()
        mock_data_verifier.verify_data_accuracy.return_value = (
            True, None, {
                'actual_row_count': 2,
                'row_count_match': True,
                'all_rows_match': True
            }
        )
        
        # Create executor
        executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.mock_source_connector,
            target_connector=self.mock_target_connector
        )
        
        # Mock data integrity verifier
        executor.data_integrity_verifier = mock_data_verifier
        
        # Test verification without query results
        is_accurate, error_msg, accuracy_report = executor._verify_post_migration_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=2,
            column_names=['id', 'name', 'email', 'age'],
            pre_migration_query_results=None  # No query results
        )
        
        # Verify results
        self.assertTrue(is_accurate, "Verification should pass")
        self.assertIsNone(error_msg, "No error should be returned")
        self.assertIsNotNone(accuracy_report, "Accuracy report should be returned")
        # Perfect accuracy should be False when no query results provided
        self.assertFalse(accuracy_report.get('perfect_accuracy', True), "Perfect accuracy should be False without query results")
    
    @patch('sync_engine.query_result_verifier.QueryResultVerifier')
    def test_verify_post_migration_accuracy_query_result_mismatch(self, mock_query_verifier_class):
        """Test post-migration verification fails when query results don't match target"""
        # Setup mocks
        mock_data_verifier = Mock()
        mock_data_verifier.verify_data_accuracy.return_value = (
            True, None, {
                'actual_row_count': 2,
                'row_count_match': True,
                'all_rows_match': True
            }
        )
        
        mock_query_verifier = Mock()
        mock_query_verifier.compare_query_results_with_target.return_value = (
            False, "Row count mismatch", {
                'rows_match': False,
                'mismatched_rows': [1]
            }
        )
        mock_query_verifier_class.return_value = mock_query_verifier
        
        # Mock target connector fetch
        self.mock_target_connector.fetch_batch.return_value = [
            (1, 'John Doe', 'john@example.com', 30)
        ]
        
        # Create executor
        executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.mock_source_connector,
            target_connector=self.mock_target_connector
        )
        
        # Mock data integrity verifier
        executor.data_integrity_verifier = mock_data_verifier
        
        executor.query_builder = Mock()
        executor.query_builder.build_select_query.return_value = 'SELECT * FROM public.test_table ORDER BY id'
        
        # Pre-migration query results (2 rows)
        pre_migration_query_results = [
            (1, 'John Doe', 'john@example.com', 30),
            (2, 'Jane Smith', 'jane@example.com', 35)
        ]
        
        # Test verification
        is_accurate, error_msg, accuracy_report = executor._verify_post_migration_accuracy(
            job_table=self.job_table,
            source_schema='public',
            target_schema='public',
            expected_row_count=2,
            column_names=['id', 'name', 'email', 'age'],
            pre_migration_query_results=pre_migration_query_results
        )
        
        # Verify verification fails
        self.assertFalse(is_accurate, "Verification should fail")
        self.assertIsNotNone(error_msg, "Error message should be returned")
        self.assertIn("Query result comparison failed", error_msg)
    
    def test_verify_post_migration_accuracy_no_transformations(self):
        """Test post-migration verification with no transformations (backward compatibility)"""
        # Create job table without transformations
        job_table_no_transform = SyncJobTable.objects.create(
            job=self.job,
            schema_name='public',
            table_name='test_table_no_transform',
            transformation_query=None,
            column_transformations=None
        )
        
        # Create executor
        executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.mock_source_connector,
            target_connector=self.mock_target_connector
        )
        
        # Mock data integrity verifier
        executor.data_integrity_verifier = Mock()
        executor.data_integrity_verifier.verify_data_accuracy.return_value = (
            True, None, {
                'actual_row_count': 5,
                'row_count_match': True,
                'all_rows_match': True
            }
        )
        
        # Test verification
        is_accurate, error_msg, accuracy_report = executor._verify_post_migration_accuracy(
            job_table=job_table_no_transform,
            source_schema='public',
            target_schema='public',
            expected_row_count=5,
            column_names=['id', 'name', 'email', 'age'],
            pre_migration_query_results=None
        )
        
        # Verify results
        self.assertTrue(is_accurate, "Verification should pass")
        self.assertIsNone(error_msg, "No error should be returned")
        # Perfect accuracy should not be set when no query results provided
        # (it won't be in the report, so default to False)
        self.assertFalse(accuracy_report.get('perfect_accuracy', False), "Perfect accuracy should be False without query results")
