"""
Data accuracy tests for transformation queries
Verifies zero data loss and perfect accuracy with transformations
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from connections.connectors.base import ColumnInfo
import os
import logging

logger = logging.getLogger(__name__)


class TransformationDataAccuracyTest(TransactionTestCase):
    """Test data accuracy with transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='transformationaccuracy',
            password='testpass123',
            email='transformationaccuracy@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        # Try to get existing connections or use defaults
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
            
            # Drop table if exists
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table_name}')
            except:
                pass
            
            # Create table
            create_sql = f'''
                CREATE TABLE {schema}.{table_name} (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    email VARCHAR(255),
                    age INTEGER,
                    salary DECIMAL(10,2),
                    is_active BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            '''
            connector.execute_query(create_sql)
            
            # Insert comprehensive test data
            insert_sql = f"""
                INSERT INTO {schema}.{table_name} (name, email, age, salary, is_active, created_at, description)
                VALUES
                    ('  John Doe  ', 'JOHN@EXAMPLE.COM', 25, 50000.00, true, '2020-01-01', '  Test Description  '),
                    ('Jane Smith', 'jane@example.com', 30, 60000.00, true, '2021-01-01', 'Another description'),
                    ('  Bob Johnson  ', 'BOB@EXAMPLE.COM', 35, 70000.00, false, '2022-01-01', NULL),
                    ('Alice Brown', 'alice@example.com', 28, 55000.00, true, '2023-01-01', 'Test with ''quotes'''),
                    (NULL, 'nullname@example.com', 40, 80000.00, true, '2024-01-01', 'NULL name test')
            """
            connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def _verify_data_accuracy(self, source_connector, target_connector, source_schema, target_schema, table_name, expected_row_count):
        """
        Verify 100% data accuracy between source and target
        
        Args:
            source_connector: Source database connector
            target_connector: Target database connector
            source_schema: Source schema name
            target_schema: Target schema name
            table_name: Table name
            expected_row_count: Expected number of rows after transformation
        """
        source_connector.connect()
        target_connector.connect()
        
        try:
            # 1. Verify row count matches expected
            target_count = target_connector.get_row_count(target_schema, table_name)
            self.assertEqual(
                target_count, expected_row_count,
                f"Row count mismatch: expected={expected_row_count}, target={target_count}"
            )
            
            # 2. Verify column structure
            source_columns = source_connector.get_columns(source_schema, table_name)
            target_columns = target_connector.get_columns(target_schema, table_name)
            
            source_col_names = {col.name for col in source_columns}
            target_col_names = {col.name for col in target_columns}
            
            self.assertEqual(
                source_col_names, target_col_names,
                f"Column mismatch: source={source_col_names}, target={target_col_names}"
            )
            
            # 3. Verify data integrity (compare all rows)
            source_rows = source_connector.fetch_batch(
                f'SELECT * FROM {source_schema}.{table_name} ORDER BY id',
                batch_size=100,
                offset=0
            )
            target_rows = target_connector.fetch_batch(
                f'SELECT * FROM {target_schema}.{table_name} ORDER BY id',
                batch_size=100,
                offset=0
            )
            
            self.assertEqual(
                len(source_rows), len(target_rows),
                f"Row count mismatch in fetched data: source={len(source_rows)}, target={len(target_rows)}"
            )
            
            # Compare each row
            for i, (source_row, target_row) in enumerate(zip(source_rows, target_rows)):
                self.assertEqual(
                    len(source_row), len(target_row),
                    f"Column count mismatch at row {i}: source={len(source_row)}, target={len(target_row)}"
                )
                
                # Compare each column value
                for j, (source_val, target_val) in enumerate(zip(source_row, target_row)):
                    # Handle NULL values
                    if source_val is None:
                        self.assertIsNone(
                            target_val,
                            f"NULL mismatch at row {i}, column {j}: source=NULL, target={target_val}"
                        )
                    else:
                        # Compare values (handle type conversions)
                        if isinstance(source_val, float) and isinstance(target_val, float):
                            self.assertAlmostEqual(
                                source_val, target_val, places=2,
                                msg=f"Value mismatch at row {i}, column {j}: source={source_val}, target={target_val}"
                            )
                        else:
                            self.assertEqual(
                                source_val, target_val,
                                f"Value mismatch at row {i}, column {j}: source={source_val}, target={target_val}"
                            )
            
            logger.info(f"✓ Data accuracy verified: {target_count} rows, {len(source_col_names)} columns")
            return True
            
        except Exception as e:
            logger.error(f"Data accuracy verification failed: {str(e)}")
            raise
        finally:
            source_connector.close()
            target_connector.close()
    
    def test_full_sync_with_where_clause_transformation(self):
        """Test full sync with WHERE clause transformation - verify zero data loss"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_where'
        target_table = 'test_target_where'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target',
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
                name='Test WHERE Transformation',
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
            # Expected: 3 rows (Jane, Bob, Alice have age >= 30)
            self._verify_data_accuracy(
                source_connector, target_connector,
                schema, schema,
                target_table,
                expected_row_count=3
            )
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_full_sync_with_column_transformations(self):
        """Test full sync with column transformations - verify perfect accuracy"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_cols'
        target_table = 'test_target_cols'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Cols',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Cols',
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
                name='Test Column Transformation',
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
            
            # Verify data accuracy
            # Expected: All 5 rows (no WHERE clause)
            self._verify_data_accuracy(
                source_connector, target_connector,
                schema, schema,
                target_table,
                expected_row_count=5
            )
            
            # Verify transformations were applied
            target_connector.connect()
            rows = target_connector.fetch_batch(
                f'SELECT name, email, description FROM {schema}.{target_table} ORDER BY id',
                batch_size=100,
                offset=0
            )
            target_connector.close()
            
            # Check first row (John Doe)
            name, email, desc = rows[0]
            self.assertEqual(name, 'John Doe')  # Should be trimmed
            self.assertEqual(email, 'john@example.com')  # Should be lowercase
            self.assertEqual(desc, 'Test Description')  # Should be trimmed
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_full_sync_with_combined_transformations(self):
        """Test full sync with both WHERE clause and column transformations"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_combined'
        target_table = 'test_target_combined'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Combined',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Combined',
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
                name='Test Combined Transformation',
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
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify data accuracy
            # Expected: 2 rows (Jane age=30, Alice age=28 but is_active=true - wait, Alice is 28, so only Jane)
            # Actually: Jane (30, active) - only one row
            self._verify_data_accuracy(
                source_connector, target_connector,
                schema, schema,
                target_table,
                expected_row_count=1
            )
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_transformation_preserves_null_values(self):
        """Test that NULL values are preserved correctly with transformations"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_nulls'
        target_table = 'test_target_nulls'
        
        # Create source table with NULL values
        source_connector.connect()
        try:
            source_connector.ensure_schema_exists(schema)
            try:
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
            except:
                pass
            
            create_sql = f'''
                CREATE TABLE {schema}.{source_table} (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    email VARCHAR(255),
                    description TEXT
                )
            '''
            source_connector.execute_query(create_sql)
            
            insert_sql = f'''
                INSERT INTO {schema}.{source_table} (name, email, description)
                VALUES
                    ('  John  ', 'JOHN@EXAMPLE.COM', 'Test'),
                    (NULL, 'nullname@example.com', NULL),
                    ('Jane', NULL, 'Another test'),
                    (NULL, NULL, NULL)
            '''
            source_connector.execute_query(insert_sql)
        finally:
            source_connector.close()
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Nulls',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Nulls',
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
                name='Test NULL Preservation',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with transformations
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query=None,
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify NULL values are preserved
            target_connector.connect()
            rows = target_connector.fetch_batch(
                f'SELECT name, email, description FROM {schema}.{target_table} ORDER BY id',
                batch_size=100,
                offset=0
            )
            target_connector.close()
            
            # Check NULL preservation
            # Row 1: name='John' (trimmed), email='john@example.com' (lowercase), description='Test'
            self.assertEqual(rows[0][0], 'John')
            self.assertEqual(rows[0][1], 'john@example.com')
            self.assertEqual(rows[0][2], 'Test')
            
            # Row 2: name=NULL, email='nullname@example.com' (lowercase), description=NULL
            self.assertIsNone(rows[1][0])
            self.assertEqual(rows[1][1], 'nullname@example.com')
            self.assertIsNone(rows[1][2])
            
            # Row 3: name='Jane' (trimmed), email=NULL, description='Another test'
            self.assertEqual(rows[2][0], 'Jane')
            self.assertIsNone(rows[2][1])
            self.assertEqual(rows[2][2], 'Another test')
            
            # Row 4: name=NULL, email=NULL, description=NULL
            self.assertIsNone(rows[3][0])
            self.assertIsNone(rows[3][1])
            self.assertIsNone(rows[3][2])
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
