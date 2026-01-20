"""
Concurrent execution tests for transformation queries
Tests multiple sync jobs running concurrently with transformations
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
import os
import logging
import threading
import time

logger = logging.getLogger(__name__)


class TransformationConcurrentTest(TransactionTestCase):
    """Concurrent execution tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='concurrent',
            password='testpass123',
            email='concurrent@example.com'
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
    
    def test_concurrent_sync_jobs_with_transformations(self):
        """Test multiple sync jobs running concurrently with transformations"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        schema = 'public'
        num_jobs = 3
        results = []
        errors = []
        
        def run_sync_job(job_id):
            """Run a sync job in a separate thread"""
            try:
                source_connector = PostgresConnector(**self.postgres_config)
                source_table = f'test_concurrent_source_{job_id}'
                target_table = f'test_concurrent_target_{job_id}'
                
                # Create table
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
                            age INTEGER
                        )
                    '''
                    source_connector.execute_query(create_sql)
                    
                    insert_sql = f'''
                        INSERT INTO {schema}.{source_table} (name, email, age)
                        VALUES
                            ('  Job{job_id}Name1  ', 'JOB{job_id}@EXAMPLE.COM', 25),
                            ('  Job{job_id}Name2  ', 'job{job_id}@example.com', 30)
                    '''
                    source_connector.execute_query(insert_sql)
                    
                except Exception as e:
                    errors.append(f"Job {job_id}: Failed to create table: {str(e)}")
                    return
                finally:
                    source_connector.close()
                
                # Create connections and job
                source_conn = DatabaseConnection.objects.create(
                    name=f'Test Source Concurrent {job_id}',
                    db_type='postgres',
                    host=self.postgres_config['host'],
                    port=self.postgres_config['port'],
                    username=self.postgres_config['username'],
                    password=self.postgres_config['password'],
                    database_name=self.postgres_config['database_name'],
                    created_by=self.user
                )
                
                target_conn = DatabaseConnection.objects.create(
                    name=f'Test Target Concurrent {job_id}',
                    db_type='postgres',
                    host=self.postgres_config['host'],
                    port=self.postgres_config['port'],
                    username=self.postgres_config['username'],
                    password=self.postgres_config['password'],
                    database_name=self.postgres_config['database_name'],
                    created_by=self.user
                )
                
                job = SyncJob.objects.create(
                    name=f'Test Concurrent Job {job_id}',
                    source_connection=source_conn,
                    target_connection=target_conn,
                    sync_type='full',
                    created_by=self.user
                )
                
                job_table = SyncJobTable.objects.create(
                    job=job,
                    schema_name=schema,
                    table_name=source_table,
                    transformation_query="age >= 25",
                    column_transformations={'name': 'TRIM', 'email': 'LOWER'}
                )
                
                # Execute sync
                executor = SyncExecutor(job)
                execution = executor.create_execution()
                executor.execute()
                
                results.append(f"Job {job_id}: Success")
                
            except Exception as e:
                errors.append(f"Job {job_id}: Error: {str(e)}")
        
        # Run jobs concurrently
        threads = []
        for i in range(num_jobs):
            thread = threading.Thread(target=run_sync_job, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=60)  # 60 second timeout
        
        # Verify all jobs completed successfully
        self.assertEqual(len(results), num_jobs, f"Expected {num_jobs} successful jobs, got {len(results)}")
        self.assertEqual(len(errors), 0, f"Expected no errors, got: {errors}")
        
        # Cleanup
        try:
            source_connector = PostgresConnector(**self.postgres_config)
            source_connector.connect()
            for i in range(num_jobs):
                try:
                    source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.test_concurrent_source_{i}')
                    source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.test_concurrent_target_{i}')
                except:
                    pass
            source_connector.close()
        except:
            pass
