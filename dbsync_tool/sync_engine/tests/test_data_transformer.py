"""
Tests for Data Transformer
"""
import unittest
import pandas as pd
import json
from datetime import datetime
from django.test import TestCase
from sync_engine.data_transformer import DataTransformer


class DataTransformerTests(TestCase):
    """Test cases for DataTransformer"""
    
    def test_flatten_json_empty(self):
        """Test flattening empty JSON list"""
        result = DataTransformer.flatten_json([])
        
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)
    
    def test_flatten_json_simple(self):
        """Test flattening simple JSON records"""
        data = [
            {'id': '1', 'name': 'Test 1', 'value': 100},
            {'id': '2', 'name': 'Test 2', 'value': 200}
        ]
        
        result = DataTransformer.flatten_json(data)
        
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 2)
        self.assertIn('id', result.columns)
        self.assertIn('name', result.columns)
        self.assertIn('value', result.columns)
        self.assertIn('_ingestion_timestamp', result.columns)
    
    def test_flatten_json_nested(self):
        """Test flattening nested JSON records"""
        data = [
            {
                'id': '1',
                'name': 'Test 1',
                'owner': {
                    'id': 'owner1',
                    'name': 'Owner Name'
                },
                'tags': ['tag1', 'tag2']
            }
        ]
        
        result = DataTransformer.flatten_json(data)
        
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 1)
        self.assertIn('owner_id', result.columns)
        self.assertIn('owner_name', result.columns)
        self.assertIn('tags', result.columns)
    
    def test_flatten_json_complex_objects(self):
        """Test flattening JSON with complex objects converted to strings"""
        data = [
            {
                'id': '1',
                'nested_dict': {'key': 'value'},
                'nested_list': [1, 2, 3]
            }
        ]
        
        result = DataTransformer.flatten_json(data)
        
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 1)
        
        # Complex objects should be JSON strings
        nested_dict_value = result['nested_dict'].iloc[0]
        self.assertIsInstance(nested_dict_value, str)
        self.assertEqual(json.loads(nested_dict_value), {'key': 'value'})
    
    def test_prepare_for_database_clickhouse(self):
        """Test preparing DataFrame for ClickHouse"""
        df = pd.DataFrame({
            'id': ['1', '2', None],
            'value': [100, 200, None],
            'name': ['Test', None, 'Another']
        })
        
        result = DataTransformer.prepare_for_database(df, 'clickhouse')
        
        self.assertIsInstance(result, pd.DataFrame)
        # NaN values should be filled
        self.assertFalse(result['id'].isna().any())
        self.assertFalse(result['value'].isna().any())
        self.assertFalse(result['name'].isna().any())
    
    def test_prepare_for_database_postgres(self):
        """Test preparing DataFrame for PostgreSQL"""
        df = pd.DataFrame({
            'id': ['1', '2'],
            'value': [100, 200],
            'created_at': [datetime.now(), None]
        })
        
        result = DataTransformer.prepare_for_database(df, 'postgres')
        
        self.assertIsInstance(result, pd.DataFrame)
        # Datetime NaT should be filled
        self.assertFalse(result['created_at'].isna().any())
    
    def test_prepare_for_database_mysql(self):
        """Test preparing DataFrame for MySQL"""
        df = pd.DataFrame({
            'id': ['1', '2'],
            'value': [100.5, None],
            'name': ['Test', None]
        })
        
        result = DataTransformer.prepare_for_database(df, 'mysql')
        
        self.assertIsInstance(result, pd.DataFrame)
        # NaN values should be filled
        self.assertFalse(result['value'].isna().any())
        self.assertFalse(result['name'].isna().any())
    
    def test_prepare_for_database_sqlserver(self):
        """Test preparing DataFrame for SQL Server"""
        df = pd.DataFrame({
            'id': ['1', '2'],
            'value': [100, None],
            'created_at': [datetime.now(), None]
        })
        
        result = DataTransformer.prepare_for_database(df, 'sqlserver')
        
        self.assertIsInstance(result, pd.DataFrame)
        # NaN values should be filled
        self.assertFalse(result['value'].isna().any())
        self.assertFalse(result['created_at'].isna().any())
    
    def test_clean_column_name(self):
        """Test column name cleaning"""
        test_cases = [
            ('normal_name', 'normal_name'),
            ('name.with.dots', 'name_with_dots'),
            ('name with spaces', 'name_with_spaces'),
            ('name(with)parens', 'namewithparens'),
            ('name[with]brackets', 'namewithbrackets'),
            ('name/with/slashes', 'name_with_slashes'),
            ('123starts_with_number', 'col_123starts_with_number'),
            ('', 'unnamed_column'),
        ]
        
        for input_name, expected in test_cases:
            result = DataTransformer._clean_column_name(input_name)
            self.assertEqual(result, expected, f"Failed for input: {input_name}")
    
    def test_prepare_for_database_handles_nan(self):
        """Test that NaN values are properly handled"""
        df = pd.DataFrame({
            'int_col': [1, 2, None],
            'float_col': [1.5, 2.5, None],
            'str_col': ['a', 'b', None],
            'bool_col': [True, False, None]
        })
        
        result = DataTransformer.prepare_for_database(df, 'clickhouse')
        
        # All NaN should be filled
        self.assertFalse(result['int_col'].isna().any())
        self.assertFalse(result['float_col'].isna().any())
        self.assertFalse(result['str_col'].isna().any())
        self.assertFalse(result['bool_col'].isna().any())
        
        # Check default values
        self.assertEqual(result['int_col'].iloc[2], 0)
        self.assertEqual(result['float_col'].iloc[2], 0.0)
        self.assertEqual(result['str_col'].iloc[2], '')
        self.assertEqual(result['bool_col'].iloc[2], False)
