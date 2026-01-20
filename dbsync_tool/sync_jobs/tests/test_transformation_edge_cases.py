"""
Edge case tests for transformation queries
Tests empty results, NULL values, special characters, data types, large datasets, complex WHERE clauses
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
import os
import logging

logger = logging.getLogger(__name__)


class TransformationEdgeCasesTest(TransactionTestCase):
    """Edge case tests for transformation queries"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='edgecases',
            password='testpass123',
            email='edgecases@example.com'
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
    
    def test_transformation_empty_query_results(self):
        """Handle empty query results (0 rows)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_empty_source'
        target_table = 'test_empty_target'
        
        # Create empty table
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
                    email VARCHAR(255)
                )
            '''
            source_connector.execute_query(create_sql)
            # Don't insert any rows - empty table
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Empty',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Empty',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Empty Results',
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
                column_transformations={'name': 'TRIM', 'email': 'UPPER'}
            )
            
            # Execute sync - should handle empty results gracefully
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify target table is empty
            target_connector.connect()
            target_count = target_connector.get_row_count(schema, target_table)
            target_connector.close()
            
            self.assertEqual(target_count, 0, "Target table should be empty")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_transformation_empty_where_clause_results(self):
        """Handle WHERE clause that filters all rows"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_empty_where_source'
        target_table = 'test_empty_where_target'
        
        # Create table with data
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
            
            insert_sql = f'''
                INSERT INTO {schema}.{source_table} (name, age)
                VALUES
                    ('John', 25),
                    ('Jane', 30),
                    ('Bob', 35)
            '''
            source_connector.execute_query(insert_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job with WHERE clause that filters all rows
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Empty Where',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Empty Where',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Empty Where Clause',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age > 100",  # Filters all rows
                column_transformations=None
            )
            
            # Execute sync - should handle empty result set gracefully
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify target table is empty
            target_connector.connect()
            target_count = target_connector.get_row_count(schema, target_table)
            target_connector.close()
            
            self.assertEqual(target_count, 0, "Target table should be empty (all rows filtered)")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_transformation_null_values_all_columns(self):
        """Handle NULL values in all columns"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_nulls_all_source'
        target_table = 'test_nulls_all_target'
        
        # Create table with all NULL values
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
            
            # Insert row with all NULL values (except id)
            insert_sql = f'''
                INSERT INTO {schema}.{source_table} (name, email, age, description)
                VALUES (NULL, NULL, NULL, NULL)
            '''
            source_connector.execute_query(insert_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Nulls All',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Nulls All',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test NULL Values All Columns',
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
                column_transformations={'name': 'TRIM', 'email': 'UPPER', 'description': 'TRIM'}
            )
            
            # Execute sync - should handle NULL values gracefully
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify NULL values are preserved
            target_connector.connect()
            target_rows = target_connector.fetch_batch(
                f'SELECT * FROM {schema}.{target_table} ORDER BY id',
                batch_size=10,
                offset=0
            )
            target_connector.close()
            
            self.assertEqual(len(target_rows), 1, "Should have 1 row")
            row = target_rows[0]
            # id should not be NULL, but other columns should be NULL
            self.assertIsNotNone(row[0], "ID should not be NULL")
            self.assertIsNone(row[1], "Name should be NULL")
            self.assertIsNone(row[2], "Email should be NULL")
            self.assertIsNone(row[3], "Age should be NULL")
            self.assertIsNone(row[4], "Description should be NULL")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_transformation_special_characters(self):
        """Handle special characters (quotes, backslashes, etc.)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_special_source'
        target_table = 'test_special_target'
        
        # Create table with special characters
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
                    description TEXT
                )
            '''
            source_connector.execute_query(create_sql)
            
            # Insert data with special characters
            # Note: Using parameterized queries would be better, but for test we'll escape
            insert_sql = f'''
                INSERT INTO {schema}.{source_table} (name, description)
                VALUES
                    ('John''s Name', 'Description with "quotes"'),
                    ('Name\\Backslash', 'Description with \\backslash'),
                    ('Name/Tab', 'Description with\ttab'),
                    ('Name\\nNewline', 'Description with\nnewline')
            '''
            source_connector.execute_query(insert_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Special',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Special',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Special Characters',
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
                column_transformations={'name': 'TRIM', 'description': 'TRIM'}
            )
            
            # Execute sync - should handle special characters correctly
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify special characters are preserved
            target_connector.connect()
            target_rows = target_connector.fetch_batch(
                f'SELECT * FROM {schema}.{target_table} ORDER BY id',
                batch_size=10,
                offset=0
            )
            target_connector.close()
            
            self.assertEqual(len(target_rows), 4, "Should have 4 rows")
            # Verify first row has special characters
            first_row = target_rows[0]
            self.assertIn("'", first_row[1] or "", "Should preserve single quote")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_transformation_complex_where_clause_and(self):
        """Handle complex WHERE clause with AND"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_complex_and_source'
        target_table = 'test_complex_and_target'
        
        # Create table with data
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
                    age INTEGER,
                    salary DECIMAL(10,2),
                    is_active BOOLEAN
                )
            '''
            source_connector.execute_query(create_sql)
            
            insert_sql = f'''
                INSERT INTO {schema}.{source_table} (name, age, salary, is_active)
                VALUES
                    ('John', 25, 50000.00, true),
                    ('Jane', 30, 60000.00, true),
                    ('Bob', 35, 70000.00, false),
                    ('Alice', 28, 55000.00, true)
            '''
            source_connector.execute_query(insert_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job with complex WHERE clause
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Complex AND',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Complex AND',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Complex WHERE AND',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30 AND salary > 55000.00 AND is_active = true",
                column_transformations=None
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify correct rows migrated (Jane: age=30, salary=60000, active=true)
            target_connector.connect()
            target_count = target_connector.get_row_count(schema, target_table)
            target_connector.close()
            
            self.assertEqual(target_count, 1, "Should have 1 row matching complex WHERE clause")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
    
    def test_transformation_multiple_column_transformations(self):
        """Handle multiple column transformations on same table"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_multiple_transforms_source'
        target_table = 'test_multiple_transforms_target'
        
        # Create table with data
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
                    ('  John Doe  ', 'JOHN@EXAMPLE.COM', '  Description  '),
                    ('  Jane Smith  ', 'jane@example.com', '  Another  ')
            '''
            source_connector.execute_query(insert_sql)
            
        except Exception as e:
            self.skipTest(f"Failed to create source table: {str(e)}")
        finally:
            source_connector.close()
        
        try:
            # Create connections and job with multiple column transformations
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Multiple',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Multiple',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            job = SyncJob.objects.create(
                name='Test Multiple Column Transformations',
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
            
            # Verify transformations applied correctly
            target_connector.connect()
            target_rows = target_connector.fetch_batch(
                f'SELECT name, email, description FROM {schema}.{target_table} ORDER BY id',
                batch_size=10,
                offset=0
            )
            target_connector.close()
            
            self.assertEqual(len(target_rows), 2, "Should have 2 rows")
            # Check first row
            name, email, desc = target_rows[0]
            self.assertEqual(name, 'John Doe', "Name should be trimmed")
            self.assertEqual(email, 'john@example.com', "Email should be lowercase")
            self.assertEqual(desc, 'Description', "Description should be trimmed")
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{target_table}')
                source_connector.close()
            except:
                pass
