"""
Comprehensive unit tests for transformation engine, query builder, and validator
"""
from django.test import TestCase
from unittest.mock import Mock, MagicMock, patch
from connections.connectors.base import DBConnector, ColumnInfo
from sync_engine.transformation_engine import TransformationEngine
from sync_engine.transformation_validator import TransformationValidator
from sync_engine.query_builder import QueryBuilder
from sync_jobs.models import SyncJob, SyncJobTable
from django.contrib.auth.models import User
from connections.models import DatabaseConnection


class TransformationEngineTest(TestCase):
    """Test TransformationEngine class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.engine = TransformationEngine()
        self.mock_connector = Mock(spec=DBConnector)
        self.mock_connector.__class__.__name__ = 'PostgresConnector'
    
    def test_apply_query_transformations_with_where_clause(self):
        """Test WHERE clause application"""
        query = 'SELECT * FROM "schema"."table"'
        where_clause = "date_col >= '2010-01-01'"
        
        result = self.engine.apply_query_transformations(
            query=query,
            where_clause=where_clause
        )
        
        self.assertIn('WHERE', result)
        self.assertIn(where_clause, result)
    
    def test_apply_query_transformations_with_existing_where(self):
        """Test WHERE clause with existing WHERE in query"""
        query = 'SELECT * FROM "schema"."table" WHERE id > 0'
        where_clause = "date_col >= '2010-01-01'"
        
        result = self.engine.apply_query_transformations(
            query=query,
            where_clause=where_clause
        )
        
        self.assertIn('AND', result)
        self.assertIn(where_clause, result)
    
    def test_apply_query_transformations_with_column_transforms_postgres(self):
        """Test column transformations for PostgreSQL"""
        query = 'SELECT "name", "email" FROM "schema"."table"'
        transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        result = self.engine.apply_query_transformations(
            query=query,
            column_transformations=transformations,
            connector=self.mock_connector
        )
        
        self.assertIn('TRIM("name")', result)
        self.assertIn('UPPER("email")', result)
        self.assertIn('AS "name"', result)
        self.assertIn('AS "email"', result)
    
    def test_apply_query_transformations_with_column_transforms_mysql(self):
        """Test column transformations for MySQL"""
        self.mock_connector.__class__.__name__ = 'MySQLConnector'
        query = 'SELECT `name`, `email` FROM `schema`.`table`'
        transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        result = self.engine.apply_query_transformations(
            query=query,
            column_transformations=transformations,
            connector=self.mock_connector
        )
        
        self.assertIn('TRIM(`name`)', result)
        self.assertIn('UPPER(`email`)', result)
    
    def test_apply_query_transformations_with_column_transforms_sqlserver(self):
        """Test column transformations for SQL Server"""
        # Create a new mock with SQLServer class name
        mock_sqlserver_connector = Mock(spec=DBConnector)
        mock_sqlserver_connector.__class__.__name__ = 'SQLServerConnector'
        query = 'SELECT [name], [email] FROM [schema].[table]'
        transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        result = self.engine.apply_query_transformations(
            query=query,
            column_transformations=transformations,
            connector=mock_sqlserver_connector
        )
        
        self.assertIn('LTRIM(RTRIM([name]))', result)
        self.assertIn('UPPER([email])', result)
        self.assertIn('AS [name]', result)
        self.assertIn('AS [email]', result)
    
    def test_apply_query_transformations_combined(self):
        """Test WHERE clause + column transformations together"""
        query = 'SELECT "name" FROM "schema"."table"'
        where_clause = "id > 0"
        transformations = {'name': 'TRIM'}
        
        result = self.engine.apply_query_transformations(
            query=query,
            where_clause=where_clause,
            column_transformations=transformations,
            connector=self.mock_connector
        )
        
        self.assertIn('WHERE', result)
        self.assertIn(where_clause, result)
        self.assertIn('TRIM("name")', result)
    
    def test_apply_row_transformations_trim(self):
        """Test TRIM transformation on string data"""
        batch = [
            ('  John  ', 'john@example.com', 25),
            ('Jane', 'jane@example.com', 30),
            (None, 'test@example.com', 35)  # NULL value
        ]
        column_names = ['name', 'email', 'age']
        transformations = {'name': 'TRIM'}
        
        result = self.engine.apply_row_transformations(
            batch=batch,
            column_names=column_names,
            column_transformations=transformations
        )
        
        self.assertEqual(result[0][0], 'John')  # Trimmed
        self.assertEqual(result[1][0], 'Jane')  # No change
        self.assertIsNone(result[2][0])  # NULL preserved
    
    def test_apply_row_transformations_upper(self):
        """Test UPPER transformation"""
        batch = [
            ('John', 'john@example.com'),
            ('jane', 'Jane@Example.com')
        ]
        column_names = ['name', 'email']
        transformations = {'name': 'UPPER', 'email': 'UPPER'}
        
        result = self.engine.apply_row_transformations(
            batch=batch,
            column_names=column_names,
            column_transformations=transformations
        )
        
        self.assertEqual(result[0][0], 'JOHN')
        self.assertEqual(result[0][1], 'JOHN@EXAMPLE.COM')
        self.assertEqual(result[1][0], 'JANE')
    
    def test_apply_row_transformations_lower(self):
        """Test LOWER transformation"""
        batch = [
            ('John', 'JOHN@EXAMPLE.COM'),
            ('JANE', 'Jane@Example.com')
        ]
        column_names = ['name', 'email']
        transformations = {'name': 'LOWER'}
        
        result = self.engine.apply_row_transformations(
            batch=batch,
            column_names=column_names,
            column_transformations=transformations
        )
        
        self.assertEqual(result[0][0], 'john')
        self.assertEqual(result[1][0], 'jane')
    
    def test_apply_row_transformations_multiple(self):
        """Test multiple transformations on same row"""
        batch = [
            ('  John  ', 'JOHN@EXAMPLE.COM')
        ]
        column_names = ['name', 'email']
        transformations = {'name': 'TRIM', 'email': 'LOWER'}
        
        result = self.engine.apply_row_transformations(
            batch=batch,
            column_names=column_names,
            column_transformations=transformations
        )
        
        self.assertEqual(result[0][0], 'John')  # Trimmed
        self.assertEqual(result[0][1], 'john@example.com')  # Lowercased
    
    def test_apply_row_transformations_empty_batch(self):
        """Test with empty batch"""
        result = self.engine.apply_row_transformations(
            batch=[],
            column_names=[],
            column_transformations={}
        )
        
        self.assertEqual(result, [])
    
    def test_apply_row_transformations_preserves_types(self):
        """Test that non-string columns are not modified"""
        batch = [
            ('John', 25, 1000.50, True)
        ]
        column_names = ['name', 'age', 'salary', 'is_active']
        transformations = {'name': 'UPPER'}
        
        result = self.engine.apply_row_transformations(
            batch=batch,
            column_names=column_names,
            column_transformations=transformations
        )
        
        self.assertEqual(result[0][0], 'JOHN')  # Transformed
        self.assertEqual(result[0][1], 25)  # Preserved
        self.assertEqual(result[0][2], 1000.50)  # Preserved
        self.assertEqual(result[0][3], True)  # Preserved
    
    def test_validate_transformations_valid(self):
        """Test validation with valid transformations"""
        self.mock_connector.get_columns = Mock(return_value=[
            ColumnInfo('name', 'VARCHAR', True, False),
            ColumnInfo('email', 'VARCHAR', True, False)
        ])
        
        is_valid, error = self.engine.validate_transformations(
            schema='schema',
            table='table',
            where_clause="id > 0",
            column_transformations={'name': 'TRIM'},
            connector=self.mock_connector
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_transformations_invalid_column(self):
        """Test validation with non-existent column"""
        self.mock_connector.get_columns = Mock(return_value=[
            ColumnInfo('name', 'VARCHAR', True, False)
        ])
        
        is_valid, error = self.engine.validate_transformations(
            schema='schema',
            table='table',
            column_transformations={'nonexistent': 'TRIM'},
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        self.assertIn('nonexistent', error)
    
    def test_validate_transformations_invalid_function(self):
        """Test validation with invalid transformation function"""
        self.mock_connector.get_columns = Mock(return_value=[
            ColumnInfo('name', 'VARCHAR', True, False)
        ])
        
        is_valid, error = self.engine.validate_transformations(
            schema='schema',
            table='table',
            column_transformations={'name': 'INVALID'},
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        self.assertIn('Invalid transformation', error)
    
    def test_validate_transformations_sql_injection_where(self):
        """Test validation detects SQL injection in WHERE clause"""
        self.mock_connector.get_columns = Mock(return_value=[])
        
        is_valid, error = self.engine.validate_transformations(
            schema='schema',
            table='table',
            where_clause="'; DROP TABLE users; --",
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        self.assertIn('dangerous', error.lower())


class QueryBuilderTransformationTest(TestCase):
    """Test QueryBuilder transformation enhancements"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Use actual connector classes with minimal setup
        from connections.connectors.postgres import PostgresConnector
        from connections.connectors.mysql import MySQLConnector
        from connections.connectors.sqlserver import SQLServerConnector
        
        self.mock_postgres_connector = PostgresConnector('localhost', 5432, 'user', 'pass', 'db')
        self.mock_mysql_connector = MySQLConnector('localhost', 3306, 'user', 'pass', 'db')
        self.mock_sqlserver_connector = SQLServerConnector('localhost', 1433, 'user', 'pass', 'db')
    
    def test_build_select_query_with_column_transformations_postgres(self):
        """Test PostgreSQL column transformation syntax"""
        transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        query = QueryBuilder.build_select_query(
            connector=self.mock_postgres_connector,
            schema='schema',
            table='table',
            columns=['name', 'email'],
            column_transformations=transformations
        )
        
        self.assertIn('TRIM("name")', query)
        self.assertIn('UPPER("email")', query)
        self.assertIn('AS "name"', query)
        self.assertIn('AS "email"', query)
    
    def test_build_select_query_with_column_transformations_mysql(self):
        """Test MySQL column transformation syntax"""
        transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        query = QueryBuilder.build_select_query(
            connector=self.mock_mysql_connector,
            schema='schema',
            table='table',
            columns=['name', 'email'],
            column_transformations=transformations
        )
        
        self.assertIn('TRIM(`name`)', query)
        self.assertIn('UPPER(`email`)', query)
    
    def test_build_select_query_with_column_transformations_sqlserver(self):
        """Test SQL Server column transformation syntax"""
        transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        query = QueryBuilder.build_select_query(
            connector=self.mock_sqlserver_connector,
            schema='schema',
            table='table',
            columns=['name', 'email'],
            column_transformations=transformations
        )
        
        self.assertIn('LTRIM(RTRIM([name]))', query)
        self.assertIn('UPPER([email])', query)
    
    def test_build_select_query_backward_compatible(self):
        """Test that existing calls (without transformations) work unchanged"""
        query = QueryBuilder.build_select_query(
            connector=self.mock_postgres_connector,
            schema='schema',
            table='table',
            columns=['name', 'email']
        )
        
        self.assertIn('SELECT', query)
        self.assertIn('"name"', query)
        self.assertIn('"email"', query)
        self.assertNotIn('TRIM', query)
        self.assertNotIn('UPPER', query)
    
    def test_apply_column_transformations_all_db_types(self):
        """Test column transformation application for all DB types"""
        columns = ['name', 'email']
        transformations = {'name': 'TRIM', 'email': 'UPPER'}
        
        # PostgreSQL
        result_pg = QueryBuilder.apply_column_transformations(
            columns, transformations, 'postgres'
        )
        self.assertIn('TRIM("name")', result_pg)
        self.assertIn('UPPER("email")', result_pg)
        
        # MySQL
        result_mysql = QueryBuilder.apply_column_transformations(
            columns, transformations, 'mysql'
        )
        self.assertIn('TRIM(`name`)', result_mysql)
        self.assertIn('UPPER(`email`)', result_mysql)
        
        # SQL Server
        result_sqlserver = QueryBuilder.apply_column_transformations(
            columns, transformations, 'sqlserver'
        )
        self.assertIn('LTRIM(RTRIM([name]))', result_sqlserver)
        self.assertIn('UPPER([email])', result_sqlserver)


class TransformationValidatorTest(TestCase):
    """Test TransformationValidator class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.validator = TransformationValidator()
        self.mock_connector = Mock(spec=DBConnector)
        self.mock_connector.get_tables = Mock(return_value=['table'])
        self.mock_connector.get_columns = Mock(return_value=[
            ColumnInfo('name', 'VARCHAR', True, False),
            ColumnInfo('email', 'VARCHAR', True, False)
        ])
    
    def test_validate_where_clause_valid(self):
        """Test valid WHERE clause"""
        is_valid, error = self.validator.validate_where_clause(
            where_clause="id > 0",
            schema='schema',
            table='table',
            connector=self.mock_connector
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_where_clause_sql_injection(self):
        """Test SQL injection detection"""
        is_valid, error = self.validator.validate_where_clause(
            where_clause="'; DROP TABLE users; --",
            schema='schema',
            table='table',
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        self.assertIn('dangerous', error.lower())
    
    def test_validate_where_clause_dangerous_keyword(self):
        """Test detection of dangerous keywords"""
        is_valid, error = self.validator.validate_where_clause(
            where_clause="id > 0; DROP TABLE users",
            schema='schema',
            table='table',
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        # Error message should indicate dangerous patterns were detected
        self.assertIsNotNone(error)
        self.assertTrue(len(error) > 0)
    
    def test_validate_where_clause_invalid_syntax(self):
        """Test invalid WHERE clause syntax"""
        is_valid, error = self.validator.validate_where_clause(
            where_clause="",
            schema='schema',
            table='table',
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        self.assertIn('empty', error.lower())
    
    def test_validate_column_transformations_valid(self):
        """Test valid column transformations"""
        is_valid, error = self.validator.validate_column_transformations(
            transformations={'name': 'TRIM', 'email': 'UPPER'},
            schema='schema',
            table='table',
            connector=self.mock_connector
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_column_transformations_nonexistent_column(self):
        """Test with non-existent column"""
        is_valid, error = self.validator.validate_column_transformations(
            transformations={'nonexistent': 'TRIM'},
            schema='schema',
            table='table',
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        self.assertIn('nonexistent', error)
    
    def test_validate_column_transformations_invalid_function(self):
        """Test with invalid transformation function"""
        is_valid, error = self.validator.validate_column_transformations(
            transformations={'name': 'INVALID'},
            schema='schema',
            table='table',
            connector=self.mock_connector
        )
        
        self.assertFalse(is_valid)
        self.assertIn('Invalid transformation', error)


class SyncJobTableTransformationTest(TestCase):
    """Test SyncJobTable model with transformation fields"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.source_conn = DatabaseConnection.objects.create(
            name='Source DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='postgres',
            password='postgres',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        self.target_conn = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='mysql',
            host='localhost',
            port=3306,
            username='root',
            password='root',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            created_by=self.user
        )
    
    def test_sync_job_table_with_transformations(self):
        """Test creating SyncJobTable with transformation fields"""
        job_table = SyncJobTable.objects.create(
            job=self.job,
            schema_name='public',
            table_name='users',
            transformation_query="created_at >= '2010-01-01'",
            column_transformations={'name': 'TRIM', 'email': 'UPPER'}
        )
        
        self.assertEqual(job_table.transformation_query, "created_at >= '2010-01-01'")
        self.assertEqual(job_table.column_transformations, {'name': 'TRIM', 'email': 'UPPER'})
    
    def test_sync_job_table_without_transformations(self):
        """Test creating SyncJobTable without transformation fields (backward compatibility)"""
        job_table = SyncJobTable.objects.create(
            job=self.job,
            schema_name='public',
            table_name='users'
        )
        
        self.assertIsNone(job_table.transformation_query)
        self.assertEqual(job_table.column_transformations, {})
    
    def test_sync_job_table_transformation_fields_defaults(self):
        """Test default values for transformation fields"""
        job_table = SyncJobTable.objects.create(
            job=self.job,
            schema_name='public',
            table_name='users'
        )
        
        # Refresh from database
        job_table.refresh_from_db()
        
        self.assertIsNone(job_table.transformation_query)
        # JSONField with default=dict should return empty dict, not None
        self.assertIsNotNone(job_table.column_transformations)
        self.assertEqual(job_table.column_transformations, {})
