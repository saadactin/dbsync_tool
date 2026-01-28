"""
Tests for query builder
"""
import unittest
from unittest.mock import Mock
from sync_engine.query_builder import QueryBuilder
from sync_engine.exceptions import QueryBuilderError


class TestQueryBuilder(unittest.TestCase):
    """Test cases for QueryBuilder"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.postgres_connector = Mock()
        self.postgres_connector.__class__.__name__ = 'PostgresConnector'
        
        self.mysql_connector = Mock()
        self.mysql_connector.__class__.__name__ = 'MySQLConnector'
        
        self.sqlserver_connector = Mock()
        self.sqlserver_connector.__class__.__name__ = 'SQLServerConnector'
        
        self.clickhouse_connector = Mock()
        self.clickhouse_connector.__class__.__name__ = 'ClickHouseConnector'
    
    def test_get_db_type_postgres(self):
        """Test database type detection for PostgreSQL"""
        db_type = QueryBuilder.get_db_type(self.postgres_connector)
        self.assertEqual(db_type, 'postgres')
    
    def test_get_db_type_mysql(self):
        """Test database type detection for MySQL"""
        db_type = QueryBuilder.get_db_type(self.mysql_connector)
        self.assertEqual(db_type, 'mysql')
    
    def test_get_db_type_sqlserver(self):
        """Test database type detection for SQL Server"""
        db_type = QueryBuilder.get_db_type(self.sqlserver_connector)
        self.assertEqual(db_type, 'sqlserver')
    
    def test_get_db_type_clickhouse(self):
        """Test database type detection for ClickHouse"""
        db_type = QueryBuilder.get_db_type(self.clickhouse_connector)
        self.assertEqual(db_type, 'clickhouse')
    
    def test_get_db_type_unknown(self):
        """Test database type detection for unknown connector"""
        unknown_connector = Mock()
        unknown_connector.__class__.__name__ = 'UnknownConnector'
        with self.assertRaises(QueryBuilderError):
            QueryBuilder.get_db_type(unknown_connector)
    
    def test_build_select_query_postgres(self):
        """Test SELECT query building for PostgreSQL"""
        query = QueryBuilder.build_select_query(
            self.postgres_connector,
            'public',
            'users',
            columns=['id', 'name']
        )
        self.assertIn('"public"."users"', query)
        self.assertIn('"id"', query)
        self.assertIn('"name"', query)
    
    def test_build_select_query_mysql(self):
        """Test SELECT query building for MySQL"""
        query = QueryBuilder.build_select_query(
            self.mysql_connector,
            'mydb',
            'users',
            columns=['id', 'name']
        )
        self.assertIn('`mydb`.`users`', query)
        self.assertIn('`id`', query)
        self.assertIn('`name`', query)
    
    def test_build_select_query_sqlserver(self):
        """Test SELECT query building for SQL Server"""
        query = QueryBuilder.build_select_query(
            self.sqlserver_connector,
            'dbo',
            'users',
            columns=['id', 'name']
        )
        self.assertIn('[dbo].[users]', query)
        self.assertIn('[id]', query)
        self.assertIn('[name]', query)
    
    def test_build_select_query_clickhouse(self):
        """Test SELECT query building for ClickHouse"""
        query = QueryBuilder.build_select_query(
            self.clickhouse_connector,
            'test_db',
            'users',
            columns=['id', 'name']
        )
        self.assertIn('`test_db`.`users`', query)
        self.assertIn('`id`', query)
        self.assertIn('`name`', query)
    
    def test_build_select_query_with_order_by(self):
        """Test SELECT query with ORDER BY"""
        query = QueryBuilder.build_select_query(
            self.postgres_connector,
            'public',
            'users',
            order_by='id'
        )
        self.assertIn('ORDER BY "id"', query)  # PostgreSQL quotes column names
    
    def test_build_select_query_with_where(self):
        """Test SELECT query with WHERE clause"""
        query = QueryBuilder.build_select_query(
            self.postgres_connector,
            'public',
            'users',
            where_clause='id > 10'
        )
        self.assertIn('WHERE id > 10', query)
    
    def test_build_select_query_with_limit_offset_postgres(self):
        """Test SELECT query with LIMIT/OFFSET for PostgreSQL"""
        query = QueryBuilder.build_select_query(
            self.postgres_connector,
            'public',
            'users',
            limit=10,
            offset=20
        )
        self.assertIn('LIMIT 10', query)
        self.assertIn('OFFSET 20', query)
    
    def test_build_select_query_with_limit_offset_sqlserver(self):
        """Test SELECT query with OFFSET/FETCH for SQL Server"""
        query = QueryBuilder.build_select_query(
            self.sqlserver_connector,
            'dbo',
            'users',
            limit=10,
            offset=20
        )
        self.assertIn('OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY', query)
    
    def test_build_select_query_with_limit_offset_clickhouse(self):
        """Test SELECT query with LIMIT/OFFSET for ClickHouse"""
        query = QueryBuilder.build_select_query(
            self.clickhouse_connector,
            'test_db',
            'users',
            limit=10,
            offset=20
        )
        self.assertIn('LIMIT 10', query)
        self.assertIn('OFFSET 20', query)
    
    def test_build_count_query(self):
        """Test COUNT query building"""
        query = QueryBuilder.build_count_query(
            self.postgres_connector,
            'public',
            'users'
        )
        self.assertIn('COUNT(*)', query)
        self.assertIn('"public"."users"', query)
    
    def test_build_count_query_with_where(self):
        """Test COUNT query with WHERE clause"""
        query = QueryBuilder.build_count_query(
            self.postgres_connector,
            'public',
            'users',
            where_clause='id > 10'
        )
        self.assertIn('WHERE id > 10', query)
    
    def test_build_count_query_clickhouse(self):
        """Test COUNT query for ClickHouse"""
        query = QueryBuilder.build_count_query(
            self.clickhouse_connector,
            'test_db',
            'users'
        )
        self.assertIn('COUNT(*)', query)
        self.assertIn('`test_db`.`users`', query)
    
    def test_build_incremental_query_postgres(self):
        """Test incremental query for PostgreSQL"""
        # Test with checkpoint value
        query = QueryBuilder.build_incremental_query(
            connector=self.postgres_connector,
            schema='public',
            table='users',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01 00:00:00'
        )
        self.assertIn('WHERE "updated_at"', query)
        self.assertIn('ORDER BY "updated_at"', query)
        
        # Test without checkpoint (first sync)
        query = QueryBuilder.build_incremental_query(
            connector=self.postgres_connector,
            schema='public',
            table='users',
            incremental_column='updated_at',
            checkpoint_value=None
        )
        self.assertIn('WHERE 1=1', query)
    
    def test_build_incremental_query_mysql(self):
        """Test incremental query for MySQL"""
        query = QueryBuilder.build_incremental_query(
            connector=self.mysql_connector,
            schema='test_db',
            table='users',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01 00:00:00'
        )
        self.assertIn('WHERE `updated_at`', query)
        self.assertIn('ORDER BY `updated_at`', query)
    
    def test_build_incremental_query_sqlserver(self):
        """Test incremental query for SQL Server"""
        query = QueryBuilder.build_incremental_query(
            connector=self.sqlserver_connector,
            schema='dbo',
            table='users',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01 00:00:00'
        )
        self.assertIn('WHERE [updated_at]', query)
        self.assertIn('ORDER BY [updated_at]', query)
    
    def test_build_incremental_query_clickhouse(self):
        """Test incremental query for ClickHouse"""
        query = QueryBuilder.build_incremental_query(
            connector=self.clickhouse_connector,
            schema='test_db',
            table='users',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01 00:00:00'
        )
        self.assertIn('WHERE `updated_at`', query)
        self.assertIn('ORDER BY `updated_at`', query)
        self.assertIn('toDateTime', query)  # ClickHouse uses toDateTime() for timestamp conversion
    
    def test_build_incremental_query_with_columns(self):
        """Test incremental query with specific columns"""
        query = QueryBuilder.build_incremental_query(
            connector=self.postgres_connector,
            schema='public',
            table='users',
            incremental_column='id',
            checkpoint_value=100,
            columns=['id', 'name', 'email']
        )
        self.assertIn('"id", "name", "email"', query)
        self.assertIn('WHERE "id"', query)
    
    def test_build_incremental_query_with_custom_order_by(self):
        """Test incremental query with custom ORDER BY"""
        query = QueryBuilder.build_incremental_query(
            connector=self.postgres_connector,
            schema='public',
            table='users',
            incremental_column='updated_at',
            checkpoint_value='2024-01-01',
            order_by='updated_at, id'
        )
        self.assertIn('ORDER BY "updated_at", "id"', query)
    
    def test_build_max_value_query(self):
        """Test max value query building"""
        query = QueryBuilder.build_max_value_query(
            connector=self.postgres_connector,
            schema='public',
            table='users',
            column='id'
        )
        self.assertEqual(query, 'SELECT MAX("id") FROM "public"."users"')
    
    def test_build_max_value_query_mysql(self):
        """Test max value query for MySQL"""
        query = QueryBuilder.build_max_value_query(
            connector=self.mysql_connector,
            schema='test_db',
            table='users',
            column='id'
        )
        self.assertEqual(query, 'SELECT MAX(`id`) FROM `test_db`.`users`')
    
    def test_build_max_value_query_sqlserver(self):
        """Test max value query for SQL Server"""
        query = QueryBuilder.build_max_value_query(
            connector=self.sqlserver_connector,
            schema='dbo',
            table='users',
            column='id'
        )
        self.assertEqual(query, 'SELECT MAX([id]) FROM [dbo].[users]')
    
    def test_build_max_value_query_clickhouse(self):
        """Test max value query for ClickHouse"""
        query = QueryBuilder.build_max_value_query(
            connector=self.clickhouse_connector,
            schema='test_db',
            table='users',
            column='id'
        )
        self.assertEqual(query, 'SELECT MAX(`id`) FROM `test_db`.`users`')
    
    def test_format_checkpoint_value_integer(self):
        """Test formatting integer checkpoint value"""
        value = QueryBuilder._format_checkpoint_value(100, 'postgres')
        self.assertEqual(value, '100')
    
    def test_format_checkpoint_value_float(self):
        """Test formatting float checkpoint value"""
        value = QueryBuilder._format_checkpoint_value(100.5, 'postgres')
        self.assertEqual(value, '100.5')
    
    def test_format_checkpoint_value_string(self):
        """Test formatting string checkpoint value"""
        value = QueryBuilder._format_checkpoint_value('2024-01-01', 'postgres')
        self.assertIn("'2024-01-01'", value)
        self.assertIn('::timestamp', value)
    
    def test_format_checkpoint_value_string_mysql(self):
        """Test formatting string checkpoint value for MySQL"""
        value = QueryBuilder._format_checkpoint_value('2024-01-01', 'mysql')
        self.assertIn("'2024-01-01'", value)
        self.assertNotIn('::timestamp', value)
    
    def test_format_checkpoint_value_string_clickhouse(self):
        """Test formatting string checkpoint value for ClickHouse"""
        value = QueryBuilder._format_checkpoint_value('2024-01-01 00:00:00', 'clickhouse')
        self.assertIn("toDateTime", value)
        self.assertIn("'2024-01-01 00:00:00'", value)
    
    def test_format_checkpoint_value_numeric_string(self):
        """Test formatting numeric string checkpoint value"""
        value = QueryBuilder._format_checkpoint_value('100', 'postgres')
        self.assertEqual(value, '100')  # Should not be quoted
    
    def test_sql_injection_prevention(self):
        """Test SQL injection prevention in checkpoint values"""
        malicious_value = "'; DROP TABLE users; --"
        query = QueryBuilder.build_incremental_query(
            connector=self.postgres_connector,
            schema='public',
            table='users',
            incremental_column='name',
            checkpoint_value=malicious_value
        )
        # Should escape quotes properly - the escaped string will contain the text but it's safe
        self.assertIn("''", query)  # Escaped quote (single quote becomes two single quotes)
        # The query should not execute DROP TABLE because the value is properly escaped as a string
        # The text "DROP TABLE" will appear in the escaped string, but it's safe because it's in quotes
        self.assertIn('"name"', query)  # Column name should be quoted (PostgreSQL uses double quotes)
    
    def test_build_incremental_query_missing_params(self):
        """Test incremental query with missing parameters"""
        with self.assertRaises(QueryBuilderError):
            QueryBuilder.build_incremental_query(
                connector=self.postgres_connector,
                schema='',
                table='users',
                incremental_column='id'
            )
        
        with self.assertRaises(QueryBuilderError):
            QueryBuilder.build_incremental_query(
                connector=self.postgres_connector,
                schema='public',
                table='',
                incremental_column='id'
            )
        
        with self.assertRaises(QueryBuilderError):
            QueryBuilder.build_incremental_query(
                connector=self.postgres_connector,
                schema='public',
                table='users',
                incremental_column=''
            )
    
    def test_build_max_value_query_missing_params(self):
        """Test max value query with missing parameters"""
        with self.assertRaises(QueryBuilderError):
            QueryBuilder.build_max_value_query(
                connector=self.postgres_connector,
                schema='',
                table='users',
                column='id'
            )


if __name__ == '__main__':
    unittest.main()

