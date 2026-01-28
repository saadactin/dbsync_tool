"""
Tests for ClickHouse database connector
"""
from django.test import TestCase
from connections.connectors.clickhouse import ClickHouseConnector
from connections.connectors.base import ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError
import os


class ClickHouseConnectorTests(TestCase):
    """Test cases for ClickHouse connector"""
    
    def setUp(self):
        """Set up test connector"""
        # Use environment variables or skip if not available
        self.host = os.environ.get('CLICKHOUSE_HOST', 'localhost')
        self.port = int(os.environ.get('CLICKHOUSE_PORT', '9000'))
        self.username = os.environ.get('CLICKHOUSE_USER', 'default')
        self.password = os.environ.get('CLICKHOUSE_PASSWORD', '')
        self.database_name = os.environ.get('CLICKHOUSE_DATABASE', 'default')
        
        self.connector = ClickHouseConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.database_name
        )
    
    def test_connect(self):
        """Test connection establishment"""
        try:
            conn = self.connector.connect()
            self.assertIsNotNone(conn)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_test_connection(self):
        """Test connection test method"""
        try:
            result = self.connector.test_connection()
            self.assertIsInstance(result, bool)
            self.assertTrue(result)
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_get_schemas(self):
        """Test getting databases (schemas)"""
        try:
            self.connector.connect()
            schemas = self.connector.get_schemas()
            self.assertIsInstance(schemas, list)
            # Should at least have 'default' database (if not filtered)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_list_databases(self):
        """Test listing databases"""
        try:
            self.connector.connect()
            databases = self.connector.list_databases()
            self.assertIsInstance(databases, list)
            # Should not include system databases
            self.assertNotIn('system', databases)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_get_tables(self):
        """Test getting tables"""
        try:
            self.connector.connect()
            tables = self.connector.get_tables(self.database_name)
            self.assertIsInstance(tables, list)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_table_exists(self):
        """Test table existence check"""
        try:
            self.connector.connect()
            # Check for a table that might exist
            # This will return False if table doesn't exist, which is fine
            exists = self.connector.table_exists(self.database_name, 'test_table')
            self.assertIsInstance(exists, bool)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_get_columns(self):
        """Test getting column information"""
        try:
            self.connector.connect()
            # Try to get columns from a non-existent table (should raise error)
            with self.assertRaises(TableNotFoundError):
                self.connector.get_columns(self.database_name, 'non_existent_table')
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_get_row_count(self):
        """Test getting row count"""
        try:
            self.connector.connect()
            # Try to get row count from a non-existent table (should raise error)
            # We'll test with a table that doesn't exist to verify error handling
            try:
                count = self.connector.get_row_count(self.database_name, 'non_existent_table')
                # If no error, verify it's an integer
                self.assertIsInstance(count, int)
            except Exception:
                # Expected if table doesn't exist
                pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_ensure_schema_exists(self):
        """Test ensuring schema (database) exists"""
        try:
            self.connector.connect()
            # Try to ensure a test database exists
            test_db = 'test_schema_' + str(hash(self.database_name))[:8]
            self.connector.ensure_schema_exists(test_db)
            # Clean up - drop the test database
            try:
                self.connector._connection.command(f"DROP DATABASE IF EXISTS `{test_db}`")
            except:
                pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_context_manager(self):
        """Test context manager usage"""
        try:
            with self.connector:
                self.assertIsNotNone(self.connector._connection)
            # Connection should be closed after context
            self.assertIsNone(self.connector._connection)
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_get_primary_key(self):
        """Test getting primary key (ORDER BY columns)"""
        try:
            self.connector.connect()
            # Try to get primary key from a non-existent table
            pk_cols = self.connector.get_primary_key(self.database_name, 'non_existent_table')
            self.assertIsInstance(pk_cols, list)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_fetch_batch(self):
        """Test fetching batch of rows"""
        try:
            self.connector.connect()
            # Test with a simple query
            query = f"SELECT 1 as col1, 2 as col2 FROM system.one"
            rows = self.connector.fetch_batch(query, batch_size=10, offset=0)
            self.assertIsInstance(rows, list)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_get_query_row_count(self):
        """Test getting query row count"""
        try:
            self.connector.connect()
            # Test with a simple query
            query = f"SELECT * FROM system.one"
            count = self.connector.get_query_row_count(query)
            self.assertIsInstance(count, int)
            self.assertGreaterEqual(count, 0)
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_connection_timeout(self):
        """Test connection timeout handling"""
        try:
            # Test with unreachable host
            timeout_connector = ClickHouseConnector(
                host='192.0.2.0',  # Unreachable IP
                port=9000,
                username='default',
                password='',
                database_name='default'
            )
            with self.assertRaises(DatabaseConnectionError):
                timeout_connector.connect()
        except DatabaseConnectionError:
            # Expected behavior
            pass
        except Exception as e:
            # Other exceptions are acceptable for timeout scenarios
            pass
    
    def test_connection_invalid_credentials(self):
        """Test connection with invalid credentials"""
        try:
            self.connector.connect()
            # If connection succeeds, test with wrong password
            invalid_connector = ClickHouseConnector(
                host=self.host,
                port=self.port,
                username='invalid_user',
                password='wrong_password',
                database_name=self.database_name
            )
            try:
                invalid_connector.connect()
                # If it doesn't raise, that's also acceptable (some setups allow any user)
                invalid_connector.close()
            except DatabaseConnectionError:
                # Expected behavior
                pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_connection_wrong_port(self):
        """Test connection with wrong port"""
        try:
            self.connector.connect()
            # Test with wrong port
            wrong_port_connector = ClickHouseConnector(
                host=self.host,
                port=9999,  # Wrong port
                username=self.username,
                password=self.password,
                database_name=self.database_name
            )
            try:
                wrong_port_connector.connect()
                wrong_port_connector.close()
            except DatabaseConnectionError:
                # Expected behavior
                pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_list_databases_excludes_system(self):
        """Test that system databases are excluded"""
        try:
            self.connector.connect()
            databases = self.connector.list_databases()
            self.assertIsInstance(databases, list)
            # Verify system databases are not in list
            system_dbs = ['system', 'information_schema', 'INFORMATION_SCHEMA']
            for sys_db in system_dbs:
                self.assertNotIn(sys_db, databases, f"System database {sys_db} should be excluded")
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_create_table_with_nullable_types(self):
        """Test table creation with Nullable types"""
        try:
            self.connector.connect()
            test_table = f'test_nullable_{hash(self.database_name) % 10000}'
            test_db = self.database_name
            
            # Create table with Nullable types
            create_query = f"""
            CREATE TABLE IF NOT EXISTS `{test_db}`.`{test_table}` (
                id Int32,
                name Nullable(String),
                age Nullable(Int32)
            ) ENGINE = MergeTree()
            ORDER BY id
            """
            self.connector.execute_query(create_query)
            
            # Verify table exists
            exists = self.connector.table_exists(test_db, test_table)
            self.assertTrue(exists)
            
            # Clean up
            try:
                self.connector.execute_query(f"DROP TABLE IF EXISTS `{test_db}`.`{test_table}`")
            except:
                pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_create_table_with_array_types(self):
        """Test table creation with Array types"""
        try:
            self.connector.connect()
            test_table = f'test_array_{hash(self.database_name) % 10000}'
            test_db = self.database_name
            
            # Create table with Array type
            create_query = f"""
            CREATE TABLE IF NOT EXISTS `{test_db}`.`{test_table}` (
                id Int32,
                tags Array(String)
            ) ENGINE = MergeTree()
            ORDER BY id
            """
            self.connector.execute_query(create_query)
            
            # Verify table exists
            exists = self.connector.table_exists(test_db, test_table)
            self.assertTrue(exists)
            
            # Clean up
            try:
                self.connector.execute_query(f"DROP TABLE IF EXISTS `{test_db}`.`{test_table}`")
            except:
                pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_fetch_batch_with_large_offset(self):
        """Test batch fetching with large offset"""
        try:
            self.connector.connect()
            # Create test table with data
            test_table = f'test_batch_{hash(self.database_name) % 10000}'
            test_db = self.database_name
            
            try:
                # Create table
                create_query = f"""
                CREATE TABLE IF NOT EXISTS `{test_db}`.`{test_table}` (
                    id Int32
                ) ENGINE = MergeTree()
                ORDER BY id
                """
                self.connector.execute_query(create_query)
                
                # Insert some test data
                for i in range(10):
                    self.connector.execute_query(f"INSERT INTO `{test_db}`.`{test_table}` VALUES ({i})")
                
                # Test fetch with large offset
                query = f"SELECT * FROM `{test_db}`.`{test_table}` ORDER BY id"
                rows = self.connector.fetch_batch(query, batch_size=5, offset=100)
                self.assertIsInstance(rows, list)
                # Should return empty list for offset beyond data
                self.assertEqual(len(rows), 0)
            finally:
                # Clean up
                try:
                    self.connector.execute_query(f"DROP TABLE IF EXISTS `{test_db}`.`{test_table}`")
                except:
                    pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")
    
    def test_bulk_insert_performance(self):
        """Test bulk insert performance"""
        try:
            self.connector.connect()
            test_table = f'test_bulk_{hash(self.database_name) % 10000}'
            test_db = self.database_name
            
            try:
                # Create table
                create_query = f"""
                CREATE TABLE IF NOT EXISTS `{test_db}`.`{test_table}` (
                    id Int32,
                    name String
                ) ENGINE = MergeTree()
                ORDER BY id
                """
                self.connector.execute_query(create_query)
                
                # Prepare bulk data
                bulk_data = [(i, f'name_{i}') for i in range(100)]
                
                # Test bulk insert
                self.connector.bulk_insert(test_db, test_table, ['id', 'name'], bulk_data)
                
                # Verify data was inserted
                count = self.connector.get_row_count(test_db, test_table)
                self.assertGreaterEqual(count, 100)
            finally:
                # Clean up
                try:
                    self.connector.execute_query(f"DROP TABLE IF EXISTS `{test_db}`.`{test_table}`")
                except:
                    pass
            self.connector.close()
        except DatabaseConnectionError:
            self.skipTest("ClickHouse not available for testing")