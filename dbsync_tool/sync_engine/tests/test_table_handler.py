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
    
    def test_get_db_type_clickhouse(self):
        """Test database type detection for ClickHouse"""
        self.source_connector.__class__.__name__ = 'ClickHouseConnector'
        handler = TableHandler(self.source_connector, self.target_connector)
        self.assertEqual(handler.source_db_type, 'clickhouse')
    
    def test_get_db_type_oracle(self):
        """Test database type detection for Oracle"""
        self.source_connector.__class__.__name__ = 'OracleADWConnector'
        handler = TableHandler(self.source_connector, self.target_connector)
        self.assertEqual(handler.source_db_type, 'oracle')
    
    def test_ensure_schema_exists_success(self):
        """Test successful schema creation"""
        # Use PostgreSQL as target (not MySQL, which skips schema creation)
        postgres_target = Mock()
        postgres_target.__class__.__name__ = 'PostgresConnector'
        postgres_target.ensure_schema_exists = Mock()
        handler = TableHandler(self.source_connector, postgres_target)
        handler.ensure_schema_exists('test_schema')
        postgres_target.ensure_schema_exists.assert_called_once_with('public')
    
    def test_ensure_schema_exists_failure(self):
        """Test schema creation failure"""
        # Use PostgreSQL as target (not MySQL, which skips schema creation)
        postgres_target = Mock()
        postgres_target.__class__.__name__ = 'PostgresConnector'
        postgres_target.ensure_schema_exists = Mock(side_effect=Exception("Connection failed"))
        handler = TableHandler(self.source_connector, postgres_target)
        with self.assertRaises(SchemaCreationError):
            handler.ensure_schema_exists('test_schema')
    
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
    
    def test_ensure_schema_exists_clickhouse(self):
        """Test schema creation for ClickHouse (uses databases)"""
        clickhouse_connector = Mock()
        clickhouse_connector.__class__.__name__ = 'ClickHouseConnector'
        clickhouse_connector.ensure_schema_exists = Mock()
        
        handler = TableHandler(self.source_connector, clickhouse_connector)
        handler.ensure_schema_exists('test_db')
        # ClickHouse should use database name directly
        clickhouse_connector.ensure_schema_exists.assert_called_once_with('test_db')
    
    def test_create_table_if_not_exists_clickhouse_target(self):
        """Test table creation with ClickHouse as target"""
        clickhouse_connector = Mock()
        clickhouse_connector.__class__.__name__ = 'ClickHouseConnector'
        clickhouse_connector.table_exists = Mock(return_value=False)
        clickhouse_connector.ensure_schema_exists = Mock()
        clickhouse_connector.create_table = Mock()
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int4', False, True, None)
        ])
        
        handler = TableHandler(self.source_connector, clickhouse_connector)
        result = handler.create_table_if_not_exists('test_db', 'test_table')
        
        self.assertTrue(result)
        # ClickHouse create_table should be called with target_db_type parameter
        clickhouse_connector.create_table.assert_called_once()
        call_args = clickhouse_connector.create_table.call_args
        self.assertEqual(call_args[0][0], 'test_db')  # schema
        self.assertEqual(call_args[0][1], 'test_table')  # table
        # Check that target_db_type is passed
        self.assertEqual(call_args[1]['target_db_type'], 'postgres')

    def test_create_table_if_not_exists_oracle_target_reuses_compatible_table(self):
        """Oracle as target: reuse existing table when schema is compatible."""
        # Source: Postgres, Target: Oracle
        source = Mock()
        source.__class__.__name__ = 'PostgresConnector'
        source.get_columns = Mock(return_value=[
            ColumnInfo('id', 'integer', False, True, None),
        ])

        target = Mock()
        target.__class__.__name__ = 'OracleADWConnector'
        target.table_exists = Mock(return_value=True)
        # Existing column is wider than required (precision 19 vs 10)
        target.get_columns = Mock(return_value=[
            ColumnInfo('ID', 'NUMBER(19)', False, True, None),
        ])

        handler = TableHandler(source, target)
        result = handler.create_table_if_not_exists('myschema', 'mytable')

        self.assertFalse(result)
        target.create_table.assert_not_called()

    def test_create_table_if_not_exists_oracle_target_creates_when_missing(self):
        """Oracle as target: create table using Oracle-aware mappings when it does not exist."""
        source = Mock()
        source.__class__.__name__ = 'PostgresConnector'
        source.get_columns = Mock(return_value=[
            ColumnInfo('id', 'integer', False, True, None),
            ColumnInfo('name', 'character varying(50)', True, False, 50),
        ])

        target = Mock()
        target.__class__.__name__ = 'OracleADWConnector'
        target.table_exists = Mock(return_value=False)
        target.ensure_schema_exists = Mock()
        target.create_table = Mock()

        handler = TableHandler(source, target)
        result = handler.create_table_if_not_exists('myschema', 'mytable')

        self.assertTrue(result)
        target.create_table.assert_called_once()
        call_args = target.create_table.call_args
        # schema, table, columns
        self.assertEqual(call_args[0][0], 'myschema')
        self.assertEqual(call_args[0][1], 'mytable')
        created_columns = call_args[0][2]
        self.assertGreaterEqual(len(created_columns), 2)
        # The mapped Oracle types should be NUMBER(...) and VARCHAR2(...) or CLOB
        id_col = created_columns[0]
        name_col = created_columns[1]
        self.assertIn('NUMBER', id_col.data_type.upper())
        self.assertTrue(
            'VARCHAR2' in name_col.data_type.upper() or 'CLOB' in name_col.data_type.upper()
        )


if __name__ == '__main__':
    unittest.main()



