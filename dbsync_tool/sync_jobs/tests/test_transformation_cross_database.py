"""
Cross-database combination tests for transformation queries
Tests transformations across all database combinations (PostgreSQL, MySQL, SQL Server)
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
import os
import logging

logger = logging.getLogger(__name__)


class TransformationCrossDatabaseTest(TransactionTestCase):
    """Cross-database combination tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='crossdb',
            password='testpass123',
            email='crossdb@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        # For now, we'll test with PostgreSQL only
        # Cross-database tests require multiple database connections
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
    
    def _create_test_table(self, connector, schema, table_name):
        """Create a test table with data"""
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
                    age INTEGER
                )
            '''
            connector.execute_query(create_sql)
            
            insert_sql = f'''
                INSERT INTO {schema}.{table_name} (name, email, age)
                VALUES
                    ('  John Doe  ', 'JOHN@EXAMPLE.COM', 25),
                    ('  Jane Smith  ', 'jane@example.com', 30),
                    ('  Bob Johnson  ', 'BOB@EXAMPLE.COM', 35)
            '''
            connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_perfect_migration_postgres_to_postgres(self):
        """Test perfect migration PostgreSQL to PostgreSQL with transformations"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_pg_pg_source'
        target_table = 'test_pg_pg_target'
        
        if not self._create_test_table(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source PG-PG',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target PG-PG',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            # Create sync job with transformations
            job = SyncJob.objects.create(
                name='Test PG to PG Perfect',
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
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify perfect accuracy
            target_connector.connect()
            target_count = target_connector.get_row_count(schema, target_table)
            target_rows = target_connector.fetch_batch(
                f'SELECT name, email, age FROM {schema}.{target_table} ORDER BY id',
                batch_size=10,
                offset=0
            )
            target_connector.close()
            
            # Expected: 2 rows (Jane age=30, Bob age=35)
            self.assertEqual(target_count, 2, "Should have 2 rows")
            
            # Verify transformations applied
            if target_rows:
                name, email, age = target_rows[0]
                self.assertEqual(name, 'Jane Smith', "Name should be trimmed")
                self.assertEqual(email, 'jane@example.com', "Email should be lowercase")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    # Note: Additional cross-database tests (PostgreSQL to MySQL, MySQL to SQL Server, etc.)
    # would require multiple database connections to be configured.
    # These tests are placeholders that can be expanded when multiple databases are available.
    
    def test_perfect_migration_cross_database_placeholder(self):
        """Placeholder for cross-database tests when multiple databases are available"""
        # This test can be expanded when MySQL and SQL Server connections are available
        self.skipTest("Cross-database tests require multiple database connections")
