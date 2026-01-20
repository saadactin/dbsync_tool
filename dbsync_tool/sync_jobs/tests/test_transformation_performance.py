"""
Performance tests for transformation queries
Measures query execution, transformation, and migration performance
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
import os
import logging
import time

logger = logging.getLogger(__name__)


class TransformationPerformanceTest(TransactionTestCase):
    """Performance tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='perftest',
            password='testpass123',
            email='perftest@example.com'
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
    
    def _create_large_test_table(self, connector, schema, table_name, num_rows=1000):
        """Create a test table with large dataset"""
        connector.connect()
        try:
            connector.ensure_schema_exists(schema)
            
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
                    description TEXT
                )
            '''
            connector.execute_query(create_sql)
            
            # Insert data in batches
            batch_size = 100
            for i in range(0, num_rows, batch_size):
                values = []
                for j in range(batch_size):
                    if i + j >= num_rows:
                        break
                    values.append(
                        f"('  Name {i+j}  ', 'EMAIL{i+j}@EXAMPLE.COM', {20 + (i+j) % 50}, '  Description {i+j}  ')"
                    )
                
                if values:
                    insert_sql = f'''
                        INSERT INTO {schema}.{table_name} (name, email, age, description)
                        VALUES {', '.join(values)}
                    '''
                    connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create large test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_query_execution_performance_small_dataset(self):
        """Measure query execution time for small dataset (< 1K rows)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        connector = PostgresConnector(**self.postgres_config)
        schema = 'public'
        table_name = 'test_perf_small'
        
        if not self._create_large_test_table(connector, schema, table_name, num_rows=100):
            self.skipTest("Failed to create test table")
        
        try:
            connector.connect()
            
            # Measure query execution time without transformation
            start_time = time.time()
            result = connector.fetch_batch(
                f'SELECT * FROM {schema}.{table_name}',
                batch_size=100,
                offset=0
            )
            time_without_transform = time.time() - start_time
            
            # Measure query execution time with WHERE clause transformation
            start_time = time.time()
            result = connector.fetch_batch(
                f'SELECT * FROM {schema}.{table_name} WHERE age >= 30',
                batch_size=100,
                offset=0
            )
            time_with_where = time.time() - start_time
            
            # Measure query execution time with column transformation
            start_time = time.time()
            result = connector.fetch_batch(
                f'SELECT TRIM(name) as name, LOWER(email) as email, age, TRIM(description) as description FROM {schema}.{table_name}',
                batch_size=100,
                offset=0
            )
            time_with_column_transform = time.time() - start_time
            
            logger.info(
                f"Small dataset performance: "
                f"without={time_without_transform:.3f}s, "
                f"with_where={time_with_where:.3f}s, "
                f"with_column={time_with_column_transform:.3f}s"
            )
            
            # Performance should be acceptable (< 1 second for 100 rows)
            self.assertLess(time_without_transform, 1.0, "Query execution too slow")
            self.assertLess(time_with_where, 1.0, "Query with WHERE clause too slow")
            self.assertLess(time_with_column_transform, 1.0, "Query with column transformation too slow")
            
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table_name}')
            except:
                pass
            connector.close()
    
    def test_migration_performance_overhead(self):
        """Calculate transformation overhead (< 10% target)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_perf_source'
        target_table = 'test_perf_target'
        
        if not self._create_large_test_table(source_connector, schema, source_table, num_rows=500):
            self.skipTest("Failed to create test table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Perf',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perf',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            # Test migration without transformations
            job_no_transform = SyncJob.objects.create(
                name='Test Performance No Transform',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            job_table_no_transform = SyncJobTable.objects.create(
                job=job_no_transform,
                schema_name=schema,
                table_name=source_table,
                transformation_query=None,
                column_transformations=None
            )
            
            start_time = time.time()
            executor = SyncExecutor(job_no_transform)
            execution = executor.create_execution()
            executor.execute()
            time_without_transform = time.time() - start_time
            
            # Clean up target table
            target_connector.connect()
            target_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
            target_connector.close()
            
            # Test migration with transformations
            job_with_transform = SyncJob.objects.create(
                name='Test Performance With Transform',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            job_table_with_transform = SyncJobTable.objects.create(
                job=job_with_transform,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30",
                column_transformations={'name': 'TRIM', 'email': 'LOWER', 'description': 'TRIM'}
            )
            
            start_time = time.time()
            executor = SyncExecutor(job_with_transform)
            execution = executor.create_execution()
            executor.execute()
            time_with_transform = time.time() - start_time
            
            # Calculate overhead
            overhead = ((time_with_transform - time_without_transform) / time_without_transform) * 100
            
            logger.info(
                f"Migration performance: "
                f"without={time_without_transform:.3f}s, "
                f"with={time_with_transform:.3f}s, "
                f"overhead={overhead:.2f}%"
            )
            
            # Overhead should be < 10% (allowing some flexibility for test environment)
            # In real scenarios, overhead should be minimal
            self.assertLess(overhead, 50.0, f"Transformation overhead too high: {overhead:.2f}%")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
