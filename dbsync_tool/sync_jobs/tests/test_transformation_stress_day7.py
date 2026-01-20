"""
Stress testing suite for Day 7
Tests transformation queries with large datasets and complex scenarios
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

logger = logging.getLogger(__name__)


class TransformationStressDay7Test(TransactionTestCase):
    """Stress tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='stressday7',
            password='testpass123',
            email='stressday7@example.com'
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
    
    def _create_large_test_table(self, connector, schema, table_name, row_count):
        """Create test table with large amount of data"""
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
            logger.error(f"Failed to create large test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_stress_large_dataset_10k_rows(self):
        """Test with 10K rows"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_stress_10k_day7'
        target_table = 'test_stress_10k_day7'
        row_count = 10000
        
        logger.info(f"Creating test table with {row_count} rows...")
        if not self._create_large_test_table(source_connector, schema, source_table, row_count):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Stress 10K',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Stress 10K',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Stress 10K Rows',
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
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Execute sync and measure time
            start_time = time.time()
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            elapsed_time = time.time() - start_time
            
            # Verify migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                source_count_query = f'SELECT COUNT(*) FROM {schema}.{source_table} WHERE age >= 30'
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                target_count = target_connector.get_row_count(schema, target_table)
                
                self.assertEqual(target_count, expected_count, "Row count must match")
                
                logger.info(f"✓ Stress test 10K rows: {target_count} rows migrated in {elapsed_time:.2f}s")
                
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
    
    def test_stress_large_dataset_50k_rows(self):
        """Test with 50K rows (if feasible)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_stress_50k_day7'
        target_table = 'test_stress_50k_day7'
        row_count = 50000
        
        logger.info(f"Creating test table with {row_count} rows...")
        if not self._create_large_test_table(source_connector, schema, source_table, row_count):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Stress 50K',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Stress 50K',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Stress 50K Rows',
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
                column_transformations={'name': 'TRIM'}
            )
            
            # Execute sync and measure time
            start_time = time.time()
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            elapsed_time = time.time() - start_time
            
            # Verify migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                source_count_query = f'SELECT COUNT(*) FROM {schema}.{source_table} WHERE age >= 30'
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                target_count = target_connector.get_row_count(schema, target_table)
                
                self.assertEqual(target_count, expected_count, "Row count must match")
                
                logger.info(f"✓ Stress test 50K rows: {target_count} rows migrated in {elapsed_time:.2f}s")
                
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
    
    def test_stress_complex_where_clause_multiple_conditions(self):
        """Test complex WHERE clause with multiple conditions"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_stress_complex_day7'
        target_table = 'test_stress_complex_day7'
        
        if not self._create_large_test_table(source_connector, schema, source_table, 5000):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Complex',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Complex',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Stress Complex WHERE',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Complex WHERE clause with multiple conditions
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30 AND age <= 50 AND salary >= 50000 AND is_active = true",
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                source_count_query = f'''SELECT COUNT(*) FROM {schema}.{source_table} 
                    WHERE age >= 30 AND age <= 50 AND salary >= 50000 AND is_active = true'''
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                target_count = target_connector.get_row_count(schema, target_table)
                
                self.assertEqual(target_count, expected_count, "Row count must match")
                
                logger.info(f"✓ Complex WHERE clause stress test: {target_count} rows migrated")
                
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
    
    def test_stress_multiple_column_transformations(self):
        """Test multiple column transformations on same table"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_stress_multicol_day7'
        target_table = 'test_stress_multicol_day7'
        
        if not self._create_large_test_table(source_connector, schema, source_table, 3000):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Multi Col',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Multi Col',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Stress Multiple Columns',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Multiple column transformations
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query=None,
                column_transformations={
                    'name': 'TRIM',
                    'email': 'LOWER',
                    'description': 'TRIM'
                }
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                source_count = source_connector.get_row_count(schema, source_table)
                target_count = target_connector.get_row_count(schema, target_table)
                
                self.assertEqual(target_count, source_count, "Row count must match")
                
                logger.info(f"✓ Multiple column transformations stress test: {target_count} rows migrated")
                
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
