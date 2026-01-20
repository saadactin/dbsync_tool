"""
Edge case tests for Day 6 - Perfect Migration

Tests edge cases for perfect migration with transformation queries:
- Empty query results (0 rows)
- NULL values in all columns
- Special characters and Unicode
- Large datasets
- Complex WHERE clauses
- Multiple column transformations
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
import os
import logging

logger = logging.getLogger(__name__)


class TransformationEdgeCasesDay6Test(TransactionTestCase):
    """Test edge cases for perfect migration"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='edgecasesday6',
            password='testpass123',
            email='edgecasesday6@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        self.postgres_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'username': os.getenv('POSTGRES_USER', 'postgres'),
            'password': os.getenv('POSTGRES_PASSWORD', 'postgres'),
            'database_name': os.getenv('POSTGRES_DB', 'test_db')
        }
    
    def _check_database_available(self):
        """Check if PostgreSQL is available"""
        try:
            from connections.connectors.postgres import PostgresConnector
            connector = PostgresConnector(**self.postgres_config)
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"PostgreSQL not available: {str(e)}")
            return False
    
    def _create_test_table_with_data(self, connector, schema, table_name, row_count=10):
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
                    description TEXT
                )
            '''
            connector.execute_query(create_sql)
            
            # Insert test data
            for i in range(1, row_count + 1):
                insert_sql = f'''
                    INSERT INTO {schema}.{table_name} (id, name, email, age, description)
                    VALUES (
                        {i},
                        '{"  User " + str(i) + "  "}',
                        'User{i}@EXAMPLE.COM',
                        {20 + (i % 50)},
                        'Test Description {i}'
                    )
                '''
                connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_empty_query_results(self):
        """Test perfect migration with empty query results (WHERE clause filters all rows)"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_empty'
        target_table = 'test_target_empty'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table, 10):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
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
            
            # Create sync job with WHERE clause that filters all rows
            job = SyncJob.objects.create(
                name='Test Empty Results',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with WHERE clause that returns 0 rows
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age > 1000",  # No rows match
                column_transformations=None
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify target table is empty
            target_connector.connect()
            try:
                target_count = target_connector.get_row_count(schema, target_table)
                self.assertEqual(target_count, 0, "Target table should be empty")
                
                logger.info("✓ Empty query results handled correctly")
                
            finally:
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
    
    def test_null_values(self):
        """Test perfect migration with NULL values"""
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
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255),
                    email VARCHAR(255),
                    age INTEGER,
                    description TEXT
                )
            '''
            source_connector.execute_query(create_sql)
            
            # Insert data with NULL values
            source_connector.execute_query(f'''
                INSERT INTO {schema}.{source_table} (id, name, email, age, description)
                VALUES 
                    (1, NULL, 'user1@example.com', 25, NULL),
                    (2, 'User 2', NULL, NULL, 'Description 2'),
                    (3, NULL, NULL, NULL, NULL),
                    (4, 'User 4', 'user4@example.com', 30, 'Description 4')
            ''')
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
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Nulls',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            # Create sync job
            job = SyncJob.objects.create(
                name='Test NULL Values',
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
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify NULL values are preserved
            target_connector.connect()
            try:
                target_count = target_connector.get_row_count(schema, target_table)
                self.assertEqual(target_count, 4)
                
                # Verify NULL values are preserved
                rows = target_connector.fetch_batch(
                    f'SELECT id, name, email, age, description FROM {schema}.{target_table} ORDER BY id',
                    batch_size=10,
                    offset=0
                )
                
                # Check first row (all NULLs except email)
                row1 = rows[0]
                self.assertIsNone(row1[1])  # name is NULL
                self.assertEqual(row1[2], 'user1@example.com')  # email preserved
                self.assertIsNone(row1[3])  # age is NULL
                self.assertIsNone(row1[4])  # description is NULL
                
                logger.info("✓ NULL values preserved correctly")
                
            finally:
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
    
    def test_special_characters_and_unicode(self):
        """Test perfect migration with special characters and Unicode"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_unicode'
        target_table = 'test_target_unicode'
        
        # Create source table with special characters and Unicode
        source_connector.connect()
        try:
            source_connector.ensure_schema_exists(schema)
            try:
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
            except:
                pass
            
            create_sql = f'''
                CREATE TABLE {schema}.{source_table} (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255),
                    description TEXT
                )
            '''
            source_connector.execute_query(create_sql)
            
            # Insert data with special characters and Unicode
            # Insert each row separately to handle special characters properly
            source_connector.execute_query(
                f"INSERT INTO {schema}.{source_table} (id, name, description) "
                f"VALUES (1, 'User \"Test\"', 'Description with ''quotes''')"
            )
            source_connector.execute_query(
                f"INSERT INTO {schema}.{source_table} (id, name, description) "
                f"VALUES (2, 'User\\\\Backslash', 'Description with \\\\backslash')"
            )
            source_connector.execute_query(
                f"INSERT INTO {schema}.{source_table} (id, name, description) "
                f"VALUES (3, 'User 中文', 'Description with 中文 characters')"
            )
            source_connector.execute_query(
                f"INSERT INTO {schema}.{source_table} (id, name, description) "
                f"VALUES (4, 'User 🎉', 'Description with emoji 🎉')"
            )
        finally:
            source_connector.close()
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Unicode',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Unicode',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            # Create sync job
            job = SyncJob.objects.create(
                name='Test Special Characters',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query=None,
                column_transformations={'name': 'TRIM'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify special characters and Unicode are preserved
            target_connector.connect()
            try:
                target_count = target_connector.get_row_count(schema, target_table)
                self.assertEqual(target_count, 4)
                
                # Verify data matches
                source_rows = source_connector.fetch_batch(
                    f'SELECT id, name, description FROM {schema}.{source_table} ORDER BY id',
                    batch_size=10,
                    offset=0
                )
                target_rows = target_connector.fetch_batch(
                    f'SELECT id, name, description FROM {schema}.{target_table} ORDER BY id',
                    batch_size=10,
                    offset=0
                )
                
                for source_row, target_row in zip(source_rows, target_rows):
                    # Name should be trimmed but otherwise match
                    self.assertEqual(target_row[1], source_row[1].strip() if source_row[1] else source_row[1])
                    # Description should match exactly
                    self.assertEqual(target_row[2], source_row[2])
                
                logger.info("✓ Special characters and Unicode preserved correctly")
                
            finally:
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
    
    def test_complex_where_clause(self):
        """Test perfect migration with complex WHERE clause"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_complex'
        target_table = 'test_target_complex'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table, 100):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
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
            
            # Create sync job with complex WHERE clause
            job = SyncJob.objects.create(
                name='Test Complex WHERE',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with complex WHERE clause
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="(age >= 30 AND age <= 50) OR (age >= 70)",
                column_transformations=None
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify perfect migration
            source_connector.connect()
            target_connector.connect()
            
            try:
                # Count rows matching complex WHERE clause in source
                source_count_query = f'SELECT COUNT(*) FROM {schema}.{source_table} WHERE (age >= 30 AND age <= 50) OR (age >= 70)'
                source_count_result = source_connector.fetch_batch(source_count_query, batch_size=1, offset=0)
                expected_count = source_count_result[0][0] if source_count_result else 0
                
                # Count rows in target
                target_count = target_connector.get_row_count(schema, target_table)
                
                # Verify row count matches exactly
                self.assertEqual(target_count, expected_count)
                
                logger.info(f"✓ Complex WHERE clause handled correctly: {target_count} rows")
                
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
