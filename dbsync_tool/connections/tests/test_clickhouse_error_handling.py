"""
Tests for ClickHouse error handling (Day 6)
Tests comprehensive error handling for ClickHouse connector
"""
from django.test import TestCase
from unittest.mock import Mock, patch, MagicMock
from connections.connectors.clickhouse import ClickHouseConnector
from core.exceptions import (
    DatabaseConnectionError,
    DatabaseTimeoutError,
    DatabaseException,
    DatabaseQueryError,
    TableNotFoundError
)
import os


class ClickHouseErrorHandlingTests(TestCase):
    """Test ClickHouse error handling"""
    
    def setUp(self):
        """Set up test connector"""
        self.connector = ClickHouseConnector(
            host='localhost',
            port=9000,
            username='default',
            password='test',
            database_name='test_db'
        )
    
    def test_connection_timeout_error(self):
        """Test connection timeout error handling"""
        with patch('clickhouse_connect.get_client') as mock_client:
            mock_client.side_effect = Exception("Connection timeout: timed out")
            
            with self.assertRaises(DatabaseTimeoutError) as context:
                self.connector.connect()
            
            self.assertIn("Connection timeout", str(context.exception))
            self.assertIn("Unable to reach ClickHouse server", str(context.exception))
    
    def test_authentication_error(self):
        """Test authentication error handling"""
        with patch('clickhouse_connect.get_client') as mock_client:
            mock_client.side_effect = Exception("Authentication failed: invalid password")
            
            with self.assertRaises(DatabaseConnectionError) as context:
                self.connector.connect()
            
            self.assertIn("Invalid credentials", str(context.exception))
    
    def test_connection_refused_error(self):
        """Test connection refused error handling"""
        with patch('clickhouse_connect.get_client') as mock_client:
            mock_client.side_effect = Exception("Connection refused: could not connect")
            
            with self.assertRaises(DatabaseConnectionError) as context:
                self.connector.connect()
            
            self.assertIn("Host unreachable", str(context.exception))
    
    def test_database_not_found_error(self):
        """Test database not found error handling"""
        with patch('clickhouse_connect.get_client') as mock_client:
            mock_client.side_effect = Exception("Database 'test_db' does not exist")
            
            with self.assertRaises(DatabaseConnectionError) as context:
                self.connector.connect()
            
            self.assertIn("Database 'test_db' not found", str(context.exception))
    
    def test_disk_full_error(self):
        """Test disk full error handling"""
        with patch('clickhouse_connect.get_client') as mock_client:
            mock_client.side_effect = Exception("Disk is full: no space left")
            
            with self.assertRaises(DatabaseException) as context:
                self.connector.connect()
            
            self.assertIn("disk is full", str(context.exception).lower())
    
    def test_memory_limit_error(self):
        """Test memory limit error handling"""
        with patch('clickhouse_connect.get_client') as mock_client:
            mock_client.side_effect = Exception("Memory limit exceeded")
            
            with self.assertRaises(DatabaseException) as context:
                self.connector.connect()
            
            self.assertIn("memory limit", str(context.exception).lower())
    
    def test_get_tables_database_not_found(self):
        """Test get_tables with database not found"""
        mock_conn = MagicMock()
        mock_conn.query.side_effect = Exception("Database 'test_db' does not exist")
        self.connector._connection = mock_conn
        
        with self.assertRaises(DatabaseConnectionError) as context:
            self.connector.get_tables('test_db')
        
        self.assertIn("Database 'test_db' does not exist", str(context.exception))
    
    def test_execute_query_syntax_error(self):
        """Test execute_query with syntax error"""
        mock_conn = MagicMock()
        mock_conn.command.side_effect = Exception("Syntax error: unexpected token")
        self.connector._connection = mock_conn
        
        with self.assertRaises(DatabaseQueryError) as context:
            self.connector.execute_query("INVALID SQL QUERY")
        
        self.assertIn("Invalid ClickHouse query syntax", str(context.exception))
    
    def test_execute_query_table_not_found(self):
        """Test execute_query with table not found"""
        mock_conn = MagicMock()
        mock_conn.command.side_effect = Exception("Table 'test_table' does not exist")
        self.connector._connection = mock_conn
        
        with self.assertRaises(TableNotFoundError) as context:
            self.connector.execute_query("SELECT * FROM test_table")
        
        self.assertIn("Table not found", str(context.exception))
    
    def test_execute_query_timeout(self):
        """Test execute_query with timeout"""
        mock_conn = MagicMock()
        mock_conn.command.side_effect = Exception("Query timeout: exceeded time limit")
        self.connector._connection = mock_conn
        
        with self.assertRaises(DatabaseTimeoutError) as context:
            self.connector.execute_query("SELECT * FROM large_table")
        
        self.assertIn("Query timeout", str(context.exception))
    
    def test_bulk_insert_table_not_found(self):
        """Test bulk_insert with table not found"""
        mock_conn = MagicMock()
        mock_conn.insert.side_effect = Exception("Table 'test_table' does not exist")
        self.connector._connection = mock_conn
        
        with self.assertRaises(TableNotFoundError) as context:
            self.connector.bulk_insert('test_db', 'test_table', ['col1'], [(1,)])
        
        self.assertIn("Table test_db.test_table does not exist", str(context.exception))
    
    def test_bulk_insert_type_mismatch(self):
        """Test bulk_insert with type mismatch"""
        mock_conn = MagicMock()
        mock_conn.insert.side_effect = Exception("Type mismatch: cannot convert string to int")
        self.connector._connection = mock_conn
        
        with self.assertRaises(DatabaseQueryError) as context:
            self.connector.bulk_insert('test_db', 'test_table', ['col1'], [('string',)])
        
        self.assertIn("Data type mismatch", str(context.exception))
    
    def test_bulk_insert_memory_limit(self):
        """Test bulk_insert with memory limit"""
        mock_conn = MagicMock()
        mock_conn.insert.side_effect = Exception("Memory limit exceeded during insert")
        self.connector._connection = mock_conn
        
        with self.assertRaises(DatabaseException) as context:
            self.connector.bulk_insert('test_db', 'test_table', ['col1'], [(1,)] * 1000000)
        
        self.assertIn("memory limit", str(context.exception).lower())
    
    def test_bulk_insert_disk_full(self):
        """Test bulk_insert with disk full"""
        mock_conn = MagicMock()
        mock_conn.insert.side_effect = Exception("Disk is full: cannot write")
        self.connector._connection = mock_conn
        
        with self.assertRaises(DatabaseException) as context:
            self.connector.bulk_insert('test_db', 'test_table', ['col1'], [(1,)])
        
        self.assertIn("disk is full", str(context.exception).lower())
