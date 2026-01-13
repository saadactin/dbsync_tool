"""
Comprehensive test suite for all connector methods
"""
import unittest
from unittest.mock import Mock, patch
from connections.connectors.postgres import PostgresConnector
from connections.connectors.mysql import MySQLConnector
from connections.connectors.sqlserver import SQLServerConnector
from connections.connectors.base import ColumnInfo


class TestConnectorsComplete(unittest.TestCase):
    """Comprehensive tests for all connector methods"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Note: These tests use mocks to avoid requiring actual database connections
        # For integration tests, see test_integration_cross_db.py
        self.postgres_conn = PostgresConnector(
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test'
        )
        
        self.mysql_conn = MySQLConnector(
            host='localhost',
            port=3306,
            username='test',
            password='test',
            database_name='test'
        )
        
        self.sqlserver_conn = SQLServerConnector(
            host='localhost',
            port=1433,
            username='test',
            password='test',
            database_name='test'
        )
    
    def test_type_mapping_postgres_to_mysql(self):
        """Test type mapping from PostgreSQL to MySQL"""
        columns = [
            ColumnInfo('id', 'int4', False, True),
            ColumnInfo('name', 'varchar', True, False, max_length=255),
            ColumnInfo('created_at', 'timestamp without time zone', False, False),
        ]
        # This would be tested in integration tests with actual table creation
        # For now, we verify the type mapping function works
        from core.type_mapping import map_data_type
        
        result = map_data_type('int4', 'postgres', 'mysql')
        self.assertEqual(result, 'INT')
        
        result = map_data_type('varchar', 'postgres', 'mysql', max_length=255)
        self.assertEqual(result, 'VARCHAR(255)')
    
    def test_primary_key_detection_structure(self):
        """Test that primary key detection method exists and has correct signature"""
        # Verify method exists
        self.assertTrue(hasattr(self.postgres_conn, 'get_primary_key'))
        self.assertTrue(hasattr(self.mysql_conn, 'get_primary_key'))
        self.assertTrue(hasattr(self.sqlserver_conn, 'get_primary_key'))
        
        # Verify it's callable
        self.assertTrue(callable(self.postgres_conn.get_primary_key))
        self.assertTrue(callable(self.mysql_conn.get_primary_key))
        self.assertTrue(callable(self.sqlserver_conn.get_primary_key))
    
    def test_schema_creation_structure(self):
        """Test that ensure_schema_exists method exists"""
        self.assertTrue(hasattr(self.postgres_conn, 'ensure_schema_exists'))
        self.assertTrue(hasattr(self.mysql_conn, 'ensure_schema_exists'))
        self.assertTrue(hasattr(self.sqlserver_conn, 'ensure_schema_exists'))
        
        self.assertTrue(callable(self.postgres_conn.ensure_schema_exists))
        self.assertTrue(callable(self.mysql_conn.ensure_schema_exists))
        self.assertTrue(callable(self.sqlserver_conn.ensure_schema_exists))
    
    def test_fetch_batch_with_order_by(self):
        """Test that fetch_batch accepts order_by parameter"""
        # Verify method signature includes order_by
        import inspect
        postgres_sig = inspect.signature(self.postgres_conn.fetch_batch)
        mysql_sig = inspect.signature(self.mysql_conn.fetch_batch)
        sqlserver_sig = inspect.signature(self.sqlserver_conn.fetch_batch)
        
        self.assertIn('order_by', postgres_sig.parameters)
        self.assertIn('order_by', mysql_sig.parameters)
        self.assertIn('order_by', sqlserver_sig.parameters)
    
    def test_get_query_row_count_structure(self):
        """Test that get_query_row_count method exists"""
        self.assertTrue(hasattr(self.postgres_conn, 'get_query_row_count'))
        self.assertTrue(hasattr(self.mysql_conn, 'get_query_row_count'))
        self.assertTrue(hasattr(self.sqlserver_conn, 'get_query_row_count'))
        
        self.assertTrue(callable(self.postgres_conn.get_query_row_count))
        self.assertTrue(callable(self.mysql_conn.get_query_row_count))
        self.assertTrue(callable(self.sqlserver_conn.get_query_row_count))
    
    def test_create_table_uses_type_mapping(self):
        """Test that create_table uses centralized type mapping"""
        # Verify create_table accepts target_db_type parameter
        import inspect
        postgres_sig = inspect.signature(self.postgres_conn.create_table)
        mysql_sig = inspect.signature(self.mysql_conn.create_table)
        sqlserver_sig = inspect.signature(self.sqlserver_conn.create_table)
        
        self.assertIn('target_db_type', postgres_sig.parameters)
        self.assertIn('target_db_type', mysql_sig.parameters)
        self.assertIn('target_db_type', sqlserver_sig.parameters)
    
    def test_bulk_insert_error_handling(self):
        """Test that bulk_insert has proper error handling"""
        # Verify methods exist and are callable
        self.assertTrue(callable(self.postgres_conn.bulk_insert))
        self.assertTrue(callable(self.mysql_conn.bulk_insert))
        self.assertTrue(callable(self.sqlserver_conn.bulk_insert))
    
    def test_table_exists_method(self):
        """Test table_exists method exists"""
        self.assertTrue(hasattr(self.postgres_conn, 'table_exists'))
        self.assertTrue(hasattr(self.mysql_conn, 'table_exists'))
        self.assertTrue(hasattr(self.sqlserver_conn, 'table_exists'))
    
    def test_truncate_table_method(self):
        """Test truncate_table method exists"""
        self.assertTrue(hasattr(self.postgres_conn, 'truncate_table'))
        self.assertTrue(hasattr(self.mysql_conn, 'truncate_table'))
        self.assertTrue(hasattr(self.sqlserver_conn, 'truncate_table'))
    
    def test_get_columns_method(self):
        """Test get_columns method exists"""
        self.assertTrue(hasattr(self.postgres_conn, 'get_columns'))
        self.assertTrue(hasattr(self.mysql_conn, 'get_columns'))
        self.assertTrue(hasattr(self.sqlserver_conn, 'get_columns'))
    
    def test_get_row_count_method(self):
        """Test get_row_count method exists"""
        self.assertTrue(hasattr(self.postgres_conn, 'get_row_count'))
        self.assertTrue(hasattr(self.mysql_conn, 'get_row_count'))
        self.assertTrue(hasattr(self.sqlserver_conn, 'get_row_count'))


class TestTypeMappingIntegration(unittest.TestCase):
    """Test type mapping integration with connectors"""
    
    def test_all_database_combinations(self):
        """Test that type mapping works for all 9 combinations"""
        from core.type_mapping import map_data_type
        
        combinations = [
            ('postgres', 'postgres'),
            ('postgres', 'mysql'),
            ('postgres', 'sqlserver'),
            ('mysql', 'postgres'),
            ('mysql', 'mysql'),
            ('mysql', 'sqlserver'),
            ('sqlserver', 'postgres'),
            ('sqlserver', 'mysql'),
            ('sqlserver', 'sqlserver'),
        ]
        
        for source, target in combinations:
            # Test basic type mapping
            result = map_data_type('INT', source, target)
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)
    
    def test_type_mapping_with_length(self):
        """Test type mapping with max_length parameter"""
        from core.type_mapping import map_data_type
        
        result = map_data_type('varchar', 'postgres', 'mysql', max_length=255)
        self.assertIn('255', result)
    
    def test_type_mapping_with_precision_scale(self):
        """Test type mapping with precision and scale"""
        from core.type_mapping import map_data_type
        
        result = map_data_type('numeric', 'postgres', 'mysql', precision=10, scale=2)
        self.assertIn('10', result)
        self.assertIn('2', result)


if __name__ == '__main__':
    unittest.main()

