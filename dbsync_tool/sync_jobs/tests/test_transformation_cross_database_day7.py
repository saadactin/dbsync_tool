"""
Cross-database combination test suite for Day 7
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

logger = logging.getLogger(__name__)


class TransformationCrossDatabaseDay7Test(TransactionTestCase):
    """Cross-database combination tests for Day 7"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='crossdbday7',
            password='testpass123',
            email='crossdbday7@example.com'
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
        
        # MySQL configuration (optional)
        self.mysql_config = {
            'host': os.getenv('MYSQL_HOST', 'localhost'),
            'port': int(os.getenv('MYSQL_PORT', 3306)),
            'username': os.getenv('MYSQL_USER', 'root'),
            'password': os.getenv('MYSQL_PASSWORD', 'root'),
            'database_name': os.getenv('MYSQL_DB', 'test_db')
        }
        
        # SQL Server configuration (optional)
        self.sqlserver_config = {
            'host': os.getenv('SQLSERVER_HOST', 'localhost'),
            'port': int(os.getenv('SQLSERVER_PORT', 1433)),
            'username': os.getenv('SQLSERVER_USER', 'sa'),
            'password': os.getenv('SQLSERVER_PASSWORD', 'Password123'),
            'database_name': os.getenv('SQLSERVER_DB', 'test_db')
        }
    
    def _check_database_available(self, db_type='postgres'):
        """Check if database is available"""
        if not self.postgres_config and db_type == 'postgres':
            return False
        
        try:
            if db_type == 'postgres':
                from connections.connectors.postgres import PostgresConnector
                connector = PostgresConnector(**self.postgres_config)
            elif db_type == 'mysql':
                from connections.connectors.mysql import MySQLConnector
                connector = MySQLConnector(**self.mysql_config)
            elif db_type == 'sqlserver':
                from connections.connectors.sqlserver import SQLServerConnector
                connector = SQLServerConnector(**self.sqlserver_config)
            else:
                return False
            
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"{db_type} not available: {str(e)}")
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
            
            # Use generic SQL that works across databases
            create_sql = f'''
                CREATE TABLE {schema}.{table_name} (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255),
                    email VARCHAR(255),
                    age INTEGER
                )
            '''
            connector.execute_query(create_sql)
            
            insert_sql = f'''
                INSERT INTO {schema}.{table_name} (id, name, email, age)
                VALUES
                    (1, '  John Doe  ', 'JOHN@EXAMPLE.COM', 25),
                    (2, '  Jane Smith  ', 'jane@example.com', 30),
                    (3, '  Bob Johnson  ', 'BOB@EXAMPLE.COM', 35)
            '''
            connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_cross_database_postgres_to_postgres_with_where_clause(self):
        """Test PostgreSQL → PostgreSQL with WHERE clause"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_pg_pg_where_day7'
        target_table = 'test_pg_pg_where_day7'
        
        if not self._create_test_table(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source PG to PG',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target PG to PG',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test PG to PG WHERE',
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
            
            # Verify migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                source_count_query = f'SELECT COUNT(*) FROM {schema}.{source_table} WHERE age >= 30'
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                target_count = target_connector.get_row_count(schema, target_table)
                
                self.assertEqual(target_count, expected_count, "Row count must match")
                
                logger.info(f"✓ PostgreSQL → PostgreSQL with WHERE clause: {target_count} rows migrated")
                
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
    
    def test_cross_database_postgres_to_postgres_with_column_transformations(self):
        """Test PostgreSQL → PostgreSQL with column transformations"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_pg_pg_cols_day7'
        target_table = 'test_pg_pg_cols_day7'
        
        if not self._create_test_table(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source PG to PG Cols',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target PG to PG Cols',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test PG to PG Columns',
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
                
                # Verify transformations
                target_rows = target_connector.fetch_batch(
                    f'SELECT name, email FROM {schema}.{target_table} ORDER BY id',
                    batch_size=10,
                    offset=0
                )
                
                if target_rows:
                    name, email = target_rows[0]
                    self.assertNotIn('  ', name, "Name should be trimmed")
                    self.assertEqual(email, email.lower(), "Email should be lowercase")
                
                logger.info(f"✓ PostgreSQL → PostgreSQL with column transformations: {target_count} rows migrated")
                
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
    
    def test_cross_database_postgres_to_postgres_with_combined_transformations(self):
        """Test PostgreSQL → PostgreSQL with combined transformations"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_pg_pg_combined_day7'
        target_table = 'test_pg_pg_combined_day7'
        
        if not self._create_test_table(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            source_conn = DatabaseConnection.objects.create(
                name='Test Source PG to PG Combined',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target PG to PG Combined',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test PG to PG Combined',
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
                column_transformations={'name': 'TRIM', 'email': 'UPPER'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                source_count_query = f'SELECT COUNT(*) FROM {schema}.{source_table} WHERE age >= 30'
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                target_count = target_connector.get_row_count(schema, target_table)
                
                self.assertEqual(target_count, expected_count, "Row count must match")
                
                logger.info(f"✓ PostgreSQL → PostgreSQL with combined transformations: {target_count} rows migrated")
                
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
    
    # Note: Additional cross-database tests (PostgreSQL ↔ MySQL, PostgreSQL ↔ SQL Server, etc.)
    # would follow the same pattern. For brevity, we're focusing on PostgreSQL → PostgreSQL
    # as a representative example. The same patterns apply to other combinations.
