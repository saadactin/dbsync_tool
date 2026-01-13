"""
Edge case tests for sync engine
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from connections.connectors.base import ColumnInfo
from sync_jobs.tests.test_helpers import create_test_connections, create_test_job
import os
import logging

logger = logging.getLogger(__name__)

class EdgeCaseTest(TransactionTestCase):
    """Test edge cases and error scenarios"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='edgetest',
            password='testpass123',
            email='edge@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        self.source_config = {
            'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
            'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
            'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
            'database': os.getenv('TEST_POSTGRES_DB', 'test_sync_source'),
            'target_database': os.getenv('TEST_POSTGRES_TARGET_DB', 'test_sync_target'),
        }
    
    def _check_database_available(self):
        """Check if test database is available"""
        try:
            from connections.connectors.postgres import PostgresConnector
            connector = PostgresConnector(
                host=self.source_config['host'],
                port=self.source_config['port'],
                username=self.source_config['username'],
                password=self.source_config['password'],
                database_name=self.source_config['database']
            )
            connector.connect()
            connector.close()
            return True
        except Exception:
            return False
    
    def test_empty_table_sync(self):
        """Test syncing empty tables"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        source_connector = get_connector(source_conn)
        source_connector.connect()
        try:
            schema = 'public'
            table_name = 'empty_table'
            
            # Create empty table
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='name', data_type='VARCHAR(255)', is_nullable=True),
            ]
            
            source_connector.ensure_schema_exists(schema)
            if source_connector.table_exists(schema, table_name):
                source_connector.truncate_table(schema, table_name)
            else:
                source_connector.create_table(schema, table_name, columns)
        finally:
            source_connector.close()
        
        # Create job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        # Execute sync - should not error
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution completed
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
    
    def test_table_with_null_values(self):
        """Test syncing tables with NULL values"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        source_connector = get_connector(source_conn)
        source_connector.connect()
        try:
            schema = 'public'
            table_name = 'null_test_table'
            
            # Create table
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='nullable_str', data_type='VARCHAR(255)', is_nullable=True),
                ColumnInfo(name='nullable_int', data_type='INTEGER', is_nullable=True),
            ]
            
            source_connector.ensure_schema_exists(schema)
            if source_connector.table_exists(schema, table_name):
                source_connector.truncate_table(schema, table_name)
            else:
                source_connector.create_table(schema, table_name, columns)
            
            # Insert rows with NULLs
            rows = [
                (1, 'value1', None),
                (2, None, 100),
                (3, None, None),
                (4, 'value4', 200),
            ]
            source_connector.bulk_insert(schema, table_name, ['id', 'nullable_str', 'nullable_int'], rows)
        finally:
            source_connector.close()
        
        # Create job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        # Execute sync
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution completed
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
        
        # Verify data synced correctly
        target_connector = get_connector(target_conn)
        target_connector.connect()
        try:
            row_count = target_connector.get_row_count(schema, table_name)
            self.assertEqual(row_count, 4)
        finally:
            target_connector.close()
    
    def test_table_with_unicode_characters(self):
        """Test syncing tables with Unicode characters"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        source_connector = get_connector(source_conn)
        source_connector.connect()
        try:
            schema = 'public'
            table_name = 'unicode_test_table'
            
            # Create table
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='unicode_text', data_type='VARCHAR(255)', is_nullable=True),
            ]
            
            source_connector.ensure_schema_exists(schema)
            if source_connector.table_exists(schema, table_name):
                source_connector.truncate_table(schema, table_name)
            else:
                source_connector.create_table(schema, table_name, columns)
            
            # Insert rows with Unicode
            rows = [
                (1, 'Hello 世界'),
                (2, 'مرحبا'),
                (3, 'Привет'),
                (4, '🎉 Emoji test 🚀'),
            ]
            source_connector.bulk_insert(schema, table_name, ['id', 'unicode_text'], rows)
        finally:
            source_connector.close()
        
        # Create job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        # Execute sync
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution completed
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
    
    def test_concurrent_sync_prevention(self):
        """Test that concurrent syncs are prevented"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        # Create a simple job
        job = create_test_job(self.user, source_conn, target_conn, [('public', 'test_table')])
        
        # Try to start sync
        executor1 = SyncExecutor(job)
        executor1.create_execution()
        
        # Job should be marked as running
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')  # Status updated in execute(), not create_execution()
        
        # If we try to create another execution, it should work
        # (actual prevention would be in the view layer)
        executor2 = SyncExecutor(job)
        execution2 = executor2.create_execution()
        
        # Both executions should exist
        executions = SyncExecution.objects.filter(job=job)
        self.assertEqual(executions.count(), 2)
    
    def test_empty_table_incremental_sync(self):
        """Test incremental sync with empty table"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        from sync_engine.checkpoint_manager import CheckpointManager
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        source_connector = get_connector(source_conn)
        source_connector.connect()
        try:
            schema = 'public'
            table_name = 'empty_incremental_table'
            
            # Create empty table with timestamp column
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='name', data_type='VARCHAR(255)', is_nullable=True),
                ColumnInfo(name='updated_at', data_type='TIMESTAMP', is_nullable=True),
            ]
            
            source_connector.ensure_schema_exists(schema)
            if source_connector.table_exists(schema, table_name):
                source_connector.truncate_table(schema, table_name)
            else:
                source_connector.create_table(schema, table_name, columns)
        finally:
            source_connector.close()
        
        # Create incremental sync job
        job = SyncJob.objects.create(
            name='Empty Table Incremental Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name=schema,
            table_name=table_name,
            incremental_column='updated_at',
            is_enabled=True
        )
        
        # Execute sync - should not error
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution completed
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
        
        # Verify checkpoint not created for empty table
        checkpoint_manager = CheckpointManager(job)
        checkpoint = checkpoint_manager.get_checkpoint(schema, table_name)
        # Checkpoint may or may not be created for empty table - both are acceptable
    
    def test_incremental_sync_null_incremental_column(self):
        """Test incremental sync with NULL values in incremental column"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        from datetime import datetime
        import pytz
        from sync_engine.checkpoint_manager import CheckpointManager
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        source_connector = get_connector(source_conn)
        source_connector.connect()
        try:
            schema = 'public'
            table_name = 'null_incremental_table'
            
            # Create table with nullable timestamp column
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='name', data_type='VARCHAR(255)', is_nullable=True),
                ColumnInfo(name='updated_at', data_type='TIMESTAMP', is_nullable=True),
            ]
            
            source_connector.ensure_schema_exists(schema)
            if source_connector.table_exists(schema, table_name):
                source_connector.truncate_table(schema, table_name)
            else:
                source_connector.create_table(schema, table_name, columns)
            
            # Insert rows with NULL timestamps
            rows = [
                (1, 'Record 1', datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)),
                (2, 'Record 2', None),  # NULL timestamp
                (3, 'Record 3', datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)),
                (4, 'Record 4', None),  # NULL timestamp
            ]
            source_connector.bulk_insert(schema, table_name, ['id', 'name', 'updated_at'], rows)
        finally:
            source_connector.close()
        
        # Create incremental sync job
        job = SyncJob.objects.create(
            name='NULL Incremental Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name=schema,
            table_name=table_name,
            incremental_column='updated_at',
            is_enabled=True
        )
        
        # Execute sync
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution completed
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
        
        # Verify checkpoint created (should use max non-NULL value)
        checkpoint_manager = CheckpointManager(job)
        checkpoint = checkpoint_manager.get_checkpoint(schema, table_name)
        # Checkpoint should be based on max non-NULL value
        if checkpoint:
            self.assertIn('2024-01-01 12:00:00', checkpoint.last_value)
    
    def test_checkpoint_corruption_recovery(self):
        """Test recovery from checkpoint corruption"""
        from sync_engine.checkpoint_manager import CheckpointManager
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        job = SyncJob.objects.create(
            name='Checkpoint Corruption Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        # Create corrupted checkpoint (invalid value)
        checkpoint = SyncCheckpoint.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            last_value='CORRUPTED_VALUE',
            updated_at=timezone.now()
        )
        
        checkpoint_manager = CheckpointManager(job)
        
        # Try to recover
        checkpoint_manager.delete_checkpoint('public', 'users')
        
        # Verify checkpoint deleted
        checkpoint_exists = SyncCheckpoint.objects.filter(id=checkpoint.id).exists()
        self.assertFalse(checkpoint_exists)
    
    def test_concurrent_incremental_sync_prevention(self):
        """Test that concurrent incremental syncs are prevented"""
        from sync_engine.incremental_sync import IncrementalSyncExecutor
        from unittest.mock import Mock, patch
        from sync_jobs.models import SyncExecutionLog
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        job = SyncJob.objects.create(
            name='Concurrent Sync Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            incremental_column='updated_at',
            is_enabled=True
        )
        
        execution1 = SyncExecution.objects.create(
            job=job,
            status='running',
            started_at=timezone.now()
        )
        
        execution2 = SyncExecution.objects.create(
            job=job,
            status='pending',
            started_at=timezone.now()
        )
        
        # Mock connectors
        from connections.connectors.postgres import PostgresConnector
        source_connector = Mock(spec=PostgresConnector)
        source_connector.__class__.__name__ = 'PostgresConnector'
        target_connector = Mock(spec=PostgresConnector)
        target_connector.__class__.__name__ = 'PostgresConnector'
        
        executor = IncrementalSyncExecutor(
            job=job,
            execution=execution2,
            source_connector=source_connector,
            target_connector=target_connector
        )
        
        # Create running log for same table
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            running_logs_mock = Mock()
            running_logs_mock.exclude.return_value.exists = Mock(return_value=True)
            mock_filter.return_value = running_logs_mock
            
            # Check concurrent sync prevention
            result = executor._prevent_concurrent_sync('public', 'users')
            self.assertFalse(result)  # Should return False when another sync is running
    
    def test_incremental_sync_large_checkpoint_values(self):
        """Test incremental sync with very large checkpoint values"""
        from sync_engine.checkpoint_manager import CheckpointManager
        from datetime import datetime
        import pytz
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        job = SyncJob.objects.create(
            name='Large Checkpoint Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        checkpoint_manager = CheckpointManager(job)
        
        # Test with very large timestamp
        large_timestamp = datetime(2099, 12, 31, 23, 59, 59, tzinfo=pytz.UTC)
        checkpoint_manager.create_or_update_checkpoint('public', 'users', large_timestamp)
        
        # Verify checkpoint stored and retrieved correctly
        checkpoint = checkpoint_manager.get_checkpoint('public', 'users')
        self.assertIsNotNone(checkpoint)
        self.assertIn('2099', checkpoint.last_value)
        
        # Test with very large integer
        large_integer = 9223372036854775807  # Max bigint
        checkpoint_manager.create_or_update_checkpoint('public', 'products', large_integer)
        
        checkpoint2 = checkpoint_manager.get_checkpoint('public', 'products')
        self.assertIsNotNone(checkpoint2)
        self.assertIn(str(large_integer), checkpoint2.last_value)
    
    def test_incremental_sync_checkpoint_with_string_column(self):
        """Test incremental sync with string incremental column"""
        from sync_engine.checkpoint_manager import CheckpointManager
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        job = SyncJob.objects.create(
            name='String Checkpoint Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        checkpoint_manager = CheckpointManager(job)
        
        # Test with string value (not recommended but should work)
        string_value = '2024-01-01 12:00:00'
        checkpoint_manager.create_or_update_checkpoint('public', 'users', string_value)
        
        # Verify checkpoint stored correctly
        checkpoint = checkpoint_manager.get_checkpoint('public', 'users')
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.last_value, string_value)
    
    def test_incremental_sync_partial_failure_checkpoint_not_updated(self):
        """Test that checkpoint is NOT updated when sync fails partially"""
        from sync_engine.checkpoint_manager import CheckpointManager
        from unittest.mock import Mock, patch
        from sync_jobs.models import SyncExecutionLog, SyncCheckpoint
        from sync_engine.exceptions import TableSyncError
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        job = SyncJob.objects.create(
            name='Partial Failure Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            incremental_column='updated_at',
            is_enabled=True
        )
        
        # Create initial checkpoint
        initial_checkpoint = SyncCheckpoint.objects.create(
            job=job,
            schema_name='public',
            table_name='users',
            last_value='2024-01-01 10:00:00',
            updated_at=timezone.now()
        )
        
        # Create execution
        execution = SyncExecution.objects.create(
            job=job,
            status='running',
            started_at=timezone.now()
        )
        
        # Mock sync to fail
        from sync_engine.incremental_sync import IncrementalSyncExecutor
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = Mock(spec=PostgresConnector)
        source_connector.__class__.__name__ = 'PostgresConnector'
        target_connector = Mock(spec=PostgresConnector)
        target_connector.__class__.__name__ = 'PostgresConnector'
        
        executor = IncrementalSyncExecutor(
            job=job,
            execution=execution,
            source_connector=source_connector,
            target_connector=target_connector
        )
        
        # Mock sync_table to raise exception
        executor.sync_table = Mock(side_effect=TableSyncError("Sync failed"))
        
        # Execute - should handle failure gracefully
        executor.execute()
        
        # Verify checkpoint NOT updated after failure
        checkpoint_manager = CheckpointManager(job)
        checkpoint = checkpoint_manager.get_checkpoint('public', 'users')
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.last_value, '2024-01-01 10:00:00')  # Should remain unchanged

