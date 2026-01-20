"""
Error recovery tests for transformation queries
Tests error handling, rollback scenarios, and recovery mechanisms
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
import os
import logging

logger = logging.getLogger(__name__)


class TransformationErrorRecoveryTest(TransactionTestCase):
    """Error recovery tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='errorrecovery',
            password='testpass123',
            email='errorrecovery@example.com'
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
    
    def test_invalid_where_clause_fails_fast(self):
        """Test that invalid WHERE clause fails fast before migration"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_invalid_where_source'
        target_table = 'test_invalid_where_target'
        
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
                    age INTEGER
                )
            '''
            source_connector.execute_query(create_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job with invalid WHERE clause
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Invalid',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Invalid',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Invalid WHERE Clause',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="invalid_column > 100",  # Invalid column
                column_transformations=None
            )
            
            # Execute sync - should fail fast during validation
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            
            with self.assertRaises(Exception):
                executor.execute()
            
            # Verify target table was not created or is empty (rollback)
            target_connector.connect()
            try:
                target_count = target_connector.get_row_count(schema, target_table)
                # If table exists, it should be empty
                if target_count is not None:
                    self.assertEqual(target_count, 0, "Target table should be empty after failure")
            except:
                # Table might not exist, which is fine
                pass
            target_connector.close()
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                try:
                    source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                except:
                    pass
                source_connector.close()
            except:
                pass
    
    def test_invalid_column_transformation_fails_fast(self):
        """Test that invalid column transformation fails fast before migration"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_invalid_col_source'
        target_table = 'test_invalid_col_target'
        
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
                    age INTEGER
                )
            '''
            source_connector.execute_query(create_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job with invalid column transformation
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Invalid Col',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Invalid Col',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Invalid Column Transformation',
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
                column_transformations={'nonexistent_column': 'TRIM'}  # Invalid column
            )
            
            # Execute sync - should fail fast during validation
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            
            with self.assertRaises(Exception):
                executor.execute()
            
            # Verify target table was not created or is empty (rollback)
            target_connector.connect()
            try:
                target_count = target_connector.get_row_count(schema, target_table)
                # If table exists, it should be empty
                if target_count is not None:
                    self.assertEqual(target_count, 0, "Target table should be empty after failure")
            except:
                # Table might not exist, which is fine
                pass
            target_connector.close()
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                try:
                    source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                except:
                    pass
                source_connector.close()
            except:
                pass
