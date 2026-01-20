"""
Tests for table handler
"""
import unittest
from unittest.mock import Mock, MagicMock
from connections.connectors.base import ColumnInfo
from sync_engine.table_handler import TableHandler
from sync_engine.exceptions import SchemaCreationError, TableCreationError


class TestTableHandler(unittest.TestCase):
    """Test cases for TableHandler"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.source_connector = Mock()
        self.target_connector = Mock()
        self.source_connector.__class__.__name__ = 'PostgresConnector'
        self.target_connector.__class__.__name__ = 'MySQLConnector'
        
        self.handler = TableHandler(self.source_connector, self.target_connector)
    
    def test_get_db_type_postgres(self):
        """Test database type detection for PostgreSQL"""
        self.source_connector.__class__.__name__ = 'PostgresConnector'
        handler = TableHandler(self.source_connector, self.target_connector)
        self.assertEqual(handler.source_db_type, 'postgres')
    
    def test_get_db_type_mysql(self):
        """Test database type detection for MySQL"""
        self.source_connector.__class__.__name__ = 'MySQLConnector'
        handler = TableHandler(self.source_connector, self.target_connector)
        self.assertEqual(handler.source_db_type, 'mysql')
    
    def test_get_db_type_sqlserver(self):
        """Test database type detection for SQL Server"""
        self.source_connector.__class__.__name__ = 'SQLServerConnector'
        handler = TableHandler(self.source_connector, self.target_connector)
        self.assertEqual(handler.source_db_type, 'sqlserver')
    
    def test_ensure_schema_exists_success(self):
        """Test successful schema creation"""
        self.target_connector.ensure_schema_exists = Mock()
        self.handler.ensure_schema_exists('test_schema')
        self.target_connector.ensure_schema_exists.assert_called_once_with('test_schema')
    
    def test_ensure_schema_exists_failure(self):
        """Test schema creation failure"""
        self.target_connector.ensure_schema_exists = Mock(side_effect=Exception("Connection failed"))
        with self.assertRaises(SchemaCreationError):
            self.handler.ensure_schema_exists('test_schema')
    
    def test_create_table_if_not_exists_table_exists(self):
        """Test table creation when table already exists"""
        self.target_connector.table_exists = Mock(return_value=True)
        result = self.handler.create_table_if_not_exists('schema', 'table')
        self.assertFalse(result)
        self.target_connector.create_table.assert_not_called()
    
    def test_create_table_if_not_exists_creates_table(self):
        """Test table creation when table doesn't exist"""
        self.target_connector.table_exists = Mock(return_value=False)
        self.target_connector.ensure_schema_exists = Mock()
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int4', False, True, None)
        ])
        self.target_connector.create_table = Mock()
        
        result = self.handler.create_table_if_not_exists('schema', 'table')
        self.assertTrue(result)
        self.target_connector.create_table.assert_called_once()


if __name__ == '__main__':
    unittest.main()



