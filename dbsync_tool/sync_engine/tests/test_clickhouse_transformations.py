"""
Tests for ClickHouse transformation engine (Day 6)
Tests transformation functions with ClickHouse
"""
from django.test import TestCase
from unittest.mock import Mock, MagicMock
from connections.connectors.clickhouse import ClickHouseConnector
from sync_engine.transformation_engine import TransformationEngine
from sync_engine.query_builder import QueryBuilder


class ClickHouseTransformationEngineTests(TestCase):
    """Test ClickHouse transformation engine"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.connector = Mock(spec=ClickHouseConnector)
        self.connector.__class__.__name__ = 'ClickHouseConnector'
        
        self.transformation_engine = TransformationEngine()
    
    def test_trim_transformation_clickhouse(self):
        """Test TRIM transformation with ClickHouse"""
        query = "SELECT `name` FROM `test_db`.`test_table`"
        column_transformations = {'name': 'TRIM'}
        
        result = self.transformation_engine.apply_query_transformations(
            query=query,
            where_clause=None,
            column_transformations=column_transformations,
            connector=self.connector
        )
        
        # Should use lowercase trim() for ClickHouse
        self.assertIn('trim(`name`)', result.lower())
        self.assertIn('AS `name`', result)
    
    def test_upper_transformation_clickhouse(self):
        """Test UPPER transformation with ClickHouse"""
        query = "SELECT `name` FROM `test_db`.`test_table`"
        column_transformations = {'name': 'UPPER'}
        
        result = self.transformation_engine.apply_query_transformations(
            query=query,
            where_clause=None,
            column_transformations=column_transformations,
            connector=self.connector
        )
        
        # Should use lowercase upper() for ClickHouse
        self.assertIn('upper(`name`)', result.lower())
        self.assertIn('AS `name`', result)
    
    def test_lower_transformation_clickhouse(self):
        """Test LOWER transformation with ClickHouse"""
        query = "SELECT `name` FROM `test_db`.`test_table`"
        column_transformations = {'name': 'LOWER'}
        
        result = self.transformation_engine.apply_query_transformations(
            query=query,
            where_clause=None,
            column_transformations=column_transformations,
            connector=self.connector
        )
        
        # Should use lowercase lower() for ClickHouse
        self.assertIn('lower(`name`)', result.lower())
        self.assertIn('AS `name`', result)
    
    def test_multiple_transformations_clickhouse(self):
        """Test multiple transformations with ClickHouse"""
        query = "SELECT `name`, `email` FROM `test_db`.`test_table`"
        column_transformations = {
            'name': 'TRIM',
            'email': 'LOWER'
        }
        
        result = self.transformation_engine.apply_query_transformations(
            query=query,
            where_clause=None,
            column_transformations=column_transformations,
            connector=self.connector
        )
        
        # Should apply both transformations
        self.assertIn('trim(`name`)', result.lower())
        self.assertIn('lower(`email`)', result.lower())
    
    def test_where_clause_with_transformations_clickhouse(self):
        """Test WHERE clause with transformations for ClickHouse"""
        query = "SELECT `name` FROM `test_db`.`test_table`"
        where_clause = "`status` = 'active'"
        column_transformations = {'name': 'TRIM'}
        
        result = self.transformation_engine.apply_query_transformations(
            query=query,
            where_clause=where_clause,
            column_transformations=column_transformations,
            connector=self.connector
        )
        
        # Should include both WHERE clause and transformation
        self.assertIn('WHERE', result)
        self.assertIn('status', result)
        self.assertIn('trim(`name`)', result.lower())
    
    def test_parse_column_list_clickhouse_backticks(self):
        """Test parsing column list with ClickHouse backticks"""
        select_clause = "`col1`, `col2`, `col3`"
        columns = self.transformation_engine._parse_column_list(select_clause, 'clickhouse')
        
        self.assertEqual(len(columns), 3)
        self.assertIn('`col1`', columns)
        self.assertIn('`col2`', columns)
        self.assertIn('`col3`', columns)
    
    def test_unquote_column_clickhouse(self):
        """Test unquoting ClickHouse column identifiers"""
        # Test with backticks
        self.assertEqual(
            self.transformation_engine._unquote_column('`column_name`', 'clickhouse'),
            'column_name'
        )
        
        # Test without quotes
        self.assertEqual(
            self.transformation_engine._unquote_column('column_name', 'clickhouse'),
            'column_name'
        )
    
    def test_apply_column_transformation_to_select_clickhouse(self):
        """Test applying transformation to SELECT clause for ClickHouse"""
        # Test TRIM
        result = self.transformation_engine._apply_column_transformation_to_select(
            'name', 'TRIM', 'clickhouse'
        )
        self.assertIn('trim(`name`)', result.lower())
        self.assertIn('AS `name`', result)
        
        # Test UPPER
        result = self.transformation_engine._apply_column_transformation_to_select(
            'name', 'UPPER', 'clickhouse'
        )
        self.assertIn('upper(`name`)', result.lower())
        
        # Test LOWER
        result = self.transformation_engine._apply_column_transformation_to_select(
            'name', 'LOWER', 'clickhouse'
        )
        self.assertIn('lower(`name`)', result.lower())
