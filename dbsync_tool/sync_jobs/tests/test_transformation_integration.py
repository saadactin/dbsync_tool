"""
Integration tests for transformation feature with real databases
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable
from sync_engine.transformation_engine import TransformationEngine
from sync_engine.transformation_validator import TransformationValidator
from sync_engine.query_builder import QueryBuilder
from connections.connectors.factory import get_connector
from connections.connectors.base import ColumnInfo
import os
import logging

logger = logging.getLogger(__name__)


class TransformationIntegrationTest(TransactionTestCase):
    """Integration tests for transformations with real databases"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='transformationtest',
            password='testpass123',
            email='transformation@example.com'
        )
        cls.engine = TransformationEngine()
        cls.validator = TransformationValidator()
    
    def setUp(self):
        """Set up test data"""
        # Try to get existing connections or use defaults
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
                    'database': pg_conn.database_name,
                }
            else:
                self.postgres_config = {
                    'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
                    'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
                    'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
                    'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
                    'database': os.getenv('TEST_POSTGRES_DB', 'tauseef'),
                }
        except Exception as e:
            logger.warning(f"Could not load PostgreSQL connection: {str(e)}")
            self.postgres_config = None
    
    def _check_database_available(self, db_type):
        """Check if test database is available"""
        if db_type == 'postgres' and not self.postgres_config:
            return False
        
        try:
            if db_type == 'postgres':
                from connections.connectors.postgres import PostgresConnector
                connector = PostgresConnector(
                    host=self.postgres_config['host'],
                    port=self.postgres_config['port'],
                    username=self.postgres_config['username'],
                    password=self.postgres_config['password'],
                    database_name=self.postgres_config['database']
                )
                connector.connect()
                connector.close()
                return True
        except Exception as e:
            logger.warning(f"Database {db_type} not available: {str(e)}")
            return False
        return False
    
    def _create_test_table(self, connector, schema, table_name):
        """Create a test table with sample data"""
        connector.connect()
        try:
            connector.ensure_schema_exists(schema)
            
            # Drop table if exists
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table_name}')
            except:
                pass
            
            # Create table
            if QueryBuilder.get_db_type(connector) == 'postgres':
                create_sql = f'''
                    CREATE TABLE {schema}.{table_name} (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255),
                        email VARCHAR(255),
                        age INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                '''
            elif QueryBuilder.get_db_type(connector) == 'mysql':
                create_sql = f'''
                    CREATE TABLE {table_name} (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255),
                        email VARCHAR(255),
                        age INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                '''
            else:
                return False
            
            connector.execute_query(create_sql)
            
            # Insert test data
            insert_sql = f'''
                INSERT INTO {schema}.{table_name} (name, email, age, created_at)
                VALUES
                    ('  John  ', 'JOHN@EXAMPLE.COM', 25, '2020-01-01'),
                    ('Jane', 'jane@example.com', 30, '2021-01-01'),
                    ('  Bob  ', 'BOB@EXAMPLE.COM', 35, '2022-01-01'),
                    (NULL, 'test@example.com', 40, '2023-01-01')
            '''
            connector.execute_query(insert_sql)
            
            return True
        except Exception as e:
            logger.error(f"Failed to create test table: {str(e)}")
            return False
        finally:
            connector.close()
    
    def test_query_transformation_with_real_database(self):
        """Test WHERE clause transformation with real database"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        table = 'test_transformation_table'
        
        if not self._create_test_table(connector, schema, table):
            self.skipTest("Failed to create test table")
        
        try:
            connector.connect()
            
            # Build query with WHERE clause
            query = QueryBuilder.build_select_query(
                connector=connector,
                schema=schema,
                table=table,
                columns=['id', 'name', 'email', 'age']
            )
            
            # Apply WHERE transformation
            transformed_query = self.engine.apply_query_transformations(
                query=query,
                where_clause="age > 25"
            )
            
            # Execute query
            cursor = connector._connection.cursor()
            cursor.execute(transformed_query)
            results = cursor.fetchall()
            cursor.close()
            
            # Verify results (should only have rows with age > 25)
            self.assertGreater(len(results), 0)
            for row in results:
                age_idx = 3  # age is 4th column
                self.assertGreater(row[age_idx], 25)
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            connector.close()
    
    def test_column_transformation_with_real_database(self):
        """Test column transformations with real database"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        table = 'test_transformation_table'
        
        if not self._create_test_table(connector, schema, table):
            self.skipTest("Failed to create test table")
        
        try:
            connector.connect()
            
            # Build query with column transformations
            query = QueryBuilder.build_select_query(
                connector=connector,
                schema=schema,
                table=table,
                columns=['name', 'email'],
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Execute query
            cursor = connector._connection.cursor()
            cursor.execute(query)
            results = cursor.fetchall()
            cursor.close()
            
            # Verify transformations applied
            self.assertGreater(len(results), 0)
            for row in results:
                name, email = row
                if name:  # Skip NULL
                    # Name should be trimmed (no leading/trailing spaces)
                    self.assertEqual(name, name.strip())
                if email:  # Skip NULL
                    # Email should be lowercase
                    self.assertEqual(email, email.lower())
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            connector.close()
    
    def test_combined_transformations_real_database(self):
        """Test WHERE clause + column transformations together"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        table = 'test_transformation_table'
        
        if not self._create_test_table(connector, schema, table):
            self.skipTest("Failed to create test table")
        
        try:
            connector.connect()
            
            # Build query with transformations
            query = QueryBuilder.build_select_query(
                connector=connector,
                schema=schema,
                table=table,
                columns=['name', 'email', 'age'],
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            # Apply WHERE clause
            transformed_query = self.engine.apply_query_transformations(
                query=query,
                where_clause="age >= 30"
            )
            
            # Execute query
            cursor = connector._connection.cursor()
            cursor.execute(transformed_query)
            results = cursor.fetchall()
            cursor.close()
            
            # Verify both transformations applied
            self.assertGreater(len(results), 0)
            for row in results:
                name, email, age = row
                # Age filter applied
                self.assertGreaterEqual(age, 30)
                # Column transformations applied
                if name:
                    self.assertEqual(name, name.strip())
                if email:
                    self.assertEqual(email, email.lower())
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            connector.close()
    
    def test_transformation_data_accuracy(self):
        """Test data accuracy with transformations"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        table = 'test_transformation_table'
        
        if not self._create_test_table(connector, schema, table):
            self.skipTest("Failed to create test table")
        
        try:
            connector.connect()
            
            # Get original data
            original_query = QueryBuilder.build_select_query(
                connector=connector,
                schema=schema,
                table=table,
                columns=['name', 'email']
            )
            
            cursor = connector._connection.cursor()
            cursor.execute(original_query)
            original_results = cursor.fetchall()
            
            # Get transformed data
            transformed_query = QueryBuilder.build_select_query(
                connector=connector,
                schema=schema,
                table=table,
                columns=['name', 'email'],
                column_transformations={'name': 'TRIM', 'email': 'LOWER'}
            )
            
            cursor.execute(transformed_query)
            transformed_results = cursor.fetchall()
            cursor.close()
            
            # Verify row count matches
            self.assertEqual(len(original_results), len(transformed_results))
            
            # Verify transformations applied correctly
            for orig_row, trans_row in zip(original_results, transformed_results):
                orig_name, orig_email = orig_row
                trans_name, trans_email = trans_row
                
                if orig_name:
                    self.assertEqual(trans_name, orig_name.strip())
                else:
                    self.assertIsNone(trans_name)
                
                if orig_email:
                    self.assertEqual(trans_email, orig_email.lower())
                else:
                    self.assertIsNone(trans_email)
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            connector.close()
    
    def test_transformation_with_null_values(self):
        """Test transformations with NULL values"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        table = 'test_transformation_table'
        
        if not self._create_test_table(connector, schema, table):
            self.skipTest("Failed to create test table")
        
        try:
            connector.connect()
            
            # Query with transformations
            query = QueryBuilder.build_select_query(
                connector=connector,
                schema=schema,
                table=table,
                columns=['name', 'email'],
                column_transformations={'name': 'TRIM', 'email': 'UPPER'}
            )
            
            cursor = connector._connection.cursor()
            cursor.execute(query)
            results = cursor.fetchall()
            cursor.close()
            
            # Verify NULL values are preserved (not transformed)
            null_found = False
            for row in results:
                name, email = row
                if name is None:
                    null_found = True
                    # NULL should remain NULL
                    self.assertIsNone(name)
            
            self.assertTrue(null_found, "Should have at least one NULL value")
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            connector.close()
    
    def test_transformation_with_special_characters(self):
        """Test transformations with special characters"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        table = 'test_special_chars'
        
        try:
            connector.connect()
            connector.ensure_schema_exists(schema)
            
            # Drop table if exists
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            
            # Create table
            create_sql = f'''
                CREATE TABLE {schema}.{table} (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    description TEXT
                )
            '''
            connector.execute_query(create_sql)
            
            # Insert data with special characters
            insert_sql = f"""
                INSERT INTO {schema}.{table} (name, description)
                VALUES
                    ('  O''Brien  ', 'Test with ''quotes'''),
                    ('José', 'Unicode: 测试'),
                    ('  Test  ', 'Special: !@#$%^&*()')
            """
            connector.execute_query(insert_sql)
            
            # Query with transformations
            query = QueryBuilder.build_select_query(
                connector=connector,
                schema=schema,
                table=table,
                columns=['name', 'description'],
                column_transformations={'name': 'TRIM', 'description': 'UPPER'}
            )
            
            cursor = connector._connection.cursor()
            cursor.execute(query)
            results = cursor.fetchall()
            cursor.close()
            
            # Verify transformations applied correctly
            self.assertGreater(len(results), 0)
            for row in results:
                name, desc = row
                if name:
                    # Name should be trimmed
                    self.assertEqual(name, name.strip())
                if desc:
                    # Description should be uppercase
                    self.assertEqual(desc, desc.upper())
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            connector.close()
    
    def test_validator_with_real_database(self):
        """Test validator with real database"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL not available")
        
        from connections.connectors.postgres import PostgresConnector
        connector = PostgresConnector(**self.postgres_config)
        
        schema = 'public'
        table = 'test_transformation_table'
        
        if not self._create_test_table(connector, schema, table):
            self.skipTest("Failed to create test table")
        
        try:
            connector.connect()
            
            # Test valid WHERE clause
            is_valid, error = self.validator.validate_where_clause(
                where_clause="age > 25",
                schema=schema,
                table=table,
                connector=connector
            )
            self.assertTrue(is_valid, f"Valid WHERE clause rejected: {error}")
            
            # Test valid column transformations
            is_valid, error = self.validator.validate_column_transformations(
                transformations={'name': 'TRIM', 'email': 'UPPER'},
                schema=schema,
                table=table,
                connector=connector
            )
            self.assertTrue(is_valid, f"Valid transformations rejected: {error}")
            
            # Test invalid column
            is_valid, error = self.validator.validate_column_transformations(
                transformations={'nonexistent': 'TRIM'},
                schema=schema,
                table=table,
                connector=connector
            )
            self.assertFalse(is_valid)
            self.assertIn('nonexistent', error)
        finally:
            try:
                connector.execute_query(f'DROP TABLE IF EXISTS {schema}.{table}')
            except:
                pass
            connector.close()
