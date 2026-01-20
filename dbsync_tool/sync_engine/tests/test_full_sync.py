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
        
        self.source_connector = Mock()
        self.target_connector = Mock()
        
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
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        
        # Mock query builder
        self.executor.query_builder.build_select_query = Mock(return_value='SELECT * FROM "public"."users"')
        
        # Mock batch fetching
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 'Alice'), (2, 'Bob')],  # First batch
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
        
        # Verify calls
        self.executor.table_handler.create_table_if_not_exists.assert_called_once()
        self.target_connector.truncate_table.assert_called_once()
        self.source_connector.get_primary_key.assert_called_once()
        self.target_connector.bulk_insert.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.full_sync.SyncExecutionLog')
    def test_sync_table_failure(self, mock_log_class):
        """Test table sync failure"""
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        
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


if __name__ == '__main__':
    unittest.main()



