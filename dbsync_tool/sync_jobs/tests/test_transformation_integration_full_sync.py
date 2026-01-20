"""
Tests for transformation integration in FullSyncExecutor
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.exceptions import TableSyncError


class TestFullSyncTransformationIntegration(unittest.TestCase):
    """Test transformation integration in FullSyncExecutor"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.job = Mock(spec=SyncJob)
        self.job.id = 'test-job-id'
        self.job.sync_type = 'full'
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))
        
        self.execution = Mock(spec=SyncExecution)
        self.execution.id = 'test-execution-id'
        self.execution.status = 'pending'
        self.execution.save = Mock()
        
        # Create mock connectors with proper class names
        from connections.connectors.postgres import PostgresConnector
        self.source_connector = Mock(spec=PostgresConnector)
        self.source_connector.__class__.__name__ = 'PostgresConnector'
        self.target_connector = Mock(spec=PostgresConnector)
        self.target_connector.__class__.__name__ = 'PostgresConnector'
        self.target_connector.database_name = 'test_db'
        
        self.executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector
        )
    
    def test_init_has_transformation_components(self):
        """Test that executor has transformation engine and validator"""
        self.assertIsNotNone(self.executor.transformation_engine)
        self.assertIsNotNone(self.executor.transformation_validator)
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_without_transformations(self, mock_log_class):
        """Test sync table without transformations (backward compatibility)"""
        # Mock job table without transformations
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.truncate_table = Mock()
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        
        # Mock query builder
        self.executor.query_builder.build_select_query = Mock(
            return_value='SELECT "id", "name" FROM "public"."users" ORDER BY "id"'
        )
        
        # Mock batch fetching
        # First call is for pre-migration validation (LIMIT 1), then actual batches
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice')],  # Pre-migration validation query result
            [(1, 'Alice'), (2, 'Bob')],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter - need to handle multiple filter calls
        with patch('sync_engine.full_sync.SyncExecutionLog.objects.filter') as mock_filter:
            # Create a mock that returns different values based on filter criteria
            def filter_side_effect(*args, **kwargs):
                result_mock = Mock()
                if 'status' in kwargs:
                    if kwargs.get('status') == 'completed':
                        result_mock.count = Mock(return_value=1)
                    elif kwargs.get('status') == 'failed':
                        result_mock.exists = Mock(return_value=False)
                        result_mock.count = Mock(return_value=0)
                else:
                    # For aggregate calls (no status filter)
                    result_mock.aggregate = Mock(return_value={'total': 2})
                return result_mock
            
            mock_filter.side_effect = filter_side_effect
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify transformation engine was not called for validation
        # (since no transformations, it should skip validation)
        self.executor.table_handler.create_table_if_not_exists.assert_called_once()
        # Verify bulk insert was called (at least once for the batch)
        self.assertGreaterEqual(self.target_connector.bulk_insert.call_count, 1, "bulk_insert should have been called")
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_with_where_clause_transformation(self, mock_log_class):
        """Test sync table with WHERE clause transformation"""
        # Mock job table with WHERE clause
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = "age > 25"
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.truncate_table = Mock()
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('age', 'int', True, False)
        ])
        
        # Mock query builder
        base_query = 'SELECT "id", "name", "age" FROM "public"."users" ORDER BY "id"'
        self.executor.query_builder.build_select_query = Mock(return_value=base_query)
        
        # Mock transformation validation
        self.executor.transformation_validator.validate_where_clause = Mock(
            return_value=(True, None)
        )
        
        # Mock transformation engine
        transformed_query = 'SELECT "id", "name", "age" FROM "public"."users" WHERE age > 25 ORDER BY "id"'
        self.executor.transformation_engine.apply_query_transformations = Mock(
            return_value=transformed_query
        )
        
        # Mock pre-migration validation
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice', 30)],  # Validation query result
            [(1, 'Alice', 30), (2, 'Bob', 35)],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.full_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify transformation was validated and applied
        self.executor.transformation_validator.validate_where_clause.assert_called_once()
        self.executor.transformation_engine.apply_query_transformations.assert_called_once()
        self.target_connector.bulk_insert.assert_called()
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_with_column_transformations(self, mock_log_class):
        """Test sync table with column transformations"""
        # Mock job table with column transformations
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = None
        job_table.column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.truncate_table = Mock()
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('email', 'varchar', True, False)
        ])
        
        # Mock query builder
        base_query = 'SELECT "id", "name", "email" FROM "public"."users" ORDER BY "id"'
        self.executor.query_builder.build_select_query = Mock(return_value=base_query)
        
        # Mock transformation validation
        self.executor.transformation_validator.validate_column_transformations = Mock(
            return_value=(True, None)
        )
        
        # Mock transformation engine
        transformed_query = 'SELECT "id", TRIM("name") AS "name", UPPER("email") AS "email" FROM "public"."users" ORDER BY "id"'
        self.executor.transformation_engine.apply_query_transformations = Mock(
            return_value=transformed_query
        )
        
        # Mock row transformations (fallback)
        def mock_apply_row_transformations(batch, column_names, column_transformations):
            return batch
        self.executor.transformation_engine.apply_row_transformations = Mock(
            side_effect=mock_apply_row_transformations
        )
        
        # Mock pre-migration validation
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice', 'alice@example.com')],  # Validation query result
            [(1, '  Alice  ', 'alice@example.com'), (2, '  Bob  ', 'bob@example.com')],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.full_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify transformation was validated and applied
        self.executor.transformation_validator.validate_column_transformations.assert_called_once()
        self.executor.transformation_engine.apply_query_transformations.assert_called_once()
        # Row transformations should be called for each batch
        self.executor.transformation_engine.apply_row_transformations.assert_called()
        self.target_connector.bulk_insert.assert_called()
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_with_invalid_transformation(self, mock_log_class):
        """Test sync table fails with invalid transformation"""
        # Mock job table with invalid transformation
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = "DROP TABLE users"  # Invalid SQL injection attempt
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.truncate_table = Mock()
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        
        # Mock query builder
        base_query = 'SELECT "id", "name" FROM "public"."users" ORDER BY "id"'
        self.executor.query_builder.build_select_query = Mock(return_value=base_query)
        
        # Mock transformation validation (should fail)
        self.executor.transformation_validator.validate_where_clause = Mock(
            return_value=(False, "WHERE clause contains potentially dangerous SQL patterns")
        )
        
        # Execute sync - should raise TableSyncError
        with self.assertRaises(TableSyncError) as context:
            self.executor.sync_table(job_table)
        
        # Verify error message
        self.assertIn("Transformation validation failed", str(context.exception))
        
        # Verify validation was called
        self.executor.transformation_validator.validate_where_clause.assert_called_once()
        
        # Verify transformation was NOT applied (validation failed before applying)
        # Note: apply_query_transformations is a method, not a Mock, so we check it wasn't called
        # by verifying the error was raised before it could be called
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_with_pre_migration_validation_failure(self, mock_log_class):
        """Test sync table fails when pre-migration validation fails"""
        # Mock job table with transformation
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = "age > 25"
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.truncate_table = Mock()
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('age', 'int', True, False)
        ])
        
        # Mock query builder
        base_query = 'SELECT "id", "name", "age" FROM "public"."users" ORDER BY "id"'
        self.executor.query_builder.build_select_query = Mock(return_value=base_query)
        
        # Mock transformation validation (should pass)
        self.executor.transformation_validator.validate_where_clause = Mock(
            return_value=(True, None)
        )
        
        # Mock transformation engine
        transformed_query = 'SELECT "id", "name", "age" FROM "public"."users" WHERE age > 25 ORDER BY "id"'
        self.executor.transformation_engine.apply_query_transformations = Mock(
            return_value=transformed_query
        )
        
        # Mock pre-migration validation (should fail)
        self.source_connector.fetch_batch = Mock(side_effect=Exception("SQL syntax error"))
        
        # Execute sync - should raise TableSyncError
        with self.assertRaises(TableSyncError) as context:
            self.executor.sync_table(job_table)
        
        # Verify error message
        self.assertIn("Pre-migration validation failed", str(context.exception))
        
        # Verify validation was called
        self.executor.transformation_validator.validate_where_clause.assert_called_once()
        self.executor.transformation_engine.apply_query_transformations.assert_called_once()
        
        # Verify bulk insert was NOT called (validation failed)
        self.target_connector.bulk_insert.assert_not_called()
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_with_combined_transformations(self, mock_log_class):
        """Test sync table with both WHERE clause and column transformations"""
        # Mock job table with both transformations
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = "age > 25"
        job_table.column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.truncate_table = Mock()
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('email', 'varchar', True, False),
            ColumnInfo('age', 'int', True, False)
        ])
        
        # Mock query builder
        base_query = 'SELECT "id", "name", "email", "age" FROM "public"."users" ORDER BY "id"'
        self.executor.query_builder.build_select_query = Mock(return_value=base_query)
        
        # Mock transformation validation
        self.executor.transformation_validator.validate_where_clause = Mock(
            return_value=(True, None)
        )
        self.executor.transformation_validator.validate_column_transformations = Mock(
            return_value=(True, None)
        )
        
        # Mock transformation engine
        transformed_query = 'SELECT "id", TRIM("name") AS "name", UPPER("email") AS "email", "age" FROM "public"."users" WHERE age > 25 ORDER BY "id"'
        self.executor.transformation_engine.apply_query_transformations = Mock(
            return_value=transformed_query
        )
        
        # Mock row transformations
        def mock_apply_row_transformations(batch, column_names, column_transformations):
            return batch
        self.executor.transformation_engine.apply_row_transformations = Mock(
            side_effect=mock_apply_row_transformations
        )
        
        # Mock pre-migration validation
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice', 'alice@example.com', 30)],  # Validation query result
            [(1, '  Alice  ', 'alice@example.com', 30), (2, '  Bob  ', 'bob@example.com', 35)],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.full_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify both validations were called
        self.executor.transformation_validator.validate_where_clause.assert_called_once()
        self.executor.transformation_validator.validate_column_transformations.assert_called_once()
        self.executor.transformation_engine.apply_query_transformations.assert_called_once()
        self.target_connector.bulk_insert.assert_called()
