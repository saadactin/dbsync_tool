"""
Comprehensive unit tests for type mapping system
"""
import unittest
from core.type_mapping import map_data_type, get_default_length, normalize_data_type


class TestTypeMapping(unittest.TestCase):
    """Test type mapping for all database combinations"""
    
    # PostgreSQL to MySQL tests
    def test_postgres_to_mysql_int(self):
        result = map_data_type('int4', 'postgres', 'mysql')
        self.assertEqual(result, 'INT')
    
    def test_postgres_to_mysql_bigint(self):
        result = map_data_type('bigint', 'postgres', 'mysql')
        self.assertEqual(result, 'BIGINT')
    
    def test_postgres_to_mysql_varchar_with_length(self):
        result = map_data_type('varchar', 'postgres', 'mysql', max_length=255)
        self.assertEqual(result, 'VARCHAR(255)')
    
    def test_postgres_to_mysql_text(self):
        result = map_data_type('text', 'postgres', 'mysql')
        self.assertEqual(result, 'TEXT')
    
    def test_postgres_to_mysql_timestamp(self):
        result = map_data_type('timestamp without time zone', 'postgres', 'mysql')
        self.assertEqual(result, 'DATETIME')
    
    def test_postgres_to_mysql_boolean(self):
        result = map_data_type('boolean', 'postgres', 'mysql')
        self.assertEqual(result, 'BOOLEAN')
    
    def test_postgres_to_mysql_uuid(self):
        result = map_data_type('uuid', 'postgres', 'mysql')
        self.assertEqual(result, 'CHAR(36)')
    
    # PostgreSQL to SQL Server tests
    def test_postgres_to_sqlserver_int(self):
        result = map_data_type('int4', 'postgres', 'sqlserver')
        self.assertEqual(result, 'INT')
    
    def test_postgres_to_sqlserver_varchar(self):
        result = map_data_type('varchar', 'postgres', 'sqlserver', max_length=255)
        self.assertEqual(result, 'NVARCHAR(255)')
    
    def test_postgres_to_sqlserver_text(self):
        result = map_data_type('text', 'postgres', 'sqlserver')
        self.assertEqual(result, 'NVARCHAR(MAX)')
    
    def test_postgres_to_sqlserver_boolean(self):
        result = map_data_type('boolean', 'postgres', 'sqlserver')
        self.assertEqual(result, 'BIT')
    
    def test_postgres_to_sqlserver_uuid(self):
        result = map_data_type('uuid', 'postgres', 'sqlserver')
        self.assertEqual(result, 'UNIQUEIDENTIFIER')
    
    # MySQL to PostgreSQL tests
    def test_mysql_to_postgres_int(self):
        result = map_data_type('INT', 'mysql', 'postgres')
        self.assertEqual(result, 'INTEGER')
    
    def test_mysql_to_postgres_varchar(self):
        result = map_data_type('VARCHAR', 'mysql', 'postgres', max_length=255)
        self.assertEqual(result, 'VARCHAR(255)')
    
    def test_mysql_to_postgres_datetime(self):
        result = map_data_type('DATETIME', 'mysql', 'postgres')
        self.assertEqual(result, 'TIMESTAMP')
    
    def test_mysql_to_postgres_json(self):
        result = map_data_type('JSON', 'mysql', 'postgres')
        self.assertEqual(result, 'JSONB')
    
    def test_mysql_to_postgres_auto_increment(self):
        result = map_data_type('INT AUTO_INCREMENT', 'mysql', 'postgres')
        self.assertEqual(result, 'SERIAL')
    
    # MySQL to SQL Server tests
    def test_mysql_to_sqlserver_int(self):
        result = map_data_type('INT', 'mysql', 'sqlserver')
        self.assertEqual(result, 'INT')
    
    def test_mysql_to_sqlserver_varchar(self):
        result = map_data_type('VARCHAR', 'mysql', 'sqlserver', max_length=255)
        self.assertEqual(result, 'NVARCHAR(255)')
    
    def test_mysql_to_sqlserver_text(self):
        result = map_data_type('TEXT', 'mysql', 'sqlserver')
        self.assertEqual(result, 'NVARCHAR(MAX)')
    
    def test_mysql_to_sqlserver_boolean(self):
        result = map_data_type('BOOLEAN', 'mysql', 'sqlserver')
        self.assertEqual(result, 'BIT')
    
    # SQL Server to PostgreSQL tests
    def test_sqlserver_to_postgres_int(self):
        result = map_data_type('INT', 'sqlserver', 'postgres')
        self.assertEqual(result, 'INTEGER')
    
    def test_sqlserver_to_postgres_nvarchar(self):
        result = map_data_type('NVARCHAR', 'sqlserver', 'postgres', max_length=255)
        self.assertEqual(result, 'VARCHAR(255)')
    
    def test_sqlserver_to_postgres_nvarchar_max(self):
        result = map_data_type('NVARCHAR(MAX)', 'sqlserver', 'postgres')
        self.assertEqual(result, 'TEXT')
    
    def test_sqlserver_to_postgres_datetime2(self):
        result = map_data_type('DATETIME2', 'sqlserver', 'postgres')
        self.assertEqual(result, 'TIMESTAMP')
    
    def test_sqlserver_to_postgres_bit(self):
        result = map_data_type('BIT', 'sqlserver', 'postgres')
        self.assertEqual(result, 'BOOLEAN')
    
    def test_sqlserver_to_postgres_uniqueidentifier(self):
        result = map_data_type('UNIQUEIDENTIFIER', 'sqlserver', 'postgres')
        self.assertEqual(result, 'UUID')
    
    # SQL Server to MySQL tests
    def test_sqlserver_to_mysql_int(self):
        result = map_data_type('INT', 'sqlserver', 'mysql')
        self.assertEqual(result, 'INT')
    
    def test_sqlserver_to_mysql_nvarchar(self):
        result = map_data_type('NVARCHAR', 'sqlserver', 'mysql', max_length=255)
        self.assertEqual(result, 'VARCHAR(255)')
    
    def test_sqlserver_to_mysql_nvarchar_max(self):
        result = map_data_type('NVARCHAR(MAX)', 'sqlserver', 'mysql')
        self.assertEqual(result, 'LONGTEXT')
    
    def test_sqlserver_to_mysql_bit(self):
        result = map_data_type('BIT', 'sqlserver', 'mysql')
        self.assertEqual(result, 'TINYINT(1)')
    
    # Same database type tests
    def test_postgres_to_postgres(self):
        result = map_data_type('int4', 'postgres', 'postgres')
        self.assertEqual(result, 'int4')
    
    def test_mysql_to_mysql(self):
        result = map_data_type('INT', 'mysql', 'mysql')
        self.assertEqual(result, 'INT')
    
    def test_sqlserver_to_sqlserver(self):
        result = map_data_type('INT', 'sqlserver', 'sqlserver')
        self.assertEqual(result, 'INT')
    
    # Edge cases
    def test_unknown_type_fallback(self):
        result = map_data_type('UNKNOWN_TYPE', 'postgres', 'mysql')
        self.assertIn(result, ['TEXT', 'VARCHAR'])
    
    def test_numeric_with_precision_scale(self):
        result = map_data_type('numeric', 'postgres', 'mysql', precision=10, scale=2)
        self.assertEqual(result, 'DECIMAL(10,2)')
    
    def test_varchar_with_max_length(self):
        result = map_data_type('varchar', 'postgres', 'mysql', max_length=500)
        self.assertEqual(result, 'VARCHAR(500)')
    
    def test_nvarchar_max_replacement(self):
        result = map_data_type('text', 'postgres', 'sqlserver', max_length=1000)
        # Should replace (MAX) with actual length
        self.assertIn('1000', result)
    
    # Helper function tests
    def test_get_default_length_varchar(self):
        result = get_default_length('varchar', 'postgres')
        self.assertEqual(result, 255)
    
    def test_get_default_length_char(self):
        result = get_default_length('char', 'mysql')
        self.assertEqual(result, 255)
    
    def test_get_default_length_int(self):
        result = get_default_length('int', 'postgres')
        self.assertIsNone(result)
    
    def test_normalize_data_type_varchar(self):
        base_type, max_length, precision, scale = normalize_data_type('VARCHAR(255)', 'postgres')
        self.assertEqual(base_type, 'VARCHAR')
        self.assertEqual(max_length, 255)
        self.assertIsNone(precision)
        self.assertIsNone(scale)
    
    def test_normalize_data_type_decimal(self):
        base_type, max_length, precision, scale = normalize_data_type('DECIMAL(10,2)', 'mysql')
        self.assertEqual(base_type, 'DECIMAL')
        self.assertIsNone(max_length)
        self.assertEqual(precision, 10)
        self.assertEqual(scale, 2)
    
    def test_normalize_data_type_simple(self):
        base_type, max_length, precision, scale = normalize_data_type('INT', 'postgres')
        self.assertEqual(base_type, 'INT')
        self.assertIsNone(max_length)
        self.assertIsNone(precision)
        self.assertIsNone(scale)
    
    # Error handling tests
    def test_invalid_source_db(self):
        with self.assertRaises(ValueError):
            map_data_type('INT', 'invalid', 'mysql')
    
    def test_invalid_target_db(self):
        with self.assertRaises(ValueError):
            map_data_type('INT', 'mysql', 'invalid')
    
    # ClickHouse type mapping tests - PostgreSQL to ClickHouse
    def test_postgres_to_clickhouse_int4(self):
        result = map_data_type('int4', 'postgres', 'clickhouse')
        self.assertEqual(result, 'Int32')
    
    def test_postgres_to_clickhouse_bigint(self):
        result = map_data_type('bigint', 'postgres', 'clickhouse')
        self.assertEqual(result, 'Int64')
    
    def test_postgres_to_clickhouse_smallint(self):
        result = map_data_type('smallint', 'postgres', 'clickhouse')
        self.assertEqual(result, 'Int16')
    
    def test_postgres_to_clickhouse_varchar(self):
        result = map_data_type('varchar', 'postgres', 'clickhouse')
        self.assertEqual(result, 'String')
    
    def test_postgres_to_clickhouse_text(self):
        result = map_data_type('text', 'postgres', 'clickhouse')
        self.assertEqual(result, 'String')
    
    def test_postgres_to_clickhouse_timestamp(self):
        result = map_data_type('timestamp', 'postgres', 'clickhouse')
        self.assertEqual(result, 'DateTime')
    
    def test_postgres_to_clickhouse_date(self):
        result = map_data_type('date', 'postgres', 'clickhouse')
        self.assertEqual(result, 'Date')
    
    def test_postgres_to_clickhouse_boolean(self):
        result = map_data_type('boolean', 'postgres', 'clickhouse')
        self.assertEqual(result, 'UInt8')
    
    def test_postgres_to_clickhouse_numeric(self):
        result = map_data_type('numeric', 'postgres', 'clickhouse', precision=10, scale=2)
        self.assertEqual(result, 'Decimal(10,2)')
    
    def test_postgres_to_clickhouse_uuid(self):
        result = map_data_type('uuid', 'postgres', 'clickhouse')
        self.assertEqual(result, 'UUID')
    
    def test_postgres_to_clickhouse_json(self):
        result = map_data_type('json', 'postgres', 'clickhouse')
        self.assertEqual(result, 'String')
    
    # MySQL to ClickHouse tests
    def test_mysql_to_clickhouse_int(self):
        result = map_data_type('INT', 'mysql', 'clickhouse')
        self.assertEqual(result, 'Int32')
    
    def test_mysql_to_clickhouse_bigint(self):
        result = map_data_type('BIGINT', 'mysql', 'clickhouse')
        self.assertEqual(result, 'Int64')
    
    def test_mysql_to_clickhouse_varchar(self):
        result = map_data_type('VARCHAR', 'mysql', 'clickhouse')
        self.assertEqual(result, 'String')
    
    def test_mysql_to_clickhouse_datetime(self):
        result = map_data_type('DATETIME', 'mysql', 'clickhouse')
        self.assertEqual(result, 'DateTime')
    
    def test_mysql_to_clickhouse_decimal(self):
        result = map_data_type('DECIMAL', 'mysql', 'clickhouse', precision=10, scale=2)
        self.assertEqual(result, 'Decimal(10,2)')
    
    def test_mysql_to_clickhouse_tinyint_boolean(self):
        result = map_data_type('TINYINT(1)', 'mysql', 'clickhouse')
        self.assertEqual(result, 'UInt8')
    
    # SQL Server to ClickHouse tests
    def test_sqlserver_to_clickhouse_int(self):
        result = map_data_type('INT', 'sqlserver', 'clickhouse')
        self.assertEqual(result, 'Int32')
    
    def test_sqlserver_to_clickhouse_nvarchar(self):
        result = map_data_type('NVARCHAR', 'sqlserver', 'clickhouse')
        self.assertEqual(result, 'String')
    
    def test_sqlserver_to_clickhouse_datetime2(self):
        result = map_data_type('DATETIME2', 'sqlserver', 'clickhouse')
        self.assertEqual(result, 'DateTime64')
    
    def test_sqlserver_to_clickhouse_bit(self):
        result = map_data_type('BIT', 'sqlserver', 'clickhouse')
        self.assertEqual(result, 'UInt8')
    
    def test_sqlserver_to_clickhouse_uniqueidentifier(self):
        result = map_data_type('UNIQUEIDENTIFIER', 'sqlserver', 'clickhouse')
        self.assertEqual(result, 'UUID')
    
    # ClickHouse to PostgreSQL tests
    def test_clickhouse_to_postgres_int32(self):
        result = map_data_type('Int32', 'clickhouse', 'postgres')
        self.assertEqual(result, 'INTEGER')
    
    def test_clickhouse_to_postgres_int64(self):
        result = map_data_type('Int64', 'clickhouse', 'postgres')
        self.assertEqual(result, 'BIGINT')
    
    def test_clickhouse_to_postgres_string(self):
        result = map_data_type('String', 'clickhouse', 'postgres')
        self.assertEqual(result, 'TEXT')
    
    def test_clickhouse_to_postgres_datetime(self):
        result = map_data_type('DateTime', 'clickhouse', 'postgres')
        self.assertEqual(result, 'TIMESTAMP')
    
    def test_clickhouse_to_postgres_date(self):
        result = map_data_type('Date', 'clickhouse', 'postgres')
        self.assertEqual(result, 'DATE')
    
    def test_clickhouse_to_postgres_decimal(self):
        result = map_data_type('Decimal', 'clickhouse', 'postgres', precision=10, scale=2)
        self.assertEqual(result, 'NUMERIC(10,2)')
    
    def test_clickhouse_to_postgres_uuid(self):
        result = map_data_type('UUID', 'clickhouse', 'postgres')
        self.assertEqual(result, 'UUID')
    
    # ClickHouse to MySQL tests
    def test_clickhouse_to_mysql_int32(self):
        result = map_data_type('Int32', 'clickhouse', 'mysql')
        self.assertEqual(result, 'INT')
    
    def test_clickhouse_to_mysql_int64(self):
        result = map_data_type('Int64', 'clickhouse', 'mysql')
        self.assertEqual(result, 'BIGINT')
    
    def test_clickhouse_to_mysql_string(self):
        result = map_data_type('String', 'clickhouse', 'mysql')
        self.assertEqual(result, 'TEXT')
    
    def test_clickhouse_to_mysql_datetime(self):
        result = map_data_type('DateTime', 'clickhouse', 'mysql')
        self.assertEqual(result, 'DATETIME')
    
    def test_clickhouse_to_mysql_uint8(self):
        result = map_data_type('UInt8', 'clickhouse', 'mysql')
        self.assertEqual(result, 'TINYINT')
    
    # ClickHouse to SQL Server tests
    def test_clickhouse_to_sqlserver_int32(self):
        result = map_data_type('Int32', 'clickhouse', 'sqlserver')
        self.assertEqual(result, 'INT')
    
    def test_clickhouse_to_sqlserver_string(self):
        result = map_data_type('String', 'clickhouse', 'sqlserver')
        self.assertEqual(result, 'NVARCHAR(MAX)')
    
    def test_clickhouse_to_sqlserver_datetime(self):
        result = map_data_type('DateTime', 'clickhouse', 'sqlserver')
        self.assertEqual(result, 'DATETIME2')
    
    def test_clickhouse_to_sqlserver_uuid(self):
        result = map_data_type('UUID', 'clickhouse', 'sqlserver')
        self.assertEqual(result, 'UNIQUEIDENTIFIER')
    
    # ClickHouse same database type test
    def test_clickhouse_to_clickhouse(self):
        result = map_data_type('Int32', 'clickhouse', 'clickhouse')
        self.assertEqual(result, 'Int32')
    
    # ClickHouse Nullable type handling
    def test_clickhouse_nullable_type(self):
        result = map_data_type('Nullable(Int32)', 'clickhouse', 'postgres')
        self.assertEqual(result, 'INTEGER')
    
    def test_clickhouse_nullable_string(self):
        result = map_data_type('Nullable(String)', 'clickhouse', 'mysql')
        self.assertEqual(result, 'TEXT')
    
    # ClickHouse FixedString handling
    def test_clickhouse_fixedstring(self):
        result = map_data_type('FixedString', 'clickhouse', 'postgres', max_length=100)
        self.assertEqual(result, 'CHAR(100)')  # Should include length when max_length is provided
    
    # ClickHouse Decimal precision/scale handling
    def test_clickhouse_decimal_with_precision_scale(self):
        result = map_data_type('Decimal', 'clickhouse', 'mysql', precision=19, scale=4)
        self.assertEqual(result, 'DECIMAL(19,4)')
    
    # ClickHouse fallback test
    def test_clickhouse_unknown_type_fallback(self):
        # When mapping FROM ClickHouse to other DBs, fallback should be target DB's fallback
        result = map_data_type('UNKNOWN_TYPE', 'clickhouse', 'postgres')
        self.assertEqual(result, 'TEXT')  # Postgres fallback is TEXT


if __name__ == '__main__':
    unittest.main()

