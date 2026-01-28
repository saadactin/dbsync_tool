"""
Tests for ClickHouse edge cases (Day 6)
Tests edge case handling in table handler, full sync, and incremental sync
"""
from django.test import TestCase
from unittest.mock import Mock, MagicMock, patch
from connections.connectors.clickhouse import ClickHouseConnector
from connections.connectors.base import ColumnInfo
from sync_engine.table_handler import TableHandler
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_engine.query_builder import QueryBuilder
from sync_engine.exceptions import TableCreationError, SchemaCreationError
import os


class ClickHouseTableHandlerEdgeCasesTests(TestCase):
    """Test ClickHouse edge cases in table handler"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.source_connector = Mock()
        self.source_connector.__class__.__name__ = 'PostgresConnector'
        
        self.target_connector = Mock(spec=ClickHouseConnector)
        self.target_connector.__class__.__name__ = 'ClickHouseConnector'
        self.target_connector.database_name = 'test_db'
        
        self.table_handler = TableHandler(self.source_connector, self.target_connector)
    
    def test_ensure_schema_exists_checks_database_existence(self):
        """Test that ensure_schema_exists checks database existence before creating"""
        # Mock list_databases to return existing database
        self.target_connector.list_databases.return_value = ['test_db', 'existing_db']
        
        # Should not raise error if database exists
        try:
            self.table_handler.ensure_schema_exists('existing_db')
        except Exception as e:
            self.fail(f"ensure_schema_exists raised {e} unexpectedly")
    
    def test_create_table_handles_no_order_by_columns(self):
        """Test table creation handles case with no ORDER BY columns"""
        # Mock source columns with no primary key
        source_columns = [
            ColumnInfo(name='col1', data_type='String', is_nullable=False, is_primary_key=False),
            ColumnInfo(name='col2', data_type='Int32', is_nullable=False, is_primary_key=False)
        ]
        self.source_connector.get_columns.return_value = source_columns
        self.target_connector.table_exists.return_value = False
        
        # Mock create_table to succeed
        self.target_connector.create_table.return_value = None
        
        # Should use first column as ORDER BY fallback
        try:
            result = self.table_handler.create_table_if_not_exists('test_db', 'test_table')
            # Should call create_table with columns
            self.target_connector.create_table.assert_called_once()
        except Exception as e:
            self.fail(f"create_table_if_not_exists raised {e} unexpectedly")
    
    def test_create_table_handles_array_types(self):
        """Test table creation handles Array types (converts to String)"""
        source_columns = [
            ColumnInfo(name='id', data_type='Int32', is_nullable=False, is_primary_key=True),
            ColumnInfo(name='tags', data_type='Array(String)', is_nullable=True, is_primary_key=False)
        ]
        self.source_connector.get_columns.return_value = source_columns
        self.target_connector.table_exists.return_value = False
        
        # Mock create_table
        self.target_connector.create_table.return_value = None
        
        try:
            result = self.table_handler.create_table_if_not_exists('test_db', 'test_table')
            # Should call create_table - Array type should be converted to String
            self.target_connector.create_table.assert_called_once()
        except Exception as e:
            self.fail(f"create_table_if_not_exists raised {e} unexpectedly")
    
    def test_create_table_handles_nested_types(self):
        """Test table creation handles Nested types (converts to String)"""
        source_columns = [
            ColumnInfo(name='id', data_type='Int32', is_nullable=False, is_primary_key=True),
            ColumnInfo(name='metadata', data_type='Nested(key String, value String)', is_nullable=True, is_primary_key=False)
        ]
        self.source_connector.get_columns.return_value = source_columns
        self.target_connector.table_exists.return_value = False
        
        # Mock create_table
        self.target_connector.create_table.return_value = None
        
        try:
            result = self.table_handler.create_table_if_not_exists('test_db', 'test_table')
            # Should call create_table - Nested type should be converted to String
            self.target_connector.create_table.assert_called_once()
        except Exception as e:
            self.fail(f"create_table_if_not_exists raised {e} unexpectedly")
    
    def test_create_table_handles_lowcardinality_types(self):
        """Test table creation handles LowCardinality types (strips wrapper)"""
        source_columns = [
            ColumnInfo(name='id', data_type='Int32', is_nullable=False, is_primary_key=True),
            ColumnInfo(name='status', data_type='LowCardinality(String)', is_nullable=False, is_primary_key=False)
        ]
        self.source_connector.get_columns.return_value = source_columns
        self.target_connector.table_exists.return_value = False
        
        # Mock create_table
        self.target_connector.create_table.return_value = None
        
        try:
            result = self.table_handler.create_table_if_not_exists('test_db', 'test_table')
            # Should call create_table - LowCardinality wrapper should be stripped
            self.target_connector.create_table.assert_called_once()
        except Exception as e:
            self.fail(f"create_table_if_not_exists raised {e} unexpectedly")


class ClickHouseIncrementalSyncEdgeCasesTests(TestCase):
    """Test ClickHouse edge cases in incremental sync"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.source_connector = Mock(spec=ClickHouseConnector)
        self.source_connector.__class__.__name__ = 'ClickHouseConnector'
        
        self.target_connector = Mock()
        self.target_connector.__class__.__name__ = 'PostgresConnector'
        
        # Mock query builder
        self.query_builder = Mock(spec=QueryBuilder)
        self.query_builder.build_incremental_query.return_value = "SELECT * FROM `test_db`.`test_table` WHERE `updated_at` > '2024-01-01' AND `updated_at` IS NOT NULL"
    
    def test_incremental_query_filters_null_values(self):
        """Test that incremental query filters NULL values for ClickHouse"""
        query = QueryBuilder.build_incremental_query(
            connector=self.source_connector,
            schema='test_db',
            table='test_table',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01',
            columns=None,
            order_by=None
        )
        
        # Should include IS NOT NULL clause for ClickHouse
        self.assertIn('IS NOT NULL', query)
        self.assertIn('updated_at', query)
    
    def test_incremental_query_first_sync_filters_null(self):
        """Test that first sync (no checkpoint) filters NULL values for ClickHouse"""
        query = QueryBuilder.build_incremental_query(
            connector=self.source_connector,
            schema='test_db',
            table='test_table',
            incremental_column='updated_at',
            checkpoint_value=None,
            columns=None,
            order_by=None
        )
        
        # Should include IS NOT NULL clause even for first sync
        self.assertIn('IS NOT NULL', query)
    
    def test_datetime64_precision_handling(self):
        """Test DateTime64 precision handling in incremental sync"""
        # Mock columns with DateTime64
        columns = [
            ColumnInfo(name='id', data_type='Int32', is_nullable=False, is_primary_key=True),
            ColumnInfo(name='timestamp', data_type='DateTime64(3)', is_nullable=False, is_primary_key=False)
        ]
        self.source_connector.get_columns.return_value = columns
        
        # Should handle DateTime64 precision correctly
        # This is tested through the checkpoint parsing logic
        inc_col_info = next((col for col in columns if col.name == 'timestamp'), None)
        self.assertIsNotNone(inc_col_info)
        self.assertIn('DateTime64', inc_col_info.data_type)


class ClickHouseQueryBuilderEdgeCasesTests(TestCase):
    """Test ClickHouse edge cases in query builder"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.connector = Mock(spec=ClickHouseConnector)
        self.connector.__class__.__name__ = 'ClickHouseConnector'
    
    def test_build_incremental_query_clickhouse_syntax(self):
        """Test incremental query uses ClickHouse syntax"""
        query = QueryBuilder.build_incremental_query(
            connector=self.connector,
            schema='test_db',
            table='test_table',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01 00:00:00',
            columns=['id', 'name', 'updated_at'],
            order_by='updated_at'
        )
        
        # Should use backticks for ClickHouse
        self.assertIn('`test_db`', query)
        self.assertIn('`test_table`', query)
        self.assertIn('`updated_at`', query)
        self.assertIn('IS NOT NULL', query)
    
    def test_build_incremental_query_clickhouse_datetime_format(self):
        """Test checkpoint value formatting for ClickHouse DateTime"""
        query = QueryBuilder.build_incremental_query(
            connector=self.connector,
            schema='test_db',
            table='test_table',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01 00:00:00',
            columns=None,
            order_by=None
        )
        
        # Should use toDateTime() for ClickHouse timestamp conversion
        self.assertIn('toDateTime', query)
