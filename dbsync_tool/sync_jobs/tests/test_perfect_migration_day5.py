"""
Comprehensive perfect migration tests for Day 5
Verifies zero data loss, zero inaccuracy, and 100% perfect data accuracy with transformation queries
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


class PerfectMigrationDay5Test(TransactionTestCase):
    """Comprehensive perfect migration tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='perfectmigration',
            password='testpass123',
            email='perfectmigration@example.com'
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
                    'database_name': pg_conn.database_name,
                }
            else:
                self.postgres_config = {
                    'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
                    'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
                    'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
                    'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
                    'database_name': os.getenv('TEST_POSTGRES_DB', 'tauseef'),
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
            connector = PostgresConnector(**self.postgres_config)
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"Database not available: {str(e)}")
            return False
    
    def _create_test_table_with_data(self, connector, schema, table_name, num_rows=5):
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
                    created_date DATE,
                    description TEXT
                )
            '''
            connector.execute_query(create_sql)
            
            # Insert test data
            insert_sql = f'''
                INSERT INTO {schema}.{table_name} (name, email, age, salary, is_active, created_date, description)
                VALUES
                    ('  John Doe  ', 'JOHN@EXAMPLE.COM', 25, 50000.00, true, '2024-01-01', '  Test Description  '),
                    ('  Jane Smith  ', 'jane@example.com', 30, 60000.00, true, '2024-01-02', '  Another Description  '),
                    ('  Bob Johnson  ', 'BOB@EXAMPLE.COM', 35, 70000.00, false, '2024-01-03', '  Yet Another  '),
                    ('  Alice Brown  ', 'alice@example.com', 28, 55000.00, true, '2024-01-04', '  Final Description  '),
                    (NULL, 'nullname@example.com', 40, 80000.00, true, '2024-01-05', 'NULL name test')
            '''
            connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def _verify_perfect_accuracy(self, source_connector, target_connector, source_schema, target_schema, table_name, expected_row_count, column_transformations=None):
        """
        Verify 100% perfect data accuracy between source and target
        
        Args:
            source_connector: Source database connector
            target_connector: Target database connector
            source_schema: Source schema name
            target_schema: Target schema name
            table_name: Table name
            expected_row_count: Expected number of rows after transformation
            column_transformations: Optional dict of column transformations applied
        """
        source_connector.connect()
        target_connector.connect()
        
        try:
            # 1. Verify row count matches expected exactly
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
                    col_name = source_columns[j].name if j < len(source_columns) else f"col_{j}"
                    
                    # Handle NULL values
                    if source_val is None:
                        self.assertIsNone(
                            target_val,
                            f"NULL mismatch at row {i}, column {col_name}: source=NULL, target={target_val}"
                        )
                    else:
                        # Apply expected transformation if applicable
                        if column_transformations and col_name in column_transformations:
                            transformation = column_transformations[col_name].upper()
                            if transformation == 'TRIM' and isinstance(source_val, str):
                                expected_val = source_val.strip()
                            elif transformation == 'UPPER' and isinstance(source_val, str):
                                expected_val = source_val.upper()
                            elif transformation == 'LOWER' and isinstance(source_val, str):
                                expected_val = source_val.lower()
                            else:
                                expected_val = source_val
                        else:
                            expected_val = source_val
                        
                        # Compare values (handle type conversions)
                        if isinstance(expected_val, float) and isinstance(target_val, float):
                            self.assertAlmostEqual(
                                expected_val, target_val, places=2,
                                msg=f"Value mismatch at row {i}, column {col_name}: expected={expected_val}, target={target_val}"
                            )
                        else:
                            self.assertEqual(
                                expected_val, target_val,
                                f"Value mismatch at row {i}, column {col_name}: expected={expected_val}, target={target_val}"
                            )
            
            logger.info(f"✓ Perfect accuracy verified: {target_count} rows, {len(source_col_names)} columns")
            return True
            
        except Exception as e:
            logger.error(f"Perfect accuracy verification failed: {str(e)}")
            raise
        finally:
            source_connector.close()
            target_connector.close()
    
    def test_perfect_migration_full_sync_with_where_clause(self):
        """Test perfect migration with full sync and WHERE clause - verify 100% accuracy"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_where_perfect'
        target_table = 'test_target_where_perfect'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
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
                name='Test Perfect WHERE Transformation',
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
            
            # Verify perfect accuracy
            # Expected: 3 rows (Jane age=30, Bob age=35, NULL name age=40)
            self._verify_perfect_accuracy(
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
    
    def test_perfect_migration_full_sync_with_column_transformations(self):
        """Test perfect migration with full sync and column transformations - verify 100% accuracy"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_cols_perfect'
        target_table = 'test_target_cols_perfect'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Cols Perfect',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Cols Perfect',
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
                name='Test Perfect Column Transformation',
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
            
            # Verify perfect accuracy with transformations
            # Expected: All 5 rows (no WHERE clause)
            self._verify_perfect_accuracy(
                source_connector, target_connector,
                schema, schema,
                target_table,
                expected_row_count=5,
                column_transformations={'name': 'TRIM', 'email': 'LOWER', 'description': 'TRIM'}
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
    
    def test_perfect_migration_full_sync_with_combined_transformations(self):
        """Test perfect migration with full sync and combined transformations - verify 100% accuracy"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_combined_perfect'
        target_table = 'test_target_combined_perfect'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Combined Perfect',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Combined Perfect',
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
                name='Test Perfect Combined Transformation',
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
            
            # Verify perfect accuracy
            # Expected: 1 row (Jane age=30, active)
            self._verify_perfect_accuracy(
                source_connector, target_connector,
                schema, schema,
                target_table,
                expected_row_count=1,
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
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
    
    def test_zero_data_loss_with_where_clause(self):
        """Test zero data loss with WHERE clause filtering"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_zero_loss'
        target_table = 'test_target_zero_loss'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections and job
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Zero Loss',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Zero Loss',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Zero Data Loss',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30",
                column_transformations=None
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify zero data loss - all rows matching WHERE clause are migrated
            source_connector.connect()
            target_connector.connect()
            
            # Count rows matching WHERE clause in source
            source_matching_rows = source_connector.fetch_batch(
                f"SELECT COUNT(*) FROM {schema}.{source_table} WHERE age >= 30",
                batch_size=1,
                offset=0
            )
            source_count = source_matching_rows[0][0] if source_matching_rows else 0
            
            # Count rows in target
            target_count = target_connector.get_row_count(schema, target_table)
            
            # Verify zero data loss
            self.assertEqual(
                source_count, target_count,
                f"Data loss detected: source matching rows={source_count}, target rows={target_count}"
            )
            
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
    
    def test_perfect_accuracy_null_values(self):
        """Test perfect accuracy with NULL values"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_nulls_perfect'
        target_table = 'test_target_nulls_perfect'
        
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
                    age INTEGER,
                    description TEXT
                )
            '''
            source_connector.execute_query(create_sql)
            
            insert_sql = f'''
                INSERT INTO {schema}.{source_table} (name, email, age, description)
                VALUES
                    ('John Doe', 'john@example.com', 25, 'Test'),
                    (NULL, 'nullname@example.com', 30, NULL),
                    ('Jane Smith', NULL, 35, 'Another'),
                    (NULL, NULL, 40, NULL)
            '''
            source_connector.execute_query(insert_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Nulls Perfect',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Nulls Perfect',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Perfect NULL Values',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query=None,
                column_transformations=None
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify perfect accuracy with NULL values
            self._verify_perfect_accuracy(
                source_connector, target_connector,
                schema, schema,
                target_table,
                expected_row_count=4
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
