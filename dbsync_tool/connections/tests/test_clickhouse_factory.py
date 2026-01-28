"""
Tests for ClickHouse factory functions and integration
"""
from django.test import TestCase
from connections.connectors import get_connector as get_connector_init
from connections.connectors.factory import get_connector
from connections.connectors.clickhouse import ClickHouseConnector
from core.exceptions import InvalidDatabaseTypeError
from core.constants import DB_TYPES, DEFAULT_PORTS
import os


class ClickHouseFactoryTests(TestCase):
    """Test cases for ClickHouse factory functions"""
    
    def test_clickhouse_in_constants(self):
        """Test that ClickHouse is in DB_TYPES and DEFAULT_PORTS"""
        db_type_values = [t[0] for t in DB_TYPES]
        self.assertIn('clickhouse', db_type_values)
        self.assertIn('clickhouse', DEFAULT_PORTS)
        self.assertEqual(DEFAULT_PORTS['clickhouse'], 9000)
    
    def test_factory_import_clickhouse(self):
        """Test that ClickHouse connector can be imported"""
        try:
            from connections.connectors.clickhouse import ClickHouseConnector
            self.assertIsNotNone(ClickHouseConnector)
        except ImportError as e:
            self.fail(f"ClickHouse connector import failed: {e}")
    
    def test_get_connector_init_with_clickhouse(self):
        """Test get_connector from __init__.py with ClickHouse"""
        try:
            connector = get_connector_init(
                db_type='clickhouse',
                host='localhost',
                port=9000,
                username='default',
                password='',
                database_name='default'
            )
            self.assertIsInstance(connector, ClickHouseConnector)
        except InvalidDatabaseTypeError as e:
            # If clickhouse-connect is not installed, this is expected
            if 'not available' in str(e):
                self.skipTest("ClickHouse connector not available (clickhouse-connect not installed)")
            else:
                raise
    
    def test_get_connector_init_invalid_type(self):
        """Test get_connector with invalid database type"""
        with self.assertRaises(InvalidDatabaseTypeError):
            get_connector_init(
                db_type='invalid_db',
                host='localhost',
                port=9000,
                username='user',
                password='pass',
                database_name='test'
            )
    
    def test_clickhouse_connector_initialization(self):
        """Test ClickHouse connector can be initialized"""
        try:
            connector = ClickHouseConnector(
                host='localhost',
                port=9000,
                username='default',
                password='',
                database_name='default'
            )
            self.assertIsNotNone(connector)
            self.assertEqual(connector.host, 'localhost')
            self.assertEqual(connector.port, 9000)
            self.assertEqual(connector.username, 'default')
            self.assertEqual(connector.database_name, 'default')
        except Exception as e:
            self.fail(f"ClickHouse connector initialization failed: {e}")
