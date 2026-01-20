"""
Query-before-migration flow tests for Day 6

Tests comprehensive query execution before migration:
- Query execution on source BEFORE migration starts
- Query result storage and verification
- Pre-migration query result comparison with post-migration target
- Perfect accuracy verification
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from sync_engine.pre_migration_validator import PreMigrationValidator
from sync_engine.query_result_verifier import QueryResultVerifier
from connections.connectors.factory import get_connector
import os
import logging

logger = logging.getLogger(__name__)


class QueryBeforeMigrationDay6Test(TransactionTestCase):
    """Test query execution before migration flow"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='querybeforemigrationday6',
            password='testpass123',
            email='querybeforemigrationday6@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        # PostgreSQL configuration
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
    
    def _create_test_table_with_data(self, connector, schema, table_name, row_count=50):
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
                    is_active BOOLEAN
                )
            '''
            connector.execute_query(create_sql)
            
            # Insert test data
            for i in range(1, row_count + 1):
                insert_sql = f'''
                    INSERT INTO {schema}.{table_name} (id, name, email, age, salary, is_active)
                    VALUES (
                        {i},
                        '{"  User " + str(i) + "  "}',
                        'User{i}@EXAMPLE.COM',
                        {20 + (i % 50)},
                        {50000.00 + (i * 100)},
                        {i % 2 == 0}
                    )
                '''
                connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_query_execution_before_migration_with_where_clause(self):
        """Test query execution before migration with WHERE clause"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_query_before'
        target_table = 'test_target_query_before'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table, 100):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Query Before',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Query Before',
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
                name='Test Query Before Migration',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with WHERE clause
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30 AND age <= 50",
                column_transformations=None
            )
            
            # Test pre-migration validation
            source_connector.connect()
            try:
                validator = PreMigrationValidator(source_connector)
                
                # Build transformed query
                from sync_engine.query_builder import QueryBuilder
                from sync_engine.transformation_engine import TransformationEngine
                
                query_builder = QueryBuilder()
                transformation_engine = TransformationEngine()
                
                # Get column names
                columns = source_connector.get_columns(schema, source_table)
                column_names = [col.name for col in columns]
                
                # Build base query
                base_query = query_builder.build_select_query(
                    connector=source_connector,
                    schema=schema,
                    table=source_table,
                    columns=column_names
                )
                
                # Apply transformations
                transformed_query = transformation_engine.apply_query_transformations(
                    query=base_query,
                    where_clause=job_table.transformation_query,
                    column_transformations=job_table.column_transformations or {},
                    connector=source_connector
                )
                
                # Validate transformation query (this executes query before migration)
                is_valid, error_msg, validation_report = validator.validate_transformation_query(
                    job_table=job_table,
                    transformed_query=transformed_query,
                    base_query=base_query,
                    column_names=column_names
                )
                
                # Verify validation passed
                self.assertTrue(is_valid, f"Pre-migration validation failed: {error_msg}")
                
                # Verify query results were stored
                self.assertIn('query_results', validation_report)
                self.assertIn('query_result_count', validation_report)
                self.assertIn('expected_row_count', validation_report)
                
                # Verify query was executed
                query_results = validation_report.get('query_results', [])
                query_result_count = validation_report.get('query_result_count', 0)
                expected_row_count = validation_report.get('expected_row_count', 0)
                
                self.assertGreater(query_result_count, 0, "Query should return some results")
                self.assertEqual(len(query_results), query_result_count)
                
                # Verify structure was verified
                self.assertTrue(validation_report.get('structure_verified', False))
                self.assertTrue(validation_report.get('data_verified', False))
                
                logger.info(
                    f"✓ Query execution before migration verified: "
                    f"{query_result_count} rows, expected {expected_row_count}"
                )
                
            finally:
                source_connector.close()
            
            # Now execute sync and verify post-migration comparison
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Verify target has correct data
            target_connector.connect()
            try:
                target_count = target_connector.get_row_count(schema, target_table)
                self.assertEqual(target_count, expected_row_count)
                
                logger.info(f"✓ Post-migration verification passed: {target_count} rows")
                
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
    
    def test_query_result_comparison_with_target(self):
        """Test comparison of pre-migration query results with post-migration target"""
        if not self._check_database_available():
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        
        source_connector = PostgresConnector(**self.postgres_config)
        target_connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        source_table = 'test_source_query_compare'
        target_table = 'test_target_query_compare'
        
        # Create source table with data
        if not self._create_test_table_with_data(source_connector, schema, source_table, 50):
            self.skipTest("Failed to create source table")
        
        try:
            # Create connections
            source_conn = DatabaseConnection.objects.create(
                name='Test Source Query Compare',
                db_type='postgres',
                host=self.postgres_config['host'],
                port=self.postgres_config['port'],
                username=self.postgres_config['username'],
                password=self.postgres_config['password'],
                database_name=self.postgres_config['database_name'],
                created_by=self.user
            )
            
            target_conn = DatabaseConnection.objects.create(
                name='Test Target Query Compare',
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
                name='Test Query Result Comparison',
                source_connection=source_conn,
                target_connection=target_conn,
                sync_type='full',
                created_by=self.user
            )
            
            # Create job table with transformations
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name=schema,
                table_name=source_table,
                transformation_query="age >= 30",
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Get pre-migration query results
            source_connector.connect()
            try:
                validator = PreMigrationValidator(source_connector)
                
                from sync_engine.query_builder import QueryBuilder
                from sync_engine.transformation_engine import TransformationEngine
                
                query_builder = QueryBuilder()
                transformation_engine = TransformationEngine()
                
                columns = source_connector.get_columns(schema, source_table)
                column_names = [col.name for col in columns]
                
                base_query = query_builder.build_select_query(
                    connector=source_connector,
                    schema=schema,
                    table=source_table,
                    columns=column_names
                )
                
                transformed_query = transformation_engine.apply_query_transformations(
                    query=base_query,
                    where_clause=job_table.transformation_query,
                    column_transformations=job_table.column_transformations or {},
                    connector=source_connector
                )
                
                is_valid, error_msg, validation_report = validator.validate_transformation_query(
                    job_table=job_table,
                    transformed_query=transformed_query,
                    base_query=base_query,
                    column_names=column_names
                )
                
                self.assertTrue(is_valid)
                pre_migration_query_results = validation_report.get('query_results', [])
                
            finally:
                source_connector.close()
            
            # Execute sync
            executor = SyncExecutor(job)
            execution = executor.create_execution()
            executor.execute()
            
            # Compare pre-migration query results with target
            target_connector.connect()
            try:
                query_verifier = QueryResultVerifier(source_connector)
                
                # Fetch target rows
                target_rows = target_connector.fetch_batch(
                    query=query_builder.build_select_query(
                        connector=target_connector,
                        schema=schema,
                        table=target_table,
                        columns=column_names,
                        order_by='id'
                    ),
                    batch_size=1000,
                    offset=0
                )
                
                # Compare
                matches, error, comparison_report = query_verifier.compare_query_results_with_target(
                    source_query_result=pre_migration_query_results,
                    target_rows=target_rows if target_rows else [],
                    column_names=column_names,
                    column_transformations=job_table.column_transformations or {}
                )
                
                # Verify comparison passed
                self.assertTrue(matches, f"Query result comparison failed: {error}")
                self.assertTrue(comparison_report.get('rows_match', False))
                
                logger.info(
                    f"✓ Query result comparison verified: "
                    f"{len(pre_migration_query_results)} rows match target exactly"
                )
                
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
