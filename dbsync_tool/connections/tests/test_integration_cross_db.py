"""
Integration tests for cross-database type mapping and table creation
These tests require actual database connections and should be run with test databases
"""
import unittest
import os
from connections.connectors.postgres import PostgresConnector
from connections.connectors.mysql import MySQLConnector
from connections.connectors.sqlserver import SQLServerConnector
from connections.connectors.base import ColumnInfo
from core.exceptions import DatabaseConnectionError


class TestIntegrationCrossDB(unittest.TestCase):
    """
    Integration tests for all 9 database combinations
    These tests require actual database connections
    Set environment variables or modify connection parameters for your test databases
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up test database connections"""
        # These should be configured for your test environment
        # For now, we'll skip tests if connections aren't available
        cls.skip_tests = os.environ.get('SKIP_INTEGRATION_TESTS', 'False').lower() == 'true'
        
        if not cls.skip_tests:
            try:
                # PostgreSQL test connection
                cls.pg_conn = PostgresConnector(
                    host=os.environ.get('TEST_PG_HOST', 'localhost'),
                    port=int(os.environ.get('TEST_PG_PORT', 5432)),
                    username=os.environ.get('TEST_PG_USER', 'test'),
                    password=os.environ.get('TEST_PG_PASS', 'test'),
                    database_name=os.environ.get('TEST_PG_DB', 'test')
                )
                
                # MySQL test connection
                cls.mysql_conn = MySQLConnector(
                    host=os.environ.get('TEST_MYSQL_HOST', 'localhost'),
                    port=int(os.environ.get('TEST_MYSQL_PORT', 3306)),
                    username=os.environ.get('TEST_MYSQL_USER', 'test'),
                    password=os.environ.get('TEST_MYSQL_PASS', 'test'),
                    database_name=os.environ.get('TEST_MYSQL_DB', 'test')
                )
                
                # SQL Server test connection
                cls.sqlserver_conn = SQLServerConnector(
                    host=os.environ.get('TEST_SQLSERVER_HOST', 'localhost'),
                    port=int(os.environ.get('TEST_SQLSERVER_PORT', 1433)),
                    username=os.environ.get('TEST_SQLSERVER_USER', 'test'),
                    password=os.environ.get('TEST_SQLSERVER_PASS', 'test'),
                    database_name=os.environ.get('TEST_SQLSERVER_DB', 'test')
                )

                # Proactively verify connectivity; if any required DB is not reachable,
                # skip integration tests rather than failing the whole suite.
                try:
                    cls.pg_conn.connect()
                    cls.pg_conn.close()
                    cls.mysql_conn.connect()
                    cls.mysql_conn.close()
                    cls.sqlserver_conn.connect()
                    cls.sqlserver_conn.close()
                except (DatabaseConnectionError, Exception) as e:
                    print(f"Warning: Integration DB(s) not available, skipping integration tests: {e}")
                    cls.skip_tests = True
            except Exception as e:
                print(f"Warning: Could not set up test connections: {e}")
                cls.skip_tests = True
    
    def setUp(self):
        """Set up for each test"""
        if self.skip_tests:
            self.skipTest("Integration tests skipped (set SKIP_INTEGRATION_TESTS=false to enable)")
    
    def test_postgres_to_postgres(self):
        """Test PostgreSQL to PostgreSQL table creation"""
        schema = 'test_schema'
        table = 'test_table_pg_to_pg'
        
        columns = [
            ColumnInfo('id', 'int4', False, True),
            ColumnInfo('name', 'varchar', True, False, max_length=255),
            ColumnInfo('created_at', 'timestamp', False, False),
        ]
        
        try:
            self.pg_conn.connect()
            self.pg_conn.create_table(schema, table, columns, target_db_type='postgres')
            self.assertTrue(self.pg_conn.table_exists(schema, table))
        finally:
            # Cleanup
            if self.pg_conn._connection:
                try:
                    with self.pg_conn._connection.cursor() as cursor:
                        cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
                        self.pg_conn._connection.commit()
                except:
                    pass
                self.pg_conn.close()
    
    def test_postgres_to_mysql(self):
        """Test PostgreSQL to MySQL table creation"""
        schema = 'test_db'
        table = 'test_table_pg_to_mysql'
        
        columns = [
            ColumnInfo('id', 'int4', False, True),
            ColumnInfo('name', 'varchar', True, False, max_length=255),
        ]
        
        try:
            self.mysql_conn.connect()
            self.mysql_conn.create_table(schema, table, columns, target_db_type='mysql')
            self.assertTrue(self.mysql_conn.table_exists(schema, table))
        finally:
            # Cleanup
            if self.mysql_conn._connection:
                try:
                    cursor = self.mysql_conn._connection.cursor()
                    cursor.execute(f"DROP TABLE IF EXISTS `{schema}`.`{table}`")
                    self.mysql_conn._connection.commit()
                    cursor.close()
                except:
                    pass
                self.mysql_conn.close()
    
    def test_postgres_to_sqlserver(self):
        """Test PostgreSQL to SQL Server table creation"""
        schema = 'test_schema'
        table = 'test_table_pg_to_sqlserver'
        
        columns = [
            ColumnInfo('id', 'int4', False, True),
            ColumnInfo('name', 'varchar', True, False, max_length=255),
        ]
        
        try:
            self.sqlserver_conn.connect()
            self.sqlserver_conn.create_table(schema, table, columns, target_db_type='sqlserver')
            self.assertTrue(self.sqlserver_conn.table_exists(schema, table))
        finally:
            # Cleanup
            if self.sqlserver_conn._connection:
                try:
                    cursor = self.sqlserver_conn._connection.cursor()
                    cursor.execute(f"DROP TABLE IF EXISTS [{schema}].[{table}]")
                    self.sqlserver_conn._connection.commit()
                    cursor.close()
                except:
                    pass
                self.sqlserver_conn.close()
    
    def test_primary_key_detection_postgres(self):
        """Test primary key detection in PostgreSQL"""
        schema = 'test_schema'
        table = 'test_pk_detection'
        
        columns = [
            ColumnInfo('id', 'int4', False, True),
            ColumnInfo('name', 'varchar', True, False, max_length=255),
        ]
        
        try:
            self.pg_conn.connect()
            self.pg_conn.create_table(schema, table, columns, target_db_type='postgres')
            
            # Add primary key constraint
            with self.pg_conn._connection.cursor() as cursor:
                cursor.execute(f"ALTER TABLE {schema}.{table} ADD PRIMARY KEY (id)")
                self.pg_conn._connection.commit()
            
            pk_columns = self.pg_conn.get_primary_key(schema, table)
            self.assertIn('id', pk_columns)
        finally:
            # Cleanup
            if self.pg_conn._connection:
                try:
                    with self.pg_conn._connection.cursor() as cursor:
                        cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
                        self.pg_conn._connection.commit()
                except:
                    pass
                self.pg_conn.close()
    
    def test_schema_creation_all_dbs(self):
        """Test schema creation for all database types"""
        test_schema = 'test_schema_creation'
        
        # PostgreSQL
        try:
            self.pg_conn.connect()
            self.pg_conn.ensure_schema_exists(test_schema)
            # Verify schema exists
            schemas = self.pg_conn.get_schemas()
            self.assertIn(test_schema, schemas)
        finally:
            if self.pg_conn._connection:
                self.pg_conn.close()
        
        # MySQL
        try:
            self.mysql_conn.connect()
            self.mysql_conn.ensure_schema_exists(test_schema)
            # Verify database exists
            schemas = self.mysql_conn.get_schemas()
            self.assertIn(test_schema, schemas)
        finally:
            if self.mysql_conn._connection:
                self.mysql_conn.close()
        
        # SQL Server
        try:
            self.sqlserver_conn.connect()
            self.sqlserver_conn.ensure_schema_exists(test_schema)
            # Verify schema exists
            schemas = self.sqlserver_conn.get_schemas()
            self.assertIn(test_schema, schemas)
        finally:
            if self.sqlserver_conn._connection:
                self.sqlserver_conn.close()
    
    def test_fetch_batch_with_ordering(self):
        """Test fetch_batch with ORDER BY clause"""
        schema = 'test_schema'
        table = 'test_fetch_batch'
        
        columns = [
            ColumnInfo('id', 'int4', False, True),
            ColumnInfo('value', 'varchar', True, False, max_length=100),
        ]
        
        try:
            self.pg_conn.connect()
            self.pg_conn.create_table(schema, table, columns, target_db_type='postgres')
            
            # Insert test data
            test_data = [(i, f'value_{i}') for i in range(1, 11)]
            self.pg_conn.bulk_insert(schema, table, ['id', 'value'], test_data)
            
            # Test fetch_batch with ordering
            query = f'SELECT * FROM {schema}.{table}'
            batch = self.pg_conn.fetch_batch(query, batch_size=5, offset=0, order_by='id')
            
            self.assertEqual(len(batch), 5)
            # Verify ordering
            ids = [row[0] for row in batch]
            self.assertEqual(ids, [1, 2, 3, 4, 5])
        finally:
            # Cleanup
            if self.pg_conn._connection:
                try:
                    with self.pg_conn._connection.cursor() as cursor:
                        cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
                        self.pg_conn._connection.commit()
                except:
                    pass
                self.pg_conn.close()
    
    def test_get_query_row_count(self):
        """Test get_query_row_count method"""
        schema = 'test_schema'
        table = 'test_row_count'
        
        columns = [
            ColumnInfo('id', 'int4', False, True),
        ]
        
        try:
            self.pg_conn.connect()
            self.pg_conn.create_table(schema, table, columns, target_db_type='postgres')
            
            # Insert test data
            test_data = [(i,) for i in range(1, 21)]
            self.pg_conn.bulk_insert(schema, table, ['id'], test_data)
            
            # Test row count
            query = f'SELECT * FROM {schema}.{table}'
            count = self.pg_conn.get_query_row_count(query)
            self.assertEqual(count, 20)
        finally:
            # Cleanup
            if self.pg_conn._connection:
                try:
                    with self.pg_conn._connection.cursor() as cursor:
                        cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
                        self.pg_conn._connection.commit()
                except:
                    pass
                self.pg_conn.close()


if __name__ == '__main__':
    unittest.main()

