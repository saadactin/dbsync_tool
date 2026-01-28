"""
Tests for full sync executor
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from connections.connectors.base import ColumnInfo
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.exceptions import TableSyncError


class TestFullSyncExecutor(unittest.TestCase):
    """Test cases for FullSyncExecutor"""
    
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
        
        # Create mock connectors with proper class names
        self.source_connector = Mock()
        type(self.source_connector).__name__ = 'PostgresConnector'
        self.target_connector = Mock()
        type(self.target_connector).__name__ = 'PostgresConnector'
        
        self.executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector
        )
    
    def test_init(self):
        """Test FullSyncExecutor initialization"""
        self.assertEqual(self.executor.job, self.job)
        self.assertEqual(self.executor.execution, self.execution)
        self.assertEqual(self.executor.source_connector, self.source_connector)
        self.assertEqual(self.executor.target_connector, self.target_connector)
        self.assertIsNotNone(self.executor.table_handler)
        self.assertIsNotNone(self.executor.validator)
        self.assertIsNotNone(self.executor.query_builder)
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_success(self, mock_log_class):
        """Test successful table sync"""
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.target_connector.truncate_table = Mock()
        
        # Mock get_tables for validation
        self.source_connector.get_tables = Mock(return_value=['users'])
        
        # Mock connection and cursor for pre-migration validation
        mock_cursor = Mock()
        mock_cursor.execute = Mock()
        mock_cursor.fetchall = Mock(return_value=[(2,)])  # Return count of 2
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_connection = Mock()
        mock_connection.cursor = Mock(return_value=mock_cursor)
        self.source_connector._connection = mock_connection
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        
        # Mock query builder
        self.executor.query_builder.build_select_query = Mock(return_value='SELECT * FROM "public"."users"')
        
        # Mock batch fetching - need to handle validation calls and sync calls
        # Validation might call fetch_batch, so we need more return values
        # Use a list that can be reset or provide enough values
        fetch_batch_results = [
            [(1, 'Alice'), (2, 'Bob')],  # First batch for validation
            [(1, 'Alice'), (2, 'Bob')],  # First batch for sync
            [],  # Empty batch to stop sync
            []   # Extra empty batch for safety
        ]
        self.source_connector.fetch_batch = Mock(side_effect=fetch_batch_results)
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        # Mock get_row_count for post-migration verification
        self.target_connector.get_row_count = Mock(return_value=2)
        # Mock fetch_batch for post-migration verification
        self.target_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice'), (2, 'Bob')],  # Target data for verification
            []
        ])
        
        # Mock execution log filter
        with patch('sync_engine.full_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify calls
        self.executor.table_handler.create_table_if_not_exists.assert_called_once()
        self.target_connector.truncate_table.assert_called_once()
        # get_primary_key may be called multiple times (validation + sync)
        self.assertGreaterEqual(self.source_connector.get_primary_key.call_count, 1)
        self.target_connector.bulk_insert.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_failure(self, mock_log_class):
        """Test table sync failure"""
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock table handler to raise error
        self.executor.table_handler.create_table_if_not_exists = Mock(
            side_effect=TableSyncError("Table creation failed")
        )
        
        # Execute sync and expect exception
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
        
        # Verify log was marked as failed
        self.assertEqual(mock_log.status, 'failed')
    
    def test_get_db_type_clickhouse(self):
        """Test database type detection for ClickHouse"""
        # Create a proper mock with class name
        from unittest.mock import Mock
        clickhouse_connector = Mock()
        type(clickhouse_connector).__name__ = 'ClickHouseConnector'
        db_type = self.executor._get_db_type(clickhouse_connector)
        self.assertEqual(db_type, 'clickhouse')
    
    def test_optimize_batch_size_clickhouse(self):
        """Test batch size optimization for ClickHouse"""
        clickhouse_source = Mock()
        type(clickhouse_source).__name__ = 'ClickHouseConnector'
        clickhouse_target = Mock()
        type(clickhouse_target).__name__ = 'ClickHouseConnector'
        
        # Mock table handler to avoid initialization errors
        with patch('sync_engine.full_sync.TableHandler') as mock_table_handler:
            mock_handler_instance = Mock()
            mock_handler_instance.target_db_type = 'clickhouse'
            mock_table_handler.return_value = mock_handler_instance
            
            executor = FullSyncExecutor(
                job=self.job,
                execution=self.execution,
                source_connector=clickhouse_source,
                target_connector=clickhouse_target
            )
            
            # ClickHouse should support larger batches
            self.assertGreaterEqual(executor.batch_size, 5000)
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    @patch('sync_engine.full_sync.TableHandler')
    def test_sync_table_clickhouse_target(self, mock_table_handler_class, mock_log_class):
        """Test table sync with ClickHouse as target"""
        # Mock ClickHouse target connector
        clickhouse_target = Mock()
        type(clickhouse_target).__name__ = 'ClickHouseConnector'
        clickhouse_target.database_name = 'test_db'
        clickhouse_target.get_tables = Mock(return_value=['users'])
        clickhouse_target.truncate_table = Mock()
        clickhouse_target.bulk_insert = Mock()
        
        # Mock source connector
        source_connector = Mock()
        type(source_connector).__name__ = 'PostgresConnector'
        
        # Mock table handler
        mock_table_handler = Mock()
        mock_table_handler.target_db_type = 'clickhouse'
        mock_table_handler.create_table_if_not_exists = Mock(return_value=True)
        mock_table_handler_class.return_value = mock_table_handler
        
        executor = FullSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=source_connector,
            target_connector=clickhouse_target
        )
        
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock source connector
        source_connector.get_primary_key = Mock(return_value=['id'])
        source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        executor.query_builder.build_select_query = Mock(return_value='SELECT * FROM "public"."users"')
        source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice'), (2, 'Bob')],
            []
        ])
        
        # Mock execution log filter
        with patch('sync_engine.full_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            executor.sync_table(job_table)
        
        # Verify ClickHouse-specific calls
        # ClickHouse should use schema as database name
        clickhouse_target.bulk_insert.assert_called_once()
        call_args = clickhouse_target.bulk_insert.call_args
        self.assertEqual(call_args[1]['schema'], 'public')  # Schema mapped to database


if __name__ == '__main__':
    unittest.main()



