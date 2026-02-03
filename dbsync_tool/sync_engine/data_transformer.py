"""
Data transformer for converting JSON API data to tabular format
Supports multiple database types (ClickHouse, PostgreSQL, MySQL, SQL Server)
"""
import pandas as pd
import json
import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class DataTransformer:
    """
    Transforms and flattens JSON data from APIs to tabular format
    Prepares data for insertion into various database types
    """
    
    @staticmethod
    def flatten_json(data: List[Dict]) -> pd.DataFrame:
        """
        Flatten nested JSON to pandas DataFrame
        
        Args:
            data: List of record dictionaries with nested structures
            
        Returns:
            pd.DataFrame: Flattened DataFrame with all nested fields expanded
        """
        if not data:
            return pd.DataFrame()
        
        # Use pandas json_normalize for flattening
        df = pd.json_normalize(data, sep='_')
        
        # Convert complex objects (dicts, lists) to JSON strings
        for col in df.columns:
            if df[col].dtype == 'object':
                try:
                    # Check if column contains dict or list
                    sample_values = df[col].dropna()
                    if len(sample_values) > 0:
                        if any(isinstance(x, (dict, list)) for x in sample_values.head(10)):
                            df[col] = df[col].apply(
                                lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x
                            )
                except Exception as e:
                    logger.warning(f"Error processing column {col}: {e}")
                    pass
        
        # Clean column names for database compatibility
        df.columns = [DataTransformer._clean_column_name(col) for col in df.columns]
        
        # Add ingestion timestamp
        df['_ingestion_timestamp'] = datetime.now()
        
        return df
    
    @staticmethod
    def prepare_for_database(df: pd.DataFrame, db_type: str) -> pd.DataFrame:
        """
        Prepare DataFrame for specific database type
        
        Args:
            df: DataFrame to prepare
            db_type: Database type ('clickhouse', 'postgres', 'mysql', 'sqlserver')
            
        Returns:
            pd.DataFrame: Prepared DataFrame ready for database insertion
        """
        df = df.copy()
        
        # Replace NaN and None with appropriate defaults based on data type
        for col in df.columns:
            dtype = df[col].dtype
            
            if dtype in ['float64', 'float32']:
                df[col] = df[col].fillna(0.0)
            elif dtype in ['int64', 'int32', 'Int64']:
                df[col] = df[col].fillna(0)
            elif dtype == 'object':
                df[col] = df[col].fillna('')
            elif dtype == 'bool':
                df[col] = df[col].fillna(False)
            elif 'datetime' in str(dtype):
                # Fill datetime NaT with a default datetime
                df[col] = df[col].fillna(pd.Timestamp('1970-01-01'))
        
        # Convert any remaining problematic types to string
        for col in df.columns:
            if df[col].dtype == 'object':
                # Check if all values are already strings or can be converted
                try:
                    df[col] = df[col].astype(str)
                    # Replace 'nan' string with empty string
                    df[col] = df[col].replace('nan', '')
                except Exception as e:
                    logger.warning(f"Error converting column {col} to string: {e}")
        
        # Database-specific preparation
        if db_type == 'clickhouse':
            df = DataTransformer._prepare_for_clickhouse(df)
        elif db_type == 'postgres':
            df = DataTransformer._prepare_for_postgres(df)
        elif db_type == 'mysql':
            df = DataTransformer._prepare_for_mysql(df)
        elif db_type == 'sqlserver':
            df = DataTransformer._prepare_for_sqlserver(df)
        else:
            logger.warning(f"Unknown database type {db_type}, using default preparation")
        
        return df
    
    @staticmethod
    def _prepare_for_clickhouse(df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare DataFrame specifically for ClickHouse
        
        Args:
            df: DataFrame to prepare
            
        Returns:
            pd.DataFrame: Prepared DataFrame for ClickHouse
        """
        # ClickHouse handles NaN well, but we've already filled them
        # Ensure all object columns are strings
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str)
                df[col] = df[col].replace('nan', '')
        
        return df
    
    @staticmethod
    def _prepare_for_postgres(df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare DataFrame specifically for PostgreSQL
        
        Args:
            df: DataFrame to prepare
            
        Returns:
            pd.DataFrame: Prepared DataFrame for PostgreSQL
        """
        # PostgreSQL handles NaN well with NULL values
        # But we've already filled them for consistency
        # Ensure datetime columns are properly formatted
        for col in df.columns:
            if 'datetime' in str(df[col].dtype):
                # Ensure datetime columns are datetime objects
                df[col] = pd.to_datetime(df[col], errors='coerce')
                df[col] = df[col].fillna(pd.Timestamp('1970-01-01'))
        
        return df
    
    @staticmethod
    def _prepare_for_mysql(df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare DataFrame specifically for MySQL
        
        Args:
            df: DataFrame to prepare
            
        Returns:
            pd.DataFrame: Prepared DataFrame for MySQL
        """
        # MySQL handles NaN well with NULL values
        # Ensure datetime columns are properly formatted
        for col in df.columns:
            if 'datetime' in str(df[col].dtype):
                # Ensure datetime columns are datetime objects
                df[col] = pd.to_datetime(df[col], errors='coerce')
                df[col] = df[col].fillna(pd.Timestamp('1970-01-01'))
        
        return df
    
    @staticmethod
    def _prepare_for_sqlserver(df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare DataFrame specifically for SQL Server
        
        Args:
            df: DataFrame to prepare
            
        Returns:
            pd.DataFrame: Prepared DataFrame for SQL Server
        """
        # SQL Server handles NaN well with NULL values
        # Ensure datetime columns are properly formatted
        for col in df.columns:
            if 'datetime' in str(df[col].dtype):
                # Ensure datetime columns are datetime objects
                df[col] = pd.to_datetime(df[col], errors='coerce')
                df[col] = df[col].fillna(pd.Timestamp('1970-01-01'))
        
        return df
    
    @staticmethod
    def _clean_column_name(name: str) -> str:
        """
        Clean column name for database compatibility
        
        Args:
            name: Original column name
            
        Returns:
            str: Cleaned column name safe for database use
        """
        # Replace problematic characters
        name = name.replace('.', '_').replace('$', '_').replace(' ', '_')
        name = name.replace('(', '').replace(')', '').replace('"', '').replace("'", '')
        name = name.replace('[', '').replace(']', '').replace('{', '').replace('}', '')
        name = name.replace('/', '_').replace('\\', '_').replace(':', '_')
        
        # Remove leading/trailing underscores
        name = name.strip('_')
        
        # Ensure name is not empty
        if not name:
            name = 'unnamed_column'
        
        # Ensure name doesn't start with a number (some DBs don't allow this)
        if name and name[0].isdigit():
            name = 'col_' + name
        
        return name
