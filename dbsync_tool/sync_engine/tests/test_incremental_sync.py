"""
Tests for incremental sync executor
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, SyncCheckpoint
from connections.connectors.base import ColumnInfo
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_engine.exceptions import TableSyncError
import pytz


class TestIncrementalSyncExecutor(unittest.TestCase):
    """Test cases for IncrementalSyncExecutor"""
    
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
    
    def test_init(self):
        """Test IncrementalSyncExecutor initialization"""
        self.assertEqual(self.executor.job, self.job)
        self.assertEqual(self.executor.execution, self.execution)
        self.assertEqual(self.executor.source_connector, self.source_connector)
        self.assertEqual(self.executor.target_connector, self.target_connector)
        self.assertIsNotNone(self.executor.table_handler)
        self.assertIsNotNone(self.executor.validator)
        self.assertIsNotNone(self.executor.checkpoint_manager)
        self.assertIsNotNone(self.executor.query_builder)
        self.assertIsNotNone(self.executor.timezone_handler)
    
    def test_init_invalid_sync_type(self):
        """Test initialization with invalid sync type"""
        self.job.sync_type = 'full'
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=self.execution,
                source_connector=self.source_connector,
                target_connector=self.target_connector
            )
    
    def test_compare_incremental_values_datetime(self):
        """Test comparing datetime values"""
        dt1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        dt2 = datetime(2024, 1, 1, 13, 0, 0, tzinfo=pytz.UTC)
        self.assertTrue(self.executor._compare_incremental_values(dt2, dt1))
        self.assertFalse(self.executor._compare_incremental_values(dt1, dt2))
    
    def test_compare_incremental_values_integer(self):
        """Test comparing integer values"""
        self.assertTrue(self.executor._compare_incremental_values(100, 50))
        self.assertFalse(self.executor._compare_incremental_values(50, 100))
    
    def test_compare_incremental_values_none(self):
        """Test comparing None values"""
        self.assertTrue(self.executor._compare_incremental_values(100, None))
        self.assertFalse(self.executor._compare_incremental_values(None, 100))
    
    def test_get_max_incremental_value(self):
        """Test getting max incremental value from batch"""
        batch = [
            (1, 'Alice', datetime(2024, 1, 1, 10, 0, 0)),
            (2, 'Bob', datetime(2024, 1, 1, 12, 0, 0)),
            (3, 'Charlie', datetime(2024, 1, 1, 11, 0, 0))
        ]
        col_index = 2  # datetime column
        current_max = datetime(2024, 1, 1, 9, 0, 0)
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, datetime(2024, 1, 1, 12, 0, 0))
    
    def test_get_max_incremental_value_with_none(self):
        """Test getting max incremental value with None values"""
        batch = [
            (1, 'Alice', None),
            (2, 'Bob', datetime(2024, 1, 1, 12, 0, 0)),
            (3, 'Charlie', None)
        ]
        col_index = 2
        current_max = None
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, datetime(2024, 1, 1, 12, 0, 0))
    
    def test_validate_incremental_column_success(self):
        """Test successful incremental column validation"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        result = self.executor._validate_incremental_column('public', 'users', 'updated_at')
        self.assertTrue(result)
    
    def test_validate_incremental_column_not_found(self):
        """Test validation with column not found"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True)
        ])
        
        with self.assertRaises(TableSyncError):
            self.executor._validate_incremental_column('public', 'users', 'updated_at')
    
    def test_validate_incremental_column_invalid_type(self):
        """Test validation with invalid column type"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        
        # Should not raise error, but log warning
        result = self.executor._validate_incremental_column('public', 'users', 'name')
        self.assertTrue(result)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_first_sync(self, mock_log_class):
        """Test first sync (no checkpoint)"""
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock checkpoint manager
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Mock batch fetching
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime), (2, test_datetime + timedelta(hours=1))],
            []
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock checkpoint manager
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify checkpoint was created
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_with_checkpoint(self, mock_log_class):
        """Test sync with existing checkpoint"""
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock checkpoint manager
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(
            return_value=str(checkpoint_time)
        )
        
        # Mock timezone handler
        self.executor.timezone_handler.parse_checkpoint_value = Mock(
            return_value=checkpoint_time
        )
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE "updated_at" > \'2024-01-01 10:00:00\' ORDER BY "updated_at"'
        )
        
        # Mock batch fetching (only new data)
        new_datetime = checkpoint_time + timedelta(hours=2)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(3, new_datetime)],
            []
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock checkpoint manager
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify checkpoint was updated
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')
    
    def test_sync_table_no_incremental_column(self):
        """Test sync_table with no incremental column"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = None
        
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
    
    def test_handle_failed_sync(self):
        """Test handling failed sync"""
        error = Exception("Test error")
        checkpoint_value = datetime(2024, 1, 1, 10, 0, 0)
        
        # Should not raise exception
        self.executor._handle_failed_sync('public', 'users', error, checkpoint_value)
    
    def test_handle_partial_batch_failure(self):
        """Test handling partial batch failure"""
        batch = [(1, 'Alice'), (2, 'Bob')]
        
        # Should not raise exception
        self.executor._handle_partial_batch_failure('public', 'users', 1, batch)
    
    def test_recover_from_checkpoint_corruption(self):
        """Test recovering from checkpoint corruption"""
        self.executor.checkpoint_manager.delete_checkpoint = Mock()
        
        self.executor._recover_from_checkpoint_corruption('public', 'users')
        
        self.executor.checkpoint_manager.delete_checkpoint.assert_called_once_with('public', 'users')
    
    def test_prevent_concurrent_sync(self):
        """Test preventing concurrent sync"""
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            # No running logs
            mock_filter.return_value.exclude.return_value.exists = Mock(return_value=False)
            
            result = self.executor._prevent_concurrent_sync('public', 'users')
            self.assertTrue(result)
            
            # Running logs exist
            mock_filter.return_value.exclude.return_value.exists = Mock(return_value=True)
            
            result = self.executor._prevent_concurrent_sync('public', 'users')
            self.assertFalse(result)
    
    def test_execute_no_tables(self):
        """Test execute with no enabled tables"""
        self.job.tables.filter.return_value.exists = Mock(return_value=False)
        
        self.executor.execute()
        
        self.assertEqual(self.execution.status, 'completed')
    
    def test_execute_tables_without_incremental_column(self):
        """Test execute with tables missing incremental column"""
        mock_table = Mock()
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        
        self.job.tables.filter.return_value.exists = Mock(return_value=True)
        self.job.tables.filter.return_value.filter.return_value.exists = Mock(return_value=True)
        self.job.tables.filter.return_value.filter.return_value.__iter__ = Mock(
            return_value=iter([mock_table])
        )
        
        with self.assertRaises(TableSyncError):
            self.executor.execute()
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_success(self, mock_sync_table):
        """Test successful execute"""
        mock_table = Mock(spec=SyncJobTable)
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        mock_table.incremental_column = 'updated_at'
        
        # Setup mocks for tables
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.count = Mock(return_value=1)
        tables_mock.__iter__ = Mock(return_value=iter([mock_table]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.target_connector._connected = False
        self.source_connector.connect = Mock()
        self.target_connector.connect = Mock()
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            completed_logs_mock = Mock()
            completed_logs_mock.count = Mock(return_value=1)
            failed_logs_mock = Mock()
            failed_logs_mock.exists = Mock(return_value=False)
            failed_logs_mock.count = Mock(return_value=0)
            
            # Setup filter to return different mocks based on status
            def filter_side_effect(*args, **kwargs):
                if 'status' in kwargs:
                    if kwargs.get('status') == 'completed':
                        return completed_logs_mock
                    elif kwargs.get('status') == 'failed':
                        return failed_logs_mock
                return completed_logs_mock
            
            mock_filter.side_effect = filter_side_effect
            
            self.executor.execute()
        
        self.assertEqual(self.execution.status, 'completed')
        mock_sync_table.assert_called_once_with(mock_table)
    
    def test_init_invalid_none_job(self):
        """Test initialization with None job"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=None,
                execution=self.execution,
                source_connector=self.source_connector,
                target_connector=self.target_connector
            )
    
    def test_init_invalid_none_execution(self):
        """Test initialization with None execution"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=None,
                source_connector=self.source_connector,
                target_connector=self.target_connector
            )
    
    def test_init_invalid_none_source_connector(self):
        """Test initialization with None source connector"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=self.execution,
                source_connector=None,
                target_connector=self.target_connector
            )
    
    def test_init_invalid_none_target_connector(self):
        """Test initialization with None target connector"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=self.execution,
                source_connector=self.source_connector,
                target_connector=None
            )
    
    def test_compare_incremental_values_string(self):
        """Test comparing string values"""
        self.assertTrue(self.executor._compare_incremental_values('zebra', 'apple'))
        self.assertFalse(self.executor._compare_incremental_values('apple', 'zebra'))
    
    def test_compare_incremental_values_float(self):
        """Test comparing float values"""
        self.assertTrue(self.executor._compare_incremental_values(100.5, 50.2))
        self.assertFalse(self.executor._compare_incremental_values(50.2, 100.5))
    
    def test_get_max_incremental_value_integer(self):
        """Test getting max incremental value with integers"""
        batch = [
            (1, 'Alice', 100),
            (2, 'Bob', 300),
            (3, 'Charlie', 200)
        ]
        col_index = 2
        current_max = 50
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, 300)
    
    def test_get_max_incremental_value_all_none(self):
        """Test getting max incremental value when all values are None"""
        batch = [
            (1, 'Alice', None),
            (2, 'Bob', None),
            (3, 'Charlie', None)
        ]
        col_index = 2
        current_max = datetime(2024, 1, 1, 9, 0, 0)
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, current_max)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_empty_result_set(self, mock_log_class):
        """Test sync with empty result set"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Empty batch
        self.source_connector.fetch_batch = Mock(return_value=[])
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 0})
            
            self.executor.sync_table(job_table)
        
        # Checkpoint should not be updated with empty result
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_not_called()
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_multiple_batches(self, mock_log_class):
        """Test sync with multiple batches"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.batch_size = 2  # Small batch size for testing
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Multiple batches
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime), (2, test_datetime + timedelta(hours=1))],
            [(3, test_datetime + timedelta(hours=2)), (4, test_datetime + timedelta(hours=3))],
            []
        ])
        
        self.target_connector.bulk_insert = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 4})
            
            self.executor.sync_table(job_table)
        
        # Should insert 2 batches
        self.assertEqual(self.target_connector.bulk_insert.call_count, 2)
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_with_integer_checkpoint(self, mock_log_class):
        """Test sync with integer checkpoint value"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'id'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Integer checkpoint
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value='100')
        self.executor.timezone_handler.parse_checkpoint_value = Mock(return_value=100)
        
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE "id" > 100 ORDER BY "id"'
        )
        
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(101, 'New User'), (102, 'Another User')],
            []
        ])
        
        self.target_connector.bulk_insert = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            self.executor.sync_table(job_table)
        
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_mysql_target_schema_mapping(self, mock_log_class):
        """Test sync with MySQL target (schema mapping)"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'mysql'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.target_connector.database_name = 'target_db'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            []
        ])
        
        self.target_connector.bulk_insert = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            self.executor.sync_table(job_table)
        
        # Verify bulk_insert called with target_db schema
        self.target_connector.bulk_insert.assert_called_once()
        call_args = self.target_connector.bulk_insert.call_args
        self.assertEqual(call_args[1]['schema'], 'target_db')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_connection_failure(self, mock_log_class):
        """Test sync with connection failure"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(
            side_effect=Exception("Connection failed")
        )
        
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
        
        self.assertEqual(mock_log.status, 'failed')
        self.assertIsNotNone(mock_log.error_message)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_fetch_batch_failure(self, mock_log_class):
        """Test sync with batch fetch failure"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Simulate fetch failure
        self.source_connector.fetch_batch = Mock(side_effect=Exception("Fetch failed"))
        
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
        
        self.assertEqual(mock_log.status, 'failed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_insert_batch_failure(self, mock_log_class):
        """Test sync with batch insert failure"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(return_value=[(1, test_datetime)])
        
        # Simulate insert failure
        self.target_connector.bulk_insert = Mock(side_effect=Exception("Insert failed"))
        
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
        
        # Checkpoint should NOT be updated on failure
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_not_called()
        self.assertEqual(mock_log.status, 'failed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_no_new_data_checkpoint_unchanged(self, mock_log_class):
        """Test sync when no new data - checkpoint unchanged"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(
            return_value=str(checkpoint_time)
        )
        self.executor.timezone_handler.parse_checkpoint_value = Mock(
            return_value=checkpoint_time
        )
        
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE "updated_at" > \'2024-01-01 10:00:00\' ORDER BY "updated_at"'
        )
        
        # Empty batch - no new data
        self.source_connector.fetch_batch = Mock(return_value=[])
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 0})
            
            self.executor.sync_table(job_table)
        
        # Checkpoint should NOT be updated when max_value == checkpoint_value
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_not_called()
        self.assertEqual(mock_log.status, 'completed')
    
    def test_validate_incremental_column_nullable_warning(self):
        """Test validation with nullable column (should log warning)"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, True)  # nullable
        ])
        
        # Should not raise error, but log warning
        with patch('sync_engine.incremental_sync.logger') as mock_logger:
            result = self.executor._validate_incremental_column('public', 'users', 'updated_at')
            self.assertTrue(result)
            mock_logger.warning.assert_called()
    
    def test_validate_incremental_column_exception_handling(self):
        """Test validation when get_columns raises exception"""
        self.source_connector.get_columns = Mock(side_effect=Exception("Database error"))
        
        with self.assertRaises(TableSyncError):
            self.executor._validate_incremental_column('public', 'users', 'updated_at')
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_connection_failure(self, mock_sync_table):
        """Test execute with connection failure"""
        mock_table = Mock(spec=SyncJobTable)
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        mock_table.incremental_column = 'updated_at'
        
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.__iter__ = Mock(return_value=iter([mock_table]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.source_connector.connect = Mock(side_effect=Exception("Connection failed"))
        
        with self.assertRaises(TableSyncError):
            self.executor.execute()
        
        self.assertEqual(self.execution.status, 'failed')
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_partial_failure(self, mock_sync_table):
        """Test execute with partial failure (some tables succeed, some fail)"""
        mock_table1 = Mock(spec=SyncJobTable)
        mock_table1.schema_name = 'public'
        mock_table1.table_name = 'users'
        mock_table1.incremental_column = 'updated_at'
        
        mock_table2 = Mock(spec=SyncJobTable)
        mock_table2.schema_name = 'public'
        mock_table2.table_name = 'products'
        mock_table2.incremental_column = 'updated_at'
        
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.count = Mock(return_value=2)
        tables_mock.__iter__ = Mock(return_value=iter([mock_table1, mock_table2]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.target_connector._connected = False
        self.source_connector.connect = Mock()
        self.target_connector.connect = Mock()
        
        # First table succeeds, second fails
        def sync_table_side_effect(job_table):
            if job_table.table_name == 'products':
                raise TableSyncError("Sync failed")
        
        mock_sync_table.side_effect = sync_table_side_effect
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            completed_logs_mock = Mock()
            completed_logs_mock.count = Mock(return_value=1)
            failed_logs_mock = Mock()
            failed_logs_mock.exists = Mock(return_value=True)
            failed_logs_mock.count = Mock(return_value=1)
            
            def filter_side_effect(*args, **kwargs):
                if 'status' in kwargs:
                    if kwargs.get('status') == 'completed':
                        return completed_logs_mock
                    elif kwargs.get('status') == 'failed':
                        return failed_logs_mock
                return completed_logs_mock
            
            mock_filter.side_effect = filter_side_effect
            
            self.executor.execute()
        
        # Should be marked as failed due to partial failure
        self.assertEqual(self.execution.status, 'failed')
        self.assertIn('failed to sync', self.execution.error_message)
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_all_tables_failed(self, mock_sync_table):
        """Test execute when all tables fail"""
        mock_table = Mock(spec=SyncJobTable)
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        mock_table.incremental_column = 'updated_at'
        
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.count = Mock(return_value=1)
        tables_mock.__iter__ = Mock(return_value=iter([mock_table]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.target_connector._connected = False
        self.source_connector.connect = Mock()
        self.target_connector.connect = Mock()
        
        # All tables fail
        mock_sync_table.side_effect = TableSyncError("Sync failed")
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            completed_logs_mock = Mock()
            completed_logs_mock.count = Mock(return_value=0)
            failed_logs_mock = Mock()
            failed_logs_mock.exists = Mock(return_value=True)
            failed_logs_mock.count = Mock(return_value=1)
            
            def filter_side_effect(*args, **kwargs):
                if 'status' in kwargs:
                    if kwargs.get('status') == 'completed':
                        return completed_logs_mock
                    elif kwargs.get('status') == 'failed':
                        return failed_logs_mock
                return completed_logs_mock
            
            mock_filter.side_effect = filter_side_effect
            
            self.executor.execute()
        
        # Should be marked as failed - all tables failed
        self.assertEqual(self.execution.status, 'failed')
        self.assertIn('All', self.execution.error_message)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_checkpoint_update_failure_non_blocking(self, mock_log_class):
        """Test that checkpoint update failure doesn't fail the sync"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            []
        ])
        
        self.target_connector.bulk_insert = Mock()
        
        # Checkpoint update fails but shouldn't block sync
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock(
            side_effect=Exception("Checkpoint update failed")
        )
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            # Should not raise exception
            self.executor.sync_table(job_table)
        
        # Sync should still be completed despite checkpoint failure
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_no_primary_key_fallback(self, mock_log_class):
        """Test sync when no primary key - should use incremental column only"""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, False),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # No primary key
        self.source_connector.get_primary_key = Mock(return_value=[])
        
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            []
        ])
        
        self.target_connector.bulk_insert = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            self.executor.sync_table(job_table)
        
        # Verify query builder was called with incremental column only
        call_args = self.executor.query_builder.build_incremental_query.call_args
        self.assertEqual(call_args[1]['order_by'], 'updated_at')


if __name__ == '__main__':
    unittest.main()

