"""
Tests for transformation integration in IncrementalSyncExecutor
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_engine.exceptions import TableSyncError


class TestIncrementalSyncTransformationIntegration(unittest.TestCase):
    """Test transformation integration in IncrementalSyncExecutor"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.job = Mock(spec=SyncJob)
        self.job.id = 'test-job-id'
        self.job.sync_type = 'incremental'
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
        
        self.executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector
        )
    
    def test_init_has_transformation_components(self):
        """Test that executor has transformation engine and validator"""
        self.assertIsNotNone(self.executor.transformation_engine)
        self.assertIsNotNone(self.executor.transformation_validator)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    @patch('sync_engine.incremental_sync.CheckpointManager')
    def test_sync_table_without_transformations(self, mock_checkpoint_manager_class, mock_log_class):
        """Test sync table without transformations (backward compatibility)"""
        # Mock checkpoint manager
        mock_checkpoint_manager = Mock()
        mock_checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        mock_checkpoint_manager_class.return_value = mock_checkpoint_manager
        self.executor.checkpoint_manager = mock_checkpoint_manager
        
        # Mock job table without transformations
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
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
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT "id", "name", "updated_at" FROM "public"."users" WHERE 1=1 ORDER BY "updated_at", "id"'
        )
        
        # Mock batch fetching
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice', datetime.now()), (2, 'Bob', datetime.now())],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify transformation engine was not called for validation
        # (since no transformations, it should skip validation)
        self.executor.table_handler.create_table_if_not_exists.assert_called_once()
        self.target_connector.bulk_insert.assert_called()
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    @patch('sync_engine.incremental_sync.CheckpointManager')
    def test_sync_table_with_where_clause_transformation(self, mock_checkpoint_manager_class, mock_log_class):
        """Test sync table with WHERE clause transformation combined with incremental WHERE"""
        # Mock checkpoint manager
        mock_checkpoint_manager = Mock()
        mock_checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        mock_checkpoint_manager_class.return_value = mock_checkpoint_manager
        self.executor.checkpoint_manager = mock_checkpoint_manager
        
        # Mock job table with WHERE clause
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = "status = 'active'"
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('status', 'varchar', True, False),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder (incremental query)
        base_query = 'SELECT "id", "name", "status", "updated_at" FROM "public"."users" WHERE 1=1 ORDER BY "updated_at", "id"'
        self.executor.query_builder.build_incremental_query = Mock(return_value=base_query)
        
        # Mock transformation validation
        self.executor.transformation_validator.validate_where_clause = Mock(
            return_value=(True, None)
        )
        
        # Mock transformation engine (should combine incremental WHERE with transformation WHERE)
        transformed_query = 'SELECT "id", "name", "status", "updated_at" FROM "public"."users" WHERE 1=1 AND (status = \'active\') ORDER BY "updated_at", "id"'
        self.executor.transformation_engine.apply_query_transformations = Mock(
            return_value=transformed_query
        )
        
        # Mock pre-migration validation
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice', 'active', datetime.now())],  # Validation query result
            [(1, 'Alice', 'active', datetime.now()), (2, 'Bob', 'active', datetime.now())],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify transformation was validated and applied
        self.executor.transformation_validator.validate_where_clause.assert_called_once()
        self.executor.transformation_engine.apply_query_transformations.assert_called_once()
        self.target_connector.bulk_insert.assert_called()
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    @patch('sync_engine.incremental_sync.CheckpointManager')
    def test_sync_table_with_column_transformations(self, mock_checkpoint_manager_class, mock_log_class):
        """Test sync table with column transformations"""
        # Mock checkpoint manager
        mock_checkpoint_manager = Mock()
        mock_checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        mock_checkpoint_manager_class.return_value = mock_checkpoint_manager
        self.executor.checkpoint_manager = mock_checkpoint_manager
        
        # Mock job table with column transformations
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
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
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('email', 'varchar', True, False),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder
        base_query = 'SELECT "id", "name", "email", "updated_at" FROM "public"."users" WHERE 1=1 ORDER BY "updated_at", "id"'
        self.executor.query_builder.build_incremental_query = Mock(return_value=base_query)
        
        # Mock transformation validation
        self.executor.transformation_validator.validate_column_transformations = Mock(
            return_value=(True, None)
        )
        
        # Mock transformation engine
        transformed_query = 'SELECT "id", TRIM("name") AS "name", UPPER("email") AS "email", "updated_at" FROM "public"."users" WHERE 1=1 ORDER BY "updated_at", "id"'
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
            [(1, '  Alice  ', 'alice@example.com', datetime.now())],  # Validation query result
            [(1, '  Alice  ', 'alice@example.com', datetime.now()), (2, '  Bob  ', 'bob@example.com', datetime.now())],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
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
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    @patch('sync_engine.incremental_sync.CheckpointManager')
    def test_sync_table_with_combined_transformations(self, mock_checkpoint_manager_class, mock_log_class):
        """Test sync table with both WHERE clause and column transformations"""
        # Mock checkpoint manager
        mock_checkpoint_manager = Mock()
        mock_checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        mock_checkpoint_manager_class.return_value = mock_checkpoint_manager
        self.executor.checkpoint_manager = mock_checkpoint_manager
        
        # Mock job table with both transformations
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = "status = 'active'"
        job_table.column_transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.source_db_type = 'postgres'
        self.executor.table_handler.target_db_type = 'postgres'
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('email', 'varchar', True, False),
            ColumnInfo('status', 'varchar', True, False),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder
        base_query = 'SELECT "id", "name", "email", "status", "updated_at" FROM "public"."users" WHERE 1=1 ORDER BY "updated_at", "id"'
        self.executor.query_builder.build_incremental_query = Mock(return_value=base_query)
        
        # Mock transformation validation
        self.executor.transformation_validator.validate_where_clause = Mock(
            return_value=(True, None)
        )
        self.executor.transformation_validator.validate_column_transformations = Mock(
            return_value=(True, None)
        )
        
        # Mock transformation engine
        transformed_query = 'SELECT "id", TRIM("name") AS "name", UPPER("email") AS "email", "status", "updated_at" FROM "public"."users" WHERE 1=1 AND (status = \'active\') ORDER BY "updated_at", "id"'
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
            [(1, 'Alice', 'alice@example.com', 'active', datetime.now())],  # Validation query result
            [(1, '  Alice  ', 'alice@example.com', 'active', datetime.now()), (2, '  Bob  ', 'bob@example.com', 'active', datetime.now())],  # First batch
            []  # Empty batch to stop
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify both validations were called
        self.executor.transformation_validator.validate_where_clause.assert_called_once()
        self.executor.transformation_validator.validate_column_transformations.assert_called_once()
        self.executor.transformation_engine.apply_query_transformations.assert_called_once()
        self.target_connector.bulk_insert.assert_called()
