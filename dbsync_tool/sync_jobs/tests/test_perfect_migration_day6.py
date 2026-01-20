"""
Comprehensive perfect migration tests for Day 6

Tests perfect migration with transformation queries:
- Zero data loss
- Zero data inaccuracy
- 100% perfect data accuracy
- Query execution before migration
- Perfect post-migration verification
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
import os
import logging

logger = logging.getLogger(__name__)


class PerfectMigrationDay6Test(TransactionTestCase):
    """Test perfect migration with transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='perfectmigrationday6',
            password='testpass123',
            email='perfectmigrationday6@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        # PostgreSQL configuration
        self.postgres_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'username': os.getenv('POSTGRES_USER', 'postgres'),
            'password': os.getenv('POSTGRES_PASSWORD', 'postgres'),
            'database_name': os.getenv('POSTGRES_DB', 'test_db')
        }
    
    def _check_database_available(self):
        """Check if PostgreSQL is available"""
        try:
            from connections.connectors.postgres import PostgresConnector
            connector = PostgresConnector(**self.postgres_config)
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"PostgreSQL not available: {str(e)}")
            return False
    
    def _create_test_table_with_data(self, connector, schema, table_name, row_count=100):
        """Create test table with sample data"""
        connector.connect()
        try:
            connector.ensure_schema_exists(schema)
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table_name}')
            except:
                pass
            
            create_sql = f'''
                CREATE TABLE {schema}.{table_name} (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255),
                    email VARCHAR(255),
                    age INTEGER,
                    salary DECIMAL(10,2),
                    is_active BOOLEAN,
                    created_at TIMESTAMP,
                    description TEXT
                )
            '''
            connector.execute_query(create_sql)
            
            # Insert test data
            for i in range(1, row_count + 1):
                insert_sql = f'''
                    INSERT INTO {schema}.{table_name} (id, name, email, age, salary, is_active, created_at, description)
                    VALUES (
                        {i},
                        '{"  User " + str(i) + "  "}',  -- Name with spaces for TRIM test
                        'User{i}@EXAMPLE.COM',  -- Email in uppercase for LOWER test
                        {20 + (i % 50)},
                        {50000.00 + (i * 100)},
                        {i % 2 == 0},
                        '2024-01-01 00:00:00',
                        'Test Description {i}'
                    )
                '''
                connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_perfect_migration_full_sync_with_where_clause(self):
        """Test perfect migration with WHERE clause - verify 100% accuracy"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_perfect_where'
        target_table = 'test_target_perfect_where'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table, 100):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Perfect',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perfect',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            # Create sync job with WHERE clause transformation
            job = SyncJob.objects.create(
                name='Test Perfect Migration WHERE',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with WHERE clause transformation
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30 AND age <= 50",  # Filter rows
                column_transformations=None
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify perfect migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                # Count rows matching WHERE clause in source
                source_count_query = f'SELECT COUNT(*) FROM {schema}.{source_table} WHERE age >= 30 AND age <= 50'
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                # Count rows in target
                target_count = target_connector.get_row_count(schema, target_table)
                
                # Verify row count matches exactly
                self.assertEqual(
                    target_count, expected_count,
                    f"Row count mismatch: expected={expected_count}, target={target_count}"
                )
                
                # Verify all rows match exactly
                source_rows = source_connector.fetch_batch(
                    f'SELECT * FROM {schema}.{source_table} WHERE age >= 30 AND age <= 50 ORDER BY id',
                    batch_size=1000,
                    offset=0
                )
                target_rows = target_connector.fetch_batch(
                    f'SELECT * FROM {schema}.{target_table} ORDER BY id',
                    batch_size=1000,
                    offset=0
                )
                
                self.assertEqual(len(source_rows), len(target_rows))
                
                # Compare each row
                for i, (source_row, target_row) in enumerate(zip(source_rows, target_rows)):
                    self.assertEqual(
                        source_row, target_row,
                        f"Row {i} mismatch: source={source_row}, target={target_row}"
                    )
                
                logger.info(f"✓ Perfect migration verified: {target_count} rows, 100% accuracy")
                
            finally:
                source_connector.close()
                target_connector.close()
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_perfect_migration_full_sync_with_column_transformations(self):
        """Test perfect migration with column transformations - verify 100% accuracy"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_perfect_cols'
        target_table = 'test_target_perfect_cols'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table, 50):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Perfect Cols',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perfect Cols',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            # Create sync job with column transformations
            job = SyncJob.objects.create(
                name='Test Perfect Migration Columns',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with column transformations
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query=None,
                column_transformations={'name': 'TRIM', 'email': 'LOWER', 'description': 'TRIM'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify perfect migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                # Verify row count
                source_count = source_connector.get_row_count(schema, source_table)
                target_count = target_connector.get_row_count(schema, target_table)
                
                self.assertEqual(target_count, source_count)
                
                # Verify transformations were applied correctly
                source_rows = source_connector.fetch_batch(
                    f'SELECT id, name, email, description FROM {schema}.{source_table} ORDER BY id',
                    batch_size=1000,
                    offset=0
                )
                target_rows = target_connector.fetch_batch(
                    f'SELECT id, name, email, description FROM {schema}.{target_table} ORDER BY id',
                    batch_size=1000,
                    offset=0
                )
                
                self.assertEqual(len(source_rows), len(target_rows))
                
                # Verify transformations
                for source_row, target_row in zip(source_rows, target_rows):
                    source_id, source_name, source_email, source_desc = source_row
                    target_id, target_name, target_email, target_desc = target_row
                    
                    # Verify TRIM on name
                    self.assertEqual(target_name, source_name.strip())
                    
                    # Verify LOWER on email
                    self.assertEqual(target_email, source_email.lower())
                    
                    # Verify TRIM on description
                    self.assertEqual(target_desc, source_desc.strip())
                
                logger.info(f"✓ Perfect migration with transformations verified: {target_count} rows")
                
            finally:
                source_connector.close()
                target_connector.close()
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_perfect_migration_full_sync_with_combined_transformations(self):
        """Test perfect migration with combined transformations - verify 100% accuracy"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_perfect_combined'
        target_table = 'test_target_perfect_combined'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table, 100):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Perfect Combined',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perfect Combined',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            # Create sync job with combined transformations
            job = SyncJob.objects.create(
                name='Test Perfect Migration Combined',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with both WHERE clause and column transformations
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30 AND is_active = true",
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify perfect migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                # Count rows matching WHERE clause in source
                source_count_query = f'SELECT COUNT(*) FROM {schema}.{source_table} WHERE age >= 30 AND is_active = true'
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                # Count rows in target
                target_count = target_connector.get_row_count(schema, target_table)
                
                # Verify row count matches exactly
                self.assertEqual(target_count, expected_count)
                
                # Verify all rows match with transformations applied
                source_rows = source_connector.fetch_batch(
                    f'SELECT id, name, email, age, salary, is_active, created_at, description FROM {schema}.{source_table} WHERE age >= 30 AND is_active = true ORDER BY id',
                    batch_size=1000,
                    offset=0
                )
                target_rows = target_connector.fetch_batch(
                    f'SELECT id, name, email, age, salary, is_active, created_at, description FROM {schema}.{target_table} ORDER BY id',
                    batch_size=1000,
                    offset=0
                )
                
                self.assertEqual(len(source_rows), len(target_rows))
                
                # Verify transformations and data match
                for source_row, target_row in zip(source_rows, target_rows):
                    source_id, source_name, source_email, source_age, source_salary, source_active, source_created, source_desc = source_row
                    target_id, target_name, target_email, target_age, target_salary, target_active, target_created, target_desc = target_row
                    
                    # Verify ID matches
                    self.assertEqual(target_id, source_id)
                    
                    # Verify TRIM on name
                    self.assertEqual(target_name, source_name.strip())
                    
                    # Verify LOWER on email
                    self.assertEqual(target_email, source_email.lower())
                    
                    # Verify other columns match
                    self.assertEqual(target_age, source_age)
                    self.assertEqual(float(target_salary), float(source_salary))
                    self.assertEqual(target_active, source_active)
                    self.assertEqual(target_desc, source_desc)
                
                logger.info(f"✓ Perfect migration with combined transformations verified: {target_count} rows")
                
            finally:
                source_connector.close()
                target_connector.close()
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
