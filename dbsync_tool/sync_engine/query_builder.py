"""
Query building utilities for different database types
"""
from typing import Optional, List, Any
from connections.connectors.base import DBConnector
from sync_engine.exceptions import QueryBuilderError
import logging

logger = logging.getLogger(__name__)

class QueryBuilder:
    """Builds database-specific queries"""
    
    @staticmethod
    def get_db_type(connector: DBConnector) -> str:
        """
        Get database type from connector
        
        Args:
            connector: Database connector instance
            
        Returns:
            Database type string ('postgres', 'mysql', 'sqlserver')
        """
        class_name = connector.__class__.__name__
        if 'Postgres' in class_name:
            return 'postgres'
        elif 'MySQL' in class_name:
            return 'mysql'
        elif 'SQLServer' in class_name:
            return 'sqlserver'
        else:
            raise QueryBuilderError(f"Unknown connector type: {class_name}")
    
    @staticmethod
    def build_select_query(
        connector: DBConnector,
        schema: str,
        table: str,
        columns: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        where_clause: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> str:
        """
        Build SELECT query based on database type
        
        Args:
            connector: Database connector instance
            schema: Schema/database name
            table: Table name
            columns: List of column names (None for *)
            order_by: ORDER BY clause
            where_clause: WHERE clause
            limit: LIMIT value
            offset: OFFSET value
            
        Returns:
            SQL query string
        """
        db_type = QueryBuilder.get_db_type(connector)
        
        # Build schema.table identifier based on DB type
        if db_type == 'postgres':
            schema_part = f'"{schema}"."{table}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
        else:
            schema_part = f'{schema}.{table}'
        
        # Build column list
        if columns:
            if db_type == 'postgres':
                col_list = ', '.join(f'"{col}"' for col in columns)
            elif db_type == 'mysql':
                col_list = ', '.join(f'`{col}`' for col in columns)
            elif db_type == 'sqlserver':
                col_list = ', '.join(f'[{col}]' for col in columns)
            else:
                col_list = ', '.join(columns)
        else:
            col_list = '*'
        
        query = f'SELECT {col_list} FROM {schema_part}'
        
        if where_clause:
            query += f' WHERE {where_clause}'
        
        if order_by:
            # Format order_by columns with proper quoting for the database type
            if db_type == 'postgres':
                # Split by comma, strip, and quote each column
                order_cols = ', '.join(f'"{col.strip()}"' for col in order_by.split(','))
            elif db_type == 'mysql':
                order_cols = ', '.join(f'`{col.strip()}`' for col in order_by.split(','))
            elif db_type == 'sqlserver':
                order_cols = ', '.join(f'[{col.strip()}]' for col in order_by.split(','))
            else:
                order_cols = order_by
            query += f' ORDER BY {order_cols}'
        
        # Add LIMIT/OFFSET based on DB type
        if db_type == 'sqlserver':
            if offset is not None and limit is not None:
                query += f' OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY'
            elif limit is not None:
                query += f' OFFSET 0 ROWS FETCH NEXT {limit} ROWS ONLY'
        else:
            if limit is not None:
                query += f' LIMIT {limit}'
            if offset is not None:
                query += f' OFFSET {offset}'
        
        return query
    
    @staticmethod
    def build_count_query(
        connector: DBConnector,
        schema: str,
        table: str,
        where_clause: Optional[str] = None
    ) -> str:
        """
        Build COUNT query for row count
        
        Args:
            connector: Database connector instance
            schema: Schema/database name
            table: Table name
            where_clause: Optional WHERE clause
            
        Returns:
            SQL COUNT query string
        """
        db_type = QueryBuilder.get_db_type(connector)
        
        if db_type == 'postgres':
            schema_part = f'"{schema}"."{table}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
        else:
            schema_part = f'{schema}.{table}'
        
        query = f'SELECT COUNT(*) FROM {schema_part}'
        
        if where_clause:
            query += f' WHERE {where_clause}'
        
        return query
    
    @staticmethod
    def build_incremental_query(
        connector: DBConnector,
        schema: str,
        table: str,
        incremental_column: str,
        checkpoint_value: Optional[Any] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[str] = None
    ) -> str:
        """
        Build incremental sync query (WHERE incremental_column > checkpoint_value)
        
        Args:
            connector: Database connector instance
            schema: Schema/database name
            table: Table name
            incremental_column: Column name for incremental sync
            checkpoint_value: Last synced value (None for first sync)
            columns: List of column names (None for *)
            order_by: Optional ORDER BY clause
            
        Returns:
            SQL query string
            
        Raises:
            QueryBuilderError: If query building fails
        """
        if not schema or not table or not incremental_column:
            raise QueryBuilderError(
                "Schema, table, and incremental_column are required"
            )
        
        db_type = QueryBuilder.get_db_type(connector)
        
        # Build schema.table identifier
        if db_type == 'postgres':
            schema_part = f'"{schema}"."{table}"'
            col_identifier = lambda c: f'"{c}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
            col_identifier = lambda c: f'`{c}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
            col_identifier = lambda c: f'[{c}]'
        else:
            schema_part = f'{schema}.{table}'
            col_identifier = lambda c: c
        
        # Build column list
        if columns:
            col_list = ', '.join(col_identifier(col) for col in columns)
        else:
            col_list = '*'
        
        query = f'SELECT {col_list} FROM {schema_part}'
        
        # Add WHERE clause for incremental sync
        inc_col = col_identifier(incremental_column)
        
        if checkpoint_value is not None:
            # Format checkpoint value based on type and database
            formatted_value = QueryBuilder._format_checkpoint_value(
                checkpoint_value, db_type
            )
            query += f' WHERE {inc_col} > {formatted_value}'
        else:
            # First sync - get all rows (WHERE 1=1 allows ORDER BY)
            query += ' WHERE 1=1'
        
        # Add ORDER BY
        if order_by:
            # Format order_by columns
            if db_type == 'postgres':
                order_cols = ', '.join(f'"{col.strip()}"' for col in order_by.split(','))
            elif db_type == 'mysql':
                order_cols = ', '.join(f'`{col.strip()}`' for col in order_by.split(','))
            elif db_type == 'sqlserver':
                order_cols = ', '.join(f'[{col.strip()}]' for col in order_by.split(','))
            else:
                order_cols = order_by
            query += f' ORDER BY {order_cols}'
        else:
            # Default: order by incremental column
            query += f' ORDER BY {inc_col}'
        
        return query
    
    @staticmethod
    def _format_checkpoint_value(value: Any, db_type: str) -> str:
        """
        Format checkpoint value for SQL query based on database type
        
        Args:
            value: Checkpoint value (int, float, str, datetime)
            db_type: Database type ('postgres', 'mysql', 'sqlserver')
            
        Returns:
            Formatted string for SQL query
        """
        if isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Try to detect if it's a number string
            try:
                float(value)
                return value
            except ValueError:
                # It's a string - escape quotes
                escaped = value.replace("'", "''")
                if db_type == 'postgres':
                    return f"'{escaped}'::timestamp"
                else:
                    return f"'{escaped}'"
        else:
            # Default: convert to string and escape
            escaped = str(value).replace("'", "''")
            return f"'{escaped}'"
    
    @staticmethod
    def build_max_value_query(
        connector: DBConnector,
        schema: str,
        table: str,
        column: str
    ) -> str:
        """
        Build query to get maximum value of a column
        
        Args:
            connector: Database connector instance
            schema: Schema/database name
            table: Table name
            column: Column name
            
        Returns:
            SQL query string
        """
        if not schema or not table or not column:
            raise QueryBuilderError(
                "Schema, table, and column are required"
            )
        
        db_type = QueryBuilder.get_db_type(connector)
        
        if db_type == 'postgres':
            schema_part = f'"{schema}"."{table}"'
            col = f'"{column}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
            col = f'`{column}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
            col = f'[{column}]'
        else:
            schema_part = f'{schema}.{table}'
            col = column
        
        return f'SELECT MAX({col}) FROM {schema_part}'

