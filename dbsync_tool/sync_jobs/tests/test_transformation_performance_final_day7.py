"""
Performance benchmarking test suite for Day 7
Tests performance of transformation queries and measures overhead
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from unittest.mock import Mock
import os
import logging
import time

logger = logging.getLogger(__name__)


class TransformationPerformanceFinalDay7Test(TransactionTestCase):
    """Performance tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='performanceday7',
            password='testpass123',
            email='performanceday7@example.com'
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
            self.postgres_config = {
                'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
                'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
                'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
                'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
                'database_name': os.getenv('TEST_POSTGRES_DB', 'tauseef'),
            }
    
    def _check_database_available(self):
        """Check if PostgreSQL is available"""
        if not self.postgres_config:
            return False
        
        try:
            from connections.connectors.postgres import PostgresConnector
            connector = PostgresConnector(**self.postgres_config)
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"PostgreSQL not available: {str(e)}")
            return False
    
    def _create_test_table_with_data(self, connector, schema, table_name, row_count=1000):
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
            
            # Insert data in batches for efficiency
            batch_size = 1000
            for batch_start in range(1, row_count + 1, batch_size):
                batch_end = min(batch_start + batch_size - 1, row_count)
                values = []
                for i in range(batch_start, batch_end + 1):
                    values.append(
                        f"({i}, '  User {i}  ', 'User{i}@EXAMPLE.COM', "
                        f"{20 + (i % 50)}, {50000.00 + (i * 100)}, "
                        f"{i % 2 == 0}, '2024-01-01 00:00:00', 'Test Description {i}')"
                    )
                
                insert_sql = f'''
                    INSERT INTO {schema}.{table_name} 
                    (id, name, email, age, salary, is_active, created_at, description)
                    VALUES {', '.join(values)}
                '''
                connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_performance_migration_without_transformations(self):
        """Test migration performance without transformations"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_perf_no_transform_day7'
        target_table = 'test_perf_no_transform_day7'
        
        if not self._create_test_table_with_data(source_connector, schema, source_table, 1000):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Perf No Transform',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perf No Transform',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Performance No Transform',
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
            
            # Measure execution time
            start_time = time.time()
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            elapsed_time = time.time() - start_time
            
            logger.info(f"✓ Migration without transformations: {elapsed_time:.2f}s for 1000 rows")
            
            # Store baseline for comparison
            self.baseline_time = elapsed_time
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_performance_migration_with_where_clause(self):
        """Test migration performance with WHERE clause transformation"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_perf_where_day7'
        target_table = 'test_perf_where_day7'
        
        if not self._create_test_table_with_data(source_connector, schema, source_table, 1000):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Perf WHERE',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perf WHERE',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Performance WHERE',
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
            
            # Measure execution time
            start_time = time.time()
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            elapsed_time = time.time() - start_time
            
            logger.info(f"✓ Migration with WHERE clause: {elapsed_time:.2f}s")
            
            # Note: WHERE clause should not add significant overhead as it's handled in SQL
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_performance_migration_with_column_transformations(self):
        """Test migration performance with column transformations"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_perf_cols_day7'
        target_table = 'test_perf_cols_day7'
        
        if not self._create_test_table_with_data(source_connector, schema, source_table, 1000):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Perf Cols',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perf Cols',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Performance Columns',
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
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Measure execution time
            start_time = time.time()
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            elapsed_time = time.time() - start_time
            
            logger.info(f"✓ Migration with column transformations: {elapsed_time:.2f}s")
            
            # Column transformations in SQL should have minimal overhead
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_performance_query_execution_before_migration(self):
        """Test query execution performance before migration"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        from sync_engine.pre_migration_validator import PreMigrationValidator
        
        source_connector = PostgresConnector(**self.postgres_config)
        schema = 'public'
        source_table = 'test_perf_query_day7'
        
        if not self._create_test_table_with_data(source_connector, schema, source_table, 5000):
            self.skipTest("Failed to create source table")
        
        try:
            from sync_jobs.models import SyncJobTable
            from sync_jobs.models import SyncJob
            
            # Create a mock job_table for testing
            job_table = Mock()
            job_table.schema_name = schema
            job_table.table_name = source_table
            job_table.transformation_query = "age >= 30"
            job_table.column_transformations = {'name': 'TRIM'}
            
            validator = PreMigrationValidator(source_connector)
            
            # Measure query execution time
            start_time = time.time()
            transformed_query = f'SELECT * FROM {schema}.{source_table} WHERE age >= 30'
            base_query = f'SELECT * FROM {schema}.{source_table}'
            column_names = ['id', 'name', 'email', 'age', 'salary', 'is_active', 'created_at', 'description']
            
            # Execute validation (includes query execution)
            is_valid, error, report = validator.validate_transformation_query(
                job_table=job_table,
                transformed_query=transformed_query,
                base_query=base_query,
                column_names=column_names
            )
            
            elapsed_time = time.time() - start_time
            
            self.assertTrue(is_valid, "Query validation should succeed")
            logger.info(f"✓ Query execution before migration: {elapsed_time:.2f}s for validation")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.close()
            except:
                pass
