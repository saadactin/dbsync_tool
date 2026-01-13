"""
Performance tests for sync engine
"""
import time
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from connections.connectors.base import ColumnInfo
from sync_jobs.tests.test_helpers import create_test_connections, create_test_job
import os
import logging

logger = logging.getLogger(__name__)

class PerformanceTest(TransactionTestCase):
    """Performance benchmarking tests"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='perftest',
            password='testpass123',
            email='perf@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        # Use PostgreSQL for performance tests (most common)
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
    
    def _create_large_table(self, connector, schema, table_name, num_rows):
        """Create a large table with test data"""
        connector.connect()
        try:
            connector.ensure_schema_exists(schema)
            
            # Create table
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='data1', data_type='VARCHAR(255)', is_nullable=True),
                ColumnInfo(name='data2', data_type='INTEGER', is_nullable=True),
                ColumnInfo(name='data3', data_type='TEXT', is_nullable=True),
            ]
            
            if connector.table_exists(schema, table_name):
                connector.truncate_table(schema, table_name)
            else:
                connector.create_table(schema, table_name, columns)
            
            # Insert data in batches
            batch_size = 1000
            column_names = ['id', 'data1', 'data2', 'data3']
            
            for batch_start in range(1, num_rows + 1, batch_size):
                batch_end = min(batch_start + batch_size, num_rows + 1)
                rows = []
                for i in range(batch_start, batch_end):
                    rows.append((
                        i,
                        f'data1_{i}',
                        i * 10,
                        f'This is a longer text field for row {i} with some content.'
                    ))
                connector.bulk_insert(schema, table_name, column_names, rows)
        finally:
            connector.close()
    
    def test_large_table_sync_performance(self):
        """Test sync performance with large tables"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        # Create connections
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        # Create large table (10k rows for performance test)
        source_connector = get_connector(source_conn)
        schema = 'public'
        table_name = 'large_perf_table'
        
        self._create_large_table(source_connector, schema, table_name, 10000)
        
        # Create job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        # Measure sync time
        start_time = time.time()
        executor = SyncExecutor(job)
        executor.execute()
        end_time = time.time()
        
        duration = end_time - start_time
        
        # Assert performance meets requirements (< 5 minutes for 10k rows)
        # This is a reasonable benchmark
        self.assertLess(duration, 300, f"Sync took {duration:.2f} seconds, expected < 300 seconds")
        
        logger.info(f"Large table sync (10k rows) completed in {duration:.2f} seconds")
    
    def test_multiple_tables_sync_performance(self):
        """Test sync performance with multiple tables"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        # Create connections
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        # Create 5 tables with 1k rows each
        source_connector = get_connector(source_conn)
        schema = 'public'
        tables = []
        
        for i in range(1, 6):
            table_name = f'perf_table_{i}'
            self._create_large_table(source_connector, schema, table_name, 1000)
            tables.append((schema, table_name))
        
        # Create job
        job = create_test_job(self.user, source_conn, target_conn, tables)
        
        # Measure sync time
        start_time = time.time()
        executor = SyncExecutor(job)
        executor.execute()
        end_time = time.time()
        
        duration = end_time - start_time
        
        # Assert performance (< 10 minutes for 5 tables with 1k rows each)
        self.assertLess(duration, 600, f"Sync took {duration:.2f} seconds, expected < 600 seconds")
        
        logger.info(f"Multiple tables sync (5 tables, 1k rows each) completed in {duration:.2f} seconds")
    
    def test_batch_size_optimization(self):
        """Test optimal batch size for different database combinations"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        # This test would measure performance with different batch sizes
        # For now, we'll just verify that batch processing works
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        source_connector = get_connector(source_conn)
        schema = 'public'
        table_name = 'batch_test_table'
        
        # Create table with 5k rows
        self._create_large_table(source_connector, schema, table_name, 5000)
        
        # Create job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        # Execute sync
        start_time = time.time()
        executor = SyncExecutor(job)
        executor.execute()
        end_time = time.time()
        
        duration = end_time - start_time
        
        # Verify it completes successfully
        self.assertLess(duration, 180, f"Batch sync took {duration:.2f} seconds")
        
        logger.info(f"Batch size test (5k rows) completed in {duration:.2f} seconds")
    
    def _create_table_with_timestamps(self, connector, schema, table_name, num_rows, start_time):
        """Create a table with timestamp data for incremental sync testing"""
        from datetime import timedelta
        connector.connect()
        try:
            connector.ensure_schema_exists(schema)
            
            # Create table with timestamp column
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='name', data_type='VARCHAR(255)', is_nullable=True),
                ColumnInfo(name='updated_at', data_type='TIMESTAMP', is_nullable=True),
                ColumnInfo(name='created_at', data_type='TIMESTAMP', is_nullable=True),
            ]
            
            if connector.table_exists(schema, table_name):
                connector.truncate_table(schema, table_name)
            else:
                connector.create_table(schema, table_name, columns)
            
            # Insert data with timestamps
            batch_size = 1000
            column_names = ['id', 'name', 'updated_at', 'created_at']
            current_time = start_time
            
            for batch_start in range(1, num_rows + 1, batch_size):
                batch_end = min(batch_start + batch_size, num_rows + 1)
                rows = []
                for i in range(batch_start, batch_end):
                    rows.append((
                        i,
                        f'Record {i}',
                        current_time,
                        current_time
                    ))
                    current_time += timedelta(minutes=1)
                if rows:
                    connector.bulk_insert(schema, table_name, column_names, rows)
        finally:
            connector.close()
    
    def test_large_table_incremental_sync_performance(self):
        """Test incremental sync performance with large table (first sync)"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        from datetime import datetime, timedelta
        import pytz
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        # Create large table with timestamps
        source_connector = get_connector(source_conn)
        schema = 'public'
        table_name = 'large_incremental_table'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        # Create 50k rows for performance test
        self._create_table_with_timestamps(source_connector, schema, table_name, 50000, start_time)
        
        # Create incremental sync job
        job = SyncJob.objects.create(
            name='Large Incremental Test',
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
        
        # Measure first sync time (no checkpoint)
        start_time_sync = time.time()
        executor = SyncExecutor(job)
        executor.execute()
        end_time_sync = time.time()
        
        duration = end_time_sync - start_time_sync
        
        # Assert performance meets requirements (< 5 minutes for 50k rows)
        self.assertLess(duration, 300, f"First incremental sync took {duration:.2f} seconds, expected < 300 seconds")
        
        logger.info(f"Large table incremental sync (50k rows, first sync) completed in {duration:.2f} seconds")
    
    def test_subsequent_incremental_sync_performance(self):
        """Test subsequent incremental sync performance (with checkpoint)"""
        if not self._check_database_available():
            self.skipTest("Test database not available")
        
        from datetime import datetime, timedelta
        import pytz
        from sync_engine.checkpoint_manager import CheckpointManager
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        # Create table with initial data
        source_connector = get_connector(source_conn)
        schema = 'public'
        table_name = 'subsequent_sync_table'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        # Create 10k rows initially
        self._create_table_with_timestamps(source_connector, schema, table_name, 10000, start_time)
        
        # Create incremental sync job
        job = SyncJob.objects.create(
            name='Subsequent Sync Test',
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
        
        # Run first sync to create checkpoint
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify checkpoint created
        checkpoint_manager = CheckpointManager(job)
        checkpoint = checkpoint_manager.get_checkpoint(schema, table_name)
        self.assertIsNotNone(checkpoint)
        
        # Add new data (5k more rows with later timestamps)
        new_start_time = start_time + timedelta(hours=1)
        self._create_table_with_timestamps(source_connector, schema, table_name, 5000, new_start_time)
        
        # Measure subsequent sync time (with checkpoint)
        start_time_sync = time.time()
        executor = SyncExecutor(job)
        executor.execute()
        end_time_sync = time.time()
        
        duration = end_time_sync - start_time_sync
        
        # Subsequent sync should be faster (only processing 5k new rows)
        self.assertLess(duration, 60, f"Subsequent incremental sync took {duration:.2f} seconds, expected < 60 seconds")
        
        logger.info(f"Subsequent incremental sync (5k new rows) completed in {duration:.2f} seconds")
    
    def test_checkpoint_update_performance(self):
        """Test checkpoint update performance overhead"""
        from sync_engine.checkpoint_manager import CheckpointManager
        from datetime import datetime
        import pytz
        
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'postgres', self.source_config, self.source_config
        )
        
        job = SyncJob.objects.create(
            name='Checkpoint Update Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        checkpoint_manager = CheckpointManager(job)
        
        # Measure checkpoint update time
        start_time = time.time()
        for i in range(100):
            checkpoint_manager.create_or_update_checkpoint(
                'public', f'table_{i}', datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
            )
        end_time = time.time()
        
        duration = end_time - start_time
        
        # Checkpoint updates should be fast (< 1 second for 100 updates)
        self.assertLess(duration, 1.0, f"Checkpoint updates took {duration:.2f} seconds, expected < 1.0 seconds")
        
        logger.info(f"Checkpoint update test (100 updates) completed in {duration:.2f} seconds")

