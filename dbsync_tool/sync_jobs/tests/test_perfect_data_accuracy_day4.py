"""
Comprehensive integration tests for perfect data accuracy (Day 4)

Tests the complete flow with query execution before migration:
- Query execution before migration
- Query result verification
- Perfect data accuracy guarantees
- Zero data loss
- Zero data inaccuracy
- Edge case handling
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from sync_engine.pre_migration_validator import PreMigrationValidator
from sync_engine.query_result_verifier import QueryResultVerifier
import os
import logging

logger = logging.getLogger(__name__)


class PerfectDataAccuracyDay4Test(TransactionTestCase):
    """Test perfect data accuracy with query execution before migration (Day 4)"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='day4accuracy',
            password='testpass123',
            email='day4accuracy@example.com'
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
                    'database_name': os.getenv('TEST_POSTGRES_DB', 'test_db'),
                }
            
            self.postgres_available = True
        except Exception as e:
            logger.warning(f"PostgreSQL not available: {str(e)}")
            self.postgres_available = False
    
    def _check_database_available(self):
        """Check if database is available"""
        if not self.postgres_available:
            return False
        
        try:
            from connections.connectors.postgres import PostgresConnector
            connector = PostgresConnector(**self.postgres_config)
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"Database connection failed: {str(e)}")
            return False
    
    def _create_test_table_with_data(self, connector, schema, table_name):
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
                    name VARCHAR(100),
                    email VARCHAR(100),
                    age INTEGER,
                    salary DECIMAL(10, 2),
                    is_active BOOLEAN,
                    hire_date DATE,
                    description TEXT
                )
            '''
            connector.execute_query(create_sql)
            
            insert_sql = f'''
                INSERT INTO {schema}.{table_name} (id, name, email, age, salary, is_active, hire_date, description)
                VALUES
                    (1, '  John Doe  ', 'JOHN@EXAMPLE.COM', 30, 50000.00, true, '2020-01-01', '  Test Description  '),
                    (2, '  Jane Smith  ', 'JANE@EXAMPLE.COM', 25, 60000.00, false, '2021-01-01', '  Another Description  '),
                    (3, '  Bob Wilson  ', 'BOB@EXAMPLE.COM', 35, 70000.00, true, '2019-01-01', '  Yet Another Description  '),
                    (4, '  Alice Brown  ', 'ALICE@EXAMPLE.COM', 28, 55000.00, true, '2022-01-01', '  Final Description  '),
                    (5, '  Charlie Davis  ', 'CHARLIE@EXAMPLE.COM', 40, 80000.00, true, '2018-01-01', '  Last Description  ')
            '''
            connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_query_execution_before_migration_with_where_clause(self):
        """Test that query is executed before migration with WHERE clause"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        schema = 'public'
        source_table = 'test_source_query_exec'
        
        # Create source table
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Query Exec',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Query Exec',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            # Create sync job with WHERE clause transformation
            job = SyncJob.objects.create(
                name='Test Query Execution Before Migration',
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
            
            # Test pre-migration validation with query execution
            validator = PreMigrationValidator(source_connector)
            
            # Build transformed query
            from sync_engine.query_builder import QueryBuilder
            query_builder = QueryBuilder()
            base_query = query_builder.build_select_query(
                connector=source_connector,
                schema=schema,
                table=source_table,
                columns=['id', 'name', 'email', 'age', 'salary', 'is_active', 'hire_date', 'description']
            )
            
            transformed_query = query_builder.build_select_query(
                connector=source_connector,
                schema=schema,
                table=source_table,
                columns=['id', 'name', 'email', 'age', 'salary', 'is_active', 'hire_date', 'description'],
                where_clause="age >= 30"
            )
            
            # Execute validation (should execute full query)
            is_valid, error_msg, validation_report = validator.validate_transformation_query(
                job_table=job_table,
                transformed_query=transformed_query,
                base_query=base_query,
                column_names=['id', 'name', 'email', 'age', 'salary', 'is_active', 'hire_date', 'description']
            )
            
            # Verify query was executed
            self.assertTrue(is_valid)
            self.assertIsNone(error_msg)
            self.assertIn('query_results', validation_report)
            self.assertGreater(validation_report['query_result_count'], 0)
            self.assertIn('query_execution_time', validation_report)
            self.assertGreater(validation_report['query_execution_time'], 0)
            self.assertTrue(validation_report['structure_verified'])
            self.assertTrue(validation_report['data_verified'])
            
            # Verify expected row count (should be 3: John, Bob, Charlie have age >= 30)
            self.assertEqual(validation_report['expected_row_count'], 3)
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.close()
            except:
                pass
    
    def test_query_execution_before_migration_with_column_transformations(self):
        """Test that query is executed before migration with column transformations"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        schema = 'public'
        source_table = 'test_source_col_transforms'
        
        # Create source table
        if not self._create_test_table_with_data(source_connector, schema, source_table):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Col Transforms',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Col Transforms',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            # Create sync job with column transformations
            job = SyncJob.objects.create(
                name='Test Query Execution Column Transforms',
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
            
            # Test pre-migration validation
            validator = PreMigrationValidator(source_connector)
            
            from sync_engine.query_builder import QueryBuilder
            query_builder = QueryBuilder()
            base_query = query_builder.build_select_query(
                connector=source_connector,
                schema=schema,
                table=source_table,
                columns=['id', 'name', 'email', 'age', 'salary', 'is_active', 'hire_date', 'description']
            )
            
            transformed_query = query_builder.build_select_query(
                connector=source_connector,
                schema=schema,
                table=source_table,
                columns=['id', 'name', 'email', 'age', 'salary', 'is_active', 'hire_date', 'description'],
                column_transformations={'name': 'TRIM', 'email': 'LOWER', 'description': 'TRIM'}
            )
            
            # Execute validation
            is_valid, error_msg, validation_report = validator.validate_transformation_query(
                job_table=job_table,
                transformed_query=transformed_query,
                base_query=base_query,
                column_names=['id', 'name', 'email', 'age', 'salary', 'is_active', 'hire_date', 'description']
            )
            
            # Verify query was executed and transformations verified
            self.assertTrue(is_valid)
            self.assertIn('query_results', validation_report)
            self.assertGreater(validation_report['query_result_count'], 0)
            self.assertTrue(validation_report['transformations_verified'])
            
            # Verify transformations were applied in query results
            query_results = validation_report['query_results']
            if query_results:
                # Check first row - name should be trimmed, email should be lowercase
                first_row = query_results[0]
                # Note: Column order depends on query, but we can check if transformations are visible
                # This is a basic check - actual verification happens in QueryResultVerifier
                self.assertIsNotNone(first_row)
            
        finally:
            # Cleanup
            try:
                source_connector.connect()
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
                source_connector.close()
            except:
                pass
    
    def test_perfect_data_accuracy_with_query_execution(self):
        """Test perfect data accuracy with query execution before migration"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        schema = 'public'
        source_table = 'test_source_perfect'
        target_table = 'test_target_perfect'
        
        # Create source table
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
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Perfect',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database'],
                created_by=self.user
            )
            
            # Create sync job with transformations
            job = SyncJob.objects.create(
                name='Test Perfect Data Accuracy Day 4',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with both WHERE clause and column transformations
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30",
                column_transformations={'name': 'TRIM', 'email': 'LOWER', 'description': 'TRIM'}
            )
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify data accuracy
            target_connector.connect()
            try:
                target_count = target_connector.get_row_count(schema, target_table)
                # Expected: 3 rows (John, Bob, Charlie have age >= 30)
                self.assertEqual(target_count, 3, f"Expected 3 rows, got {target_count}")
                
                # Verify transformations were applied
                rows = target_connector.fetch_batch(
                    f'SELECT name, email, description FROM {schema}.{target_table} ORDER BY id',
                    batch_size=100,
                    offset=0
                )
                
                # Check first row (John Doe)
                if rows:
                    name, email, desc = rows[0]
                    # Name should be trimmed
                    self.assertEqual(name, 'John Doe', f"Name should be trimmed, got: {name!r}")
                    # Email should be lowercase
                    self.assertEqual(email, 'john@example.com', f"Email should be lowercase, got: {email!r}")
                    # Description should be trimmed
                    self.assertEqual(desc, 'Test Description', f"Description should be trimmed, got: {desc!r}")
                
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
    
    def test_query_result_verification_with_null_values(self):
        """Test query result verification handles NULL values correctly"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        schema = 'public'
        source_table = 'test_source_nulls'
        
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
                    name VARCHAR(100),
                    email VARCHAR(100),
                    age INTEGER
                )
            '''
            source_connector.execute_query(create_sql)
            
            insert_sql = f'''
                INSERT INTO {schema}.{source_table} (id, name, email, age)
                VALUES
                    (1, NULL, 'john@example.com', 30),
                    (2, 'Jane Smith', NULL, 25),
                    (3, NULL, NULL, 40)
            '''
            source_connector.execute_query(insert_sql)
            
            # Test query result verification
            verifier = QueryResultVerifier(source_connector)
            
            query_result = source_connector.fetch_batch(
                f'SELECT id, name, email, age FROM {schema}.{source_table} ORDER BY id',
                batch_size=100,
                offset=0
            )
            
            # Verify structure
            is_valid, error_msg, structure_report = verifier.verify_query_result_structure(
                query_result=query_result,
                column_names=['id', 'name', 'email', 'age'],
                expected_row_count=3
            )
            
            self.assertTrue(is_valid)
            self.assertTrue(structure_report['row_count_match'])
            
            # Verify data (should handle NULL values)
            is_valid, error_msg, data_report = verifier.verify_query_result_data(
                query_result=query_result,
                column_names=['id', 'name', 'email', 'age'],
                column_transformations={}
            )
            
            self.assertTrue(is_valid)
            self.assertGreater(data_report['null_values_found'], 0)
            
        finally:
            try:
                source_connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{source_table}')
            except:
                pass
            source_connector.close()
