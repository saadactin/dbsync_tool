"""
Tests for transformation engine
"""
import unittest
from unittest.mock import Mock
from sync_engine.transformation_engine import TransformationEngine
from connections.connectors.base import DBConnector


class TestTransformationEngine(unittest.TestCase):
    """Test cases for TransformationEngine"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.engine = TransformationEngine()
    
    def test_parse_column_list_clickhouse(self):
        """Test parsing column list with ClickHouse backticks"""
        select_clause = '`id`, `name`, `email`'
        columns = self.engine._parse_column_list(select_clause, 'clickhouse')
        self.assertEqual(len(columns), 3)
        self.assertEqual(columns[0], '`id`')
        self.assertEqual(columns[1], '`name`')
        self.assertEqual(columns[2], '`email`')
    
    def test_unquote_column_clickhouse(self):
        """Test unquoting ClickHouse column identifiers"""
        # Test with backticks
        self.assertEqual(self.engine._unquote_column('`name`', 'clickhouse'), 'name')
        # Test without quotes
        self.assertEqual(self.engine._unquote_column('name', 'clickhouse'), 'name')
        # Note: Escaped backticks in ClickHouse are handled during parsing, not unquoting
    
    def test_apply_column_transformation_trim_clickhouse(self):
        """Test TRIM transformation for ClickHouse"""
        result = self.engine._apply_column_transformation_to_select('name', 'TRIM', 'clickhouse')
        self.assertIn('trim', result.lower())
        self.assertIn('`name`', result)
        self.assertIn('AS', result)
    
    def test_apply_column_transformation_upper_clickhouse(self):
        """Test UPPER transformation for ClickHouse"""
        result = self.engine._apply_column_transformation_to_select('name', 'UPPER', 'clickhouse')
        self.assertIn('upper', result.lower())
        self.assertIn('`name`', result)
        self.assertIn('AS', result)
    
    def test_apply_column_transformation_lower_clickhouse(self):
        """Test LOWER transformation for ClickHouse"""
        result = self.engine._apply_column_transformation_to_select('name', 'LOWER', 'clickhouse')
        self.assertIn('lower', result.lower())
        self.assertIn('`name`', result)
        self.assertIn('AS', result)
    
    def test_apply_query_transformations_clickhouse(self):
        """Test applying transformations to query with ClickHouse connector"""
        clickhouse_connector = Mock(spec=DBConnector)
        clickhouse_connector.__class__.__name__ = 'ClickHouseConnector'
        
        base_query = 'SELECT `id`, `name` FROM `test_db`.`users`'
        where_clause = '`status` = 1'
        column_transformations = {'name': 'TRIM'}
        
        result = self.engine.apply_query_transformations(
            query=base_query,
            where_clause=where_clause,
            column_transformations=column_transformations,
            connector=clickhouse_connector
        )
        
        # Verify WHERE clause was added
        self.assertIn('WHERE', result)
        self.assertIn('`status` = 1', result)
        # Verify column transformation was applied (trim function)
        self.assertIn('trim', result.lower())
    
    def test_apply_row_transformations_clickhouse(self):
        """Test applying row transformations (Python-based)"""
        batch = [
            ('  Alice  ', 'BOB', 'charlie'),
            ('  Dave  ', 'EVE', 'frank')
        ]
        column_names = ['name', 'upper_name', 'lower_name']
        column_transformations = {
            'name': 'TRIM',
            'upper_name': 'UPPER',
            'lower_name': 'LOWER'
        }
        
        result = self.engine.apply_row_transformations(
            batch=batch,
            column_names=column_names,
            column_transformations=column_transformations
        )
        
        # Verify transformations applied
        self.assertEqual(result[0][0], 'Alice')  # TRIM
        self.assertEqual(result[0][1], 'BOB')  # Already uppercase
        self.assertEqual(result[0][2], 'charlie')  # Already lowercase


if __name__ == '__main__':
    import unittest.mock
    unittest.main()
