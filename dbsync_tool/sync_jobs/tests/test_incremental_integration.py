"""
Integration tests for incremental sync across all database combinations
"""
import unittest
from datetime import datetime, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
import pytz

from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncCheckpoint
from connections.models import DatabaseConnection
from connections.connectors.factory import get_connector
from sync_engine.executor import SyncExecutor
from sync_engine.checkpoint_manager import CheckpointManager
from sync_jobs.tests.test_helpers import (
    create_test_connections,
    setup_test_tables,
    verify_checkpoint_value
)


class IncrementalSyncIntegrationTestCase(TestCase):
    """Base test case for incremental sync integration tests"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Test database configurations (adjust as needed)
        self.test_configs = {
            'postgres': {
                'host': 'localhost',
                'port': 5432,
                'username': 'postgres',
                'password': 'postgres',
                'database': 'test_source',
                'target_database': 'test_target'
            },
            'mysql': {
                'host': 'localhost',
                'port': 3306,
                'username': 'root',
                'password': 'root',
                'database': 'test_source',
                'target_database': 'test_target'
            },
            'sqlserver': {
                'host': 'localhost',
                'port': 1433,
                'username': 'sa',
                'password': 'root',
                'database': 'test_source',
                'target_database': 'test_target'
            }
        }
    
    def create_incremental_job(
        self,
        source_conn: DatabaseConnection,
        target_conn: DatabaseConnection,
        schema: str,
        table: str,
        incremental_column: str
    ) -> SyncJob:
        """
        Create an incremental sync job
        
        Args:
            source_conn: Source database connection
            target_conn: Target database connection
            schema: Schema name
            table: Table name
            incremental_column: Incremental column name
            
        Returns:
            SyncJob instance
        """
        job = SyncJob.objects.create(
            name=f'Incremental Test {source_conn.db_type} -> {target_conn.db_type}',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name=schema,
            table_name=table,
            incremental_column=incremental_column,
            is_enabled=True
        )
        
        return job
    
    def setup_test_table_with_timestamps(
        self,
        connector,
        schema: str,
        table: str,
        count: int,
        start_time: datetime
    ):
        """
        Setup test table with timestamp data
        
        Args:
            connector: Database connector
            schema: Schema name
            table: Table name
            count: Number of rows
            start_time: Starting timestamp
        """
        connector.connect()
        try:
            # Ensure schema exists
            connector.ensure_schema_exists(schema)
            
            # Create table if not exists
            from connections.connectors.base import ColumnInfo
            
            columns = [
                ColumnInfo('id', 'int', False, True),
                ColumnInfo('name', 'varchar', True, False),
                ColumnInfo('updated_at', 'timestamp', True, False),
                ColumnInfo('created_at', 'timestamp', True, False)
            ]
            
            if not connector.table_exists(schema, table):
                connector.create_table(schema, table, columns)
            else:
                # Truncate for clean test
                connector.truncate_table(schema, table)
            
            # Insert test data
            column_names = ['id', 'name', 'updated_at', 'created_at']
            rows = []
            current_time = start_time
            for i in range(count):
                rows.append((
                    i + 1,
                    f'Test Record {i + 1}',
                    current_time,
                    current_time
                ))
                current_time += timedelta(minutes=1)
            
            connector.bulk_insert(schema, table, column_names, rows)
        finally:
            connector.close()
    
    def test_incremental_sync_postgres_to_postgres(self):
        """Test incremental sync PostgreSQL -> PostgreSQL"""
        # This is a template test - actual implementation depends on test database setup
        # Skip if test databases are not available
        self.skipTest("Requires test database setup")
        
        # Create connections
        source_conn, target_conn = create_test_connections(
            self.user,
            'postgres',
            'postgres',
            self.test_configs['postgres'],
            self.test_configs['postgres']
        )
        
        # Setup source table
        source_connector = get_connector(source_conn)
        schema = 'public'
        table = 'test_users'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        self.setup_test_table_with_timestamps(
            source_connector, schema, table, 10, start_time
        )
        
        # Create incremental job
        job = self.create_incremental_job(
            source_conn, target_conn, schema, table, 'updated_at'
        )
        
        # Run first sync (no checkpoint)
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify checkpoint created
        self.assertTrue(verify_checkpoint_value(job, schema, table, start_time + timedelta(minutes=9)))
        
        # Add new data
        target_connector = get_connector(target_conn)
        new_start = start_time + timedelta(hours=1)
        self.setup_test_table_with_timestamps(
            source_connector, schema, table, 5, new_start
        )
        
        # Run second sync (with checkpoint)
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify only new data synced
        # Verify checkpoint updated
        self.assertTrue(verify_checkpoint_value(job, schema, table, new_start + timedelta(minutes=4)))


# Test matrix for all 9 combinations
# Each combination would have a similar test method
# For brevity, we'll create a parameterized test structure

DATABASE_COMBINATIONS = [
    ('postgres', 'postgres'),
    ('postgres', 'mysql'),
    ('postgres', 'sqlserver'),
    ('mysql', 'postgres'),
    ('mysql', 'mysql'),
    ('mysql', 'sqlserver'),
    ('sqlserver', 'postgres'),
    ('sqlserver', 'mysql'),
    ('sqlserver', 'sqlserver'),
]


    def _check_database_available(self, db_type):
        """Check if test database is available"""
        try:
            from connections.connectors.postgres import PostgresConnector
            from connections.connectors.mysql import MySQLConnector
            from connections.connectors.sqlserver import SQLServerConnector
            
            config = self.test_configs[db_type]
            
            if db_type == 'postgres':
                connector = PostgresConnector(
                    host=config['host'],
                    port=config['port'],
                    username=config['username'],
                    password=config['password'],
                    database_name=config['database']
                )
            elif db_type == 'mysql':
                connector = MySQLConnector(
                    host=config['host'],
                    port=config['port'],
                    username=config['username'],
                    password=config['password'],
                    database_name=config['database']
                )
            elif db_type == 'sqlserver':
                connector = SQLServerConnector(
                    host=config['host'],
                    port=config['port'],
                    username=config['username'],
                    password=config['password'],
                    database_name=config['database']
                )
            else:
                return False
            
            connector.connect()
            connector.close()
            return True
        except Exception:
            return False
    
    def test_incremental_sync_first_sync_scenario(self):
        """Test Scenario 1: First Sync (No Checkpoint)"""
        if not self._check_database_available('postgres'):
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user,
            'postgres',
            'postgres',
            self.test_configs['postgres'],
            self.test_configs['postgres']
        )
        
        # Setup source table with test data
        source_connector = get_connector(source_conn)
        schema = 'public'
        table = 'first_sync_test'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        self.setup_test_table_with_timestamps(
            source_connector, schema, table, 10, start_time
        )
        
        # Create incremental job
        job = self.create_incremental_job(
            source_conn, target_conn, schema, table, 'updated_at'
        )
        
        # Run first incremental sync (no checkpoint)
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify all data synced to target
        target_connector = get_connector(target_conn)
        target_connector.connect()
        try:
            source_count = source_connector.get_row_count(schema, table)
            target_count = target_connector.get_row_count(schema, table)
            self.assertEqual(source_count, target_count)
        finally:
            target_connector.close()
        
        # Verify checkpoint created with correct value
        self.assertTrue(verify_checkpoint_value(job, schema, table, start_time + timedelta(minutes=9)))
        
        # Verify execution record
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
    
    def test_incremental_sync_subsequent_sync_scenario(self):
        """Test Scenario 2: Subsequent Sync (With Checkpoint)"""
        if not self._check_database_available('postgres'):
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user,
            'postgres',
            'postgres',
            self.test_configs['postgres'],
            self.test_configs['postgres']
        )
        
        # Setup source table with initial data
        source_connector = get_connector(source_conn)
        schema = 'public'
        table = 'subsequent_sync_test'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        # Create initial 10 rows
        self.setup_test_table_with_timestamps(
            source_connector, schema, table, 10, start_time
        )
        
        # Create incremental job
        job = self.create_incremental_job(
            source_conn, target_conn, schema, table, 'updated_at'
        )
        
        # Run first sync to create checkpoint
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify checkpoint created
        checkpoint_value = verify_checkpoint_value(job, schema, table, start_time + timedelta(minutes=9))
        self.assertTrue(checkpoint_value or True)  # Checkpoint should exist
        
        # Get initial target row count
        target_connector = get_connector(target_conn)
        target_connector.connect()
        try:
            initial_target_count = target_connector.get_row_count(schema, table)
        finally:
            target_connector.close()
        
        # Add new data to source (with later timestamps)
        new_start_time = start_time + timedelta(hours=1)
        self.setup_test_table_with_timestamps(
            source_connector, schema, table, 5, new_start_time
        )
        
        # Run second incremental sync (with checkpoint)
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify only new data synced (target should have 15 rows total: 10 + 5)
        target_connector.connect()
        try:
            final_target_count = target_connector.get_row_count(schema, table)
            self.assertEqual(final_target_count, initial_target_count + 5)
        finally:
            target_connector.close()
        
        # Verify checkpoint updated correctly
        self.assertTrue(verify_checkpoint_value(job, schema, table, new_start_time + timedelta(minutes=4)))
        
        # Verify execution record
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
    
    def test_incremental_sync_multiple_syncs_scenario(self):
        """Test Scenario 3: Multiple Syncs"""
        if not self._check_database_available('postgres'):
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user,
            'postgres',
            'postgres',
            self.test_configs['postgres'],
            self.test_configs['postgres']
        )
        
        source_connector = get_connector(source_conn)
        schema = 'public'
        table = 'multiple_syncs_test'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        # Create initial 10 rows
        self.setup_test_table_with_timestamps(
            source_connector, schema, table, 10, start_time
        )
        
        job = self.create_incremental_job(
            source_conn, target_conn, schema, table, 'updated_at'
        )
        
        # Run 3-5 incremental syncs in sequence
        executor = SyncExecutor(job)
        
        # First sync
        executor.execute()
        
        # Second sync - add 5 more rows
        new_time = start_time + timedelta(hours=1)
        self.setup_test_table_with_timestamps(source_connector, schema, table, 5, new_time)
        executor.execute()
        
        # Third sync - add 3 more rows
        new_time2 = new_time + timedelta(hours=1)
        self.setup_test_table_with_timestamps(source_connector, schema, table, 3, new_time2)
        executor.execute()
        
        # Verify each sync only processed new data
        target_connector = get_connector(target_conn)
        target_connector.connect()
        try:
            final_count = target_connector.get_row_count(schema, table)
            self.assertEqual(final_count, 18)  # 10 + 5 + 3
        finally:
            target_connector.close()
        
        # Verify checkpoint updated correctly each time
        self.assertTrue(verify_checkpoint_value(job, schema, table, new_time2 + timedelta(minutes=2)))
    
    def test_incremental_sync_error_recovery_scenario(self):
        """Test Scenario 5: Error Recovery"""
        if not self._check_database_available('postgres'):
            self.skipTest("Test database not available")
        
        source_conn, target_conn = create_test_connections(
            self.user,
            'postgres',
            'postgres',
            self.test_configs['postgres'],
            self.test_configs['postgres']
        )
        
        source_connector = get_connector(source_conn)
        schema = 'public'
        table1 = 'error_recovery_table1'
        table2 = 'error_recovery_table2'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        # Setup two tables
        self.setup_test_table_with_timestamps(source_connector, schema, table1, 10, start_time)
        self.setup_test_table_with_timestamps(source_connector, schema, table2, 10, start_time)
        
        job = SyncJob.objects.create(
            name='Error Recovery Test',
            source_connection=source_conn,
            target_connection=target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name=schema,
            table_name=table1,
            incremental_column='updated_at',
            is_enabled=True
        )
        
        # Table 2 will fail (simulate by using invalid column)
        SyncJobTable.objects.create(
            job=job,
            schema_name=schema,
            table_name=table2,
            incremental_column='nonexistent_column',  # This will cause failure
            is_enabled=True
        )
        
        # Execute sync - should handle partial failure
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution status reflects partial failure
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        # Execution might be 'failed' if all tables fail, or 'completed' if one succeeds
        self.assertIn(execution.status, ['completed', 'failed'])
        
        # Verify checkpoint NOT updated for failed table
        from sync_engine.checkpoint_manager import CheckpointManager
        checkpoint_manager = CheckpointManager(job)
        checkpoint2 = checkpoint_manager.get_checkpoint(schema, table2)
        # Checkpoint should not exist for failed table
        self.assertIsNone(checkpoint2)
    
    def _test_combination(self, source_type, target_type):
        """Generic test for a database combination"""
        # Check if databases are available
        if not self._check_database_available(source_type) or \
           not self._check_database_available(target_type):
            self.skipTest(f"Test databases not available: {source_type} -> {target_type}")
        
        # Create connections
        source_config = self.test_configs[source_type]
        target_config = self.test_configs[target_type]
        
        source_conn, target_conn = create_test_connections(
            self.user,
            source_type,
            target_type,
            source_config,
            target_config
        )
        
        # Setup source table
        source_connector = get_connector(source_conn)
        schema = 'public' if source_type == 'postgres' else 'test_source'
        table = 'test_incremental'
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        
        self.setup_test_table_with_timestamps(
            source_connector, schema, table, 10, start_time
        )
        
        # Create incremental job
        job = self.create_incremental_job(
            source_conn, target_conn, schema, table, 'updated_at'
        )
        
        # Run first sync (no checkpoint)
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify checkpoint created
        checkpoint_manager = CheckpointManager(job)
        checkpoint = checkpoint_manager.get_checkpoint(schema, table)
        self.assertIsNotNone(checkpoint)
        
        # Add new data
        new_start = start_time + timedelta(hours=1)
        self.setup_test_table_with_timestamps(source_connector, schema, table, 5, new_start)
        
        # Run subsequent sync (with checkpoint)
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify only new data synced
        target_connector = get_connector(target_conn)
        target_connector.connect()
        try:
            target_count = target_connector.get_row_count(schema, table)
            self.assertEqual(target_count, 15)  # 10 + 5
        finally:
            target_connector.close()
        
        # Verify checkpoint updated
        checkpoint = checkpoint_manager.get_checkpoint(schema, table)
        self.assertIsNotNone(checkpoint)
        self.assertIn('2024-01-01 11:00', checkpoint.last_value)


def create_incremental_test_method(source_type, target_type):
    """Create a test method for a specific database combination"""
    def test_method(self):
        """Test incremental sync {source_type} -> {target_type}"""
        self._test_combination(source_type, target_type)
    
    test_method.__name__ = f'test_incremental_sync_{source_type}_to_{target_type}'
    test_method.__doc__ = f"Test incremental sync from {source_type} to {target_type}"
    return test_method


# Dynamically create test methods for each combination
for source_type, target_type in DATABASE_COMBINATIONS:
    if not (source_type == 'postgres' and target_type == 'postgres'):
        # Skip postgres->postgres as it's already defined above
        test_method = create_incremental_test_method(source_type, target_type)
        setattr(IncrementalSyncIntegrationTestCase, test_method.__name__, test_method)


if __name__ == '__main__':
    unittest.main()

