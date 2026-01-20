"""
Comprehensive integration tests for perfect data accuracy with enhanced validation
Tests the complete flow: pre-migration validation -> migration -> post-migration verification
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


class PerfectDataAccuracyTest(TransactionTestCase):
    """Test perfect data accuracy with enhanced validation"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='perfectaccuracy',
            password='testpass123',
            email='perfectaccuracy@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        try:
            pg_conn = DatabaseConnection.objects.filter(
                db_type='postgres',
                created_by=self.user
            ).first()
            
            if pg_conn:
                self.postgres_config = {
                    'host': pg_conn.host,
                    'port': pg_conn.port,
                    'username': pg_conn.username,
                    'password': pg_conn.get_decrypted_password(),
                    'database': pg_conn.database_name,
                }
            else:
                self.postgres_config = {
                    'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
                    'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
                    'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
                    'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
                    'database': os.getenv('TEST_POSTGRES_DB', 'tauseef'),
                }
        except Exception as e:
            logger.warning(f"Could not load PostgreSQL connection: {str(e)}")
            self.postgres_config = None
    
    def _check_database_available(self):
        """Check if test database is available"""
        if not self.postgres_config:
            return False
        
        try:
            from connections.connectors.postgres import PostgresConnector
            connector = PostgresConnector(
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database']
            )
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"Database not available: {str(e)}")
            return False
    
    def _create_test_table_with_data(self, connector, schema, table_name):
        """Create a test table with comprehensive test data"""
        connector.connect()
        try:
            connector.ensure_schema_exists(schema)
            
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table_name}')
            except:
                pass
            
            create_sql = f'''
                CREATE TABLE {schema}.{table_name} (
                    id SERIAL PRIMARY KEY,
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
            
            insert_sql = f'''
                INSERT INTO {schema}.{table_name} (name, email, age, salary, is_active, created_at, description)
                VALUES
                    ('  John Doe  ', 'john@example.com', 25, 50000.00, true, '2024-01-01', '  Test Description  '),
                    ('Jane Smith', 'JANE@EXAMPLE.COM', 30, 60000.00, true, '2024-01-02', 'Test Description 2'),
                    ('Bob Johnson', 'bob@example.com', 35, 70000.00, false, '2024-01-03', 'Test Description 3'),
                    ('Alice Brown', 'ALICE@EXAMPLE.COM', 28, 55000.00, true, '2024-01-04', '  Test Description 4  '),
                    ('Charlie Wilson', 'charlie@example.com', 40, 80000.00, true, '2024-01-05', 'Test Description 5')
            '''
            connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_full_sync_with_enhanced_validation_where_clause(self):
        """Test full sync with enhanced pre and post-migration validation (WHERE clause)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_enhanced'
        target_table = 'test_target_enhanced'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Enhanced',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Enhanced',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            # Create sync job with WHERE clause transformation
            job = SyncJob.objects.create(
                name='Test Enhanced Validation WHERE',
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
                transformation_query="age >= 30",  # Filter rows with age >= 30
                column_transformations=None
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify data accuracy
            target_connector.connect()
            target_count = target_connector.get_row_count(schema, target_table)
            target_connector.close()
            
            # Expected: 3 rows (Jane age=30, Bob age=35, Charlie age=40)
            self.assertEqual(target_count, 3, f"Expected 3 rows, got {target_count}")
            
            # Verify execution completed successfully
            execution.refresh_from_db()
            self.assertEqual(execution.status, 'completed')
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_full_sync_with_enhanced_validation_column_transformations(self):
        """Test full sync with enhanced validation (column transformations)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_cols_enhanced'
        target_table = 'test_target_cols_enhanced'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Cols Enhanced',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Cols Enhanced',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            # Create sync job with column transformations
            job = SyncJob.objects.create(
                name='Test Enhanced Validation Columns',
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
                column_transformations={'name': 'TRIM', 'email': 'UPPER', 'description': 'TRIM'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify data accuracy
            target_connector.connect()
            target_count = target_connector.get_row_count(schema, target_table)
            
            # Verify transformations were applied
            rows = target_connector.fetch_batch(
                f'SELECT name, email, description FROM {schema}.{target_table} ORDER BY id',
                batch_size=100,
                offset=0
            )
            target_connector.close()
            
            # Expected: All 5 rows (no WHERE clause)
            self.assertEqual(target_count, 5, f"Expected 5 rows, got {target_count}")
            
            # Check first row (John Doe) - should have TRIM and UPPER applied
            if rows:
                name, email, desc = rows[0]
                # Name should be trimmed (no leading/trailing spaces)
                self.assertEqual(name, 'John Doe')
                # Email should be uppercase
                self.assertEqual(email, 'JOHN@EXAMPLE.COM')
                # Description should be trimmed
                self.assertEqual(desc, 'Test Description')
            
            # Verify execution completed successfully
            execution.refresh_from_db()
            self.assertEqual(execution.status, 'completed')
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_full_sync_with_enhanced_validation_combined(self):
        """Test full sync with enhanced validation (WHERE + column transformations)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_combined_enhanced'
        target_table = 'test_target_combined_enhanced'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Combined Enhanced',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Combined Enhanced',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            # Create sync job with combined transformations
            job = SyncJob.objects.create(
                name='Test Enhanced Validation Combined',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with both transformations
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30 AND is_active = true",  # Filter active users >= 30
                column_transformations={'name': 'TRIM', 'email': 'UPPER'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify data accuracy
            target_connector.connect()
            target_count = target_connector.get_row_count(schema, target_table)
            target_connector.close()
            
            # Expected: 2 rows (Jane age=30 active, Charlie age=40 active)
            # Bob is 35 but not active, so excluded
            self.assertEqual(target_count, 2, f"Expected 2 rows, got {target_count}")
            
            # Verify execution completed successfully
            execution.refresh_from_db()
            self.assertEqual(execution.status, 'completed')
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
