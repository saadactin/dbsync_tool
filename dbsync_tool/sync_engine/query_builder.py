"""
Query building utilities for different database types
"""
from typing import Optional, List, Any, Dict
from datetime import datetime
from connections.connectors.base import DBConnector
from sync_engine.exceptions import QueryBuilderError
import logging
import re

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
            Database type string ('postgres', 'mysql', 'sqlserver', 'clickhouse', 'oracle')
        """
        class_name = connector.__class__.__name__
        if 'Postgres' in class_name:
            return 'postgres'
        elif 'MySQL' in class_name:
            return 'mysql'
        elif 'SQLServer' in class_name:
            return 'sqlserver'
        elif 'ClickHouse' in class_name:
            return 'clickhouse'
        elif 'Oracle' in class_name:
            # Covers OracleADWConnector and similar Oracle connectors
            return 'oracle'
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
        offset: Optional[int] = None,
        column_transformations: Optional[Dict[str, str]] = None
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
            column_transformations: Optional dict mapping column_name -> transformation_type
            
        Returns:
            SQL query string
        """
        db_type = QueryBuilder.get_db_type(connector)
        
        # Build schema.table identifier based on DB type
        if db_type == 'postgres' or db_type == 'oracle':
            schema_part = f'"{schema}"."{table}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
        elif db_type == 'clickhouse':
            schema_part = f'`{schema}`.`{table}`'
        else:
            schema_part = f'{schema}.{table}'
        
        # Build column list with transformations if provided
        if columns:
            if column_transformations:
                col_list = QueryBuilder.apply_column_transformations(
                    columns, column_transformations, db_type
                )
            else:
                if db_type == 'postgres' or db_type == 'oracle':
                    col_list = ', '.join(f'"{col}"' for col in columns)
                elif db_type == 'mysql':
                    col_list = ', '.join(f'`{col}`' for col in columns)
                elif db_type == 'sqlserver':
                    col_list = ', '.join(f'[{col}]' for col in columns)
                elif db_type == 'clickhouse':
                    col_list = ', '.join(f'`{col}`' for col in columns)
                else:
                    col_list = ', '.join(columns)
        else:
            col_list = '*'
        
        query = f'SELECT {col_list} FROM {schema_part}'
        
        if where_clause:
            # Normalize WHERE clause column names to match database type
            # Users might enter PostgreSQL-style quotes ("column") but source might be MySQL (needs `column`)
            normalized_where = QueryBuilder._normalize_where_clause_column_quotes(where_clause, db_type)
            query += f' WHERE {normalized_where}'
        
        if order_by:
            # Format order_by columns with proper quoting for the database type
            if db_type == 'postgres' or db_type == 'oracle':
                # Split by comma, strip, and quote each column
                order_cols = ', '.join(f'"{col.strip()}"' for col in order_by.split(','))
            elif db_type == 'mysql':
                order_cols = ', '.join(f'`{col.strip()}`' for col in order_by.split(','))
            elif db_type == 'sqlserver':
                order_cols = ', '.join(f'[{col.strip()}]' for col in order_by.split(','))
            elif db_type == 'clickhouse':
                order_cols = ', '.join(f'`{col.strip()}`' for col in order_by.split(','))
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
            # PostgreSQL, MySQL, and ClickHouse all support LIMIT/OFFSET.
            # Oracle ADW uses OFFSET/FETCH at the connector layer, so we do
            # NOT append LIMIT/OFFSET here for db_type == 'oracle'.
            if db_type != 'oracle':
                if limit is not None:
                    query += f' LIMIT {limit}'
                if offset is not None:
                    query += f' OFFSET {offset}'
        
        return query
    
    @staticmethod
    def build_keyset_select_query(
        connector: DBConnector,
        schema: str,
        table: str,
        pk_columns: List[str],
        last_pk_values: Optional[List[Any]] = None,
        columns: Optional[List[str]] = None,
        where_clause: Optional[str] = None,
        limit: Optional[int] = None,
        column_transformations: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Build SELECT query using Keyset Pagination (WHERE PK > last_pk)
        
        Args:
            connector: Database connector instance
            schema: Schema/database name
            table: Table name
            pk_columns: List of primary key column names
            last_pk_values: Values of PK columns from last row of the previous batch
            columns: List of column names (None for *)
            where_clause: Additional WHERE clause
            limit: LIMIT value (batch size)
            column_transformations: Optional dict mapping column_name -> transformation_type
            
        Returns:
            SQL query string
        """
        db_type = QueryBuilder.get_db_type(connector)
        
        # Build schema.table identifier
        if db_type == 'postgres' or db_type == 'oracle':
            schema_part = f'"{schema}"."{table}"'
            quote = lambda c: f'"{c}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
            quote = lambda c: f'`{c}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
            quote = lambda c: f'[{c}]'
        elif db_type == 'clickhouse':
            schema_part = f'`{schema}`.`{table}`'
            quote = lambda c: f'`{c}`'
        else:
            schema_part = f'{schema}.{table}'
            quote = lambda c: c
        
        # Build column list
        if columns:
            if column_transformations:
                col_list = QueryBuilder.apply_column_transformations(
                    columns, column_transformations, db_type
                )
            else:
                col_list = ', '.join(quote(col) for col in columns)
        else:
            col_list = '*'
        
        query = f'SELECT {col_list} FROM {schema_part}'
        
        # Build pagination condition
        pag_condition = None
        if last_pk_values and len(last_pk_values) == len(pk_columns):
            # Simple case: Single column PK
            if len(pk_columns) == 1:
                col = quote(pk_columns[0])
                val = QueryBuilder._format_checkpoint_value(last_pk_values[0], db_type)
                pag_condition = f"{col} > {val}"
            else:
                # Compound PK: (pk1 > val1) OR (pk1 = val1 AND pk2 > val2) ...
                conditions = []
                for i in range(len(pk_columns)):
                    part = []
                    for j in range(i):
                        c = quote(pk_columns[j])
                        v = QueryBuilder._format_checkpoint_value(last_pk_values[j], db_type)
                        part.append(f"{c} = {v}")
                    
                    c_curr = quote(pk_columns[i])
                    v_curr = QueryBuilder._format_checkpoint_value(last_pk_values[i], db_type)
                    part.append(f"{c_curr} > {v_curr}")
                    conditions.append(f"({' AND '.join(part)})")
                
                pag_condition = f"({' OR '.join(conditions)})"
        
        # Combine conditions
        final_where = []
        if where_clause:
            final_where.append(f"({QueryBuilder._normalize_where_clause_column_quotes(where_clause, db_type)})")
        if pag_condition:
            final_where.append(f"({pag_condition})")
        
        if final_where:
            query += f" WHERE {' AND '.join(final_where)}"
        
        # Always order by PK for keyset pagination
        order_cols = ', '.join(quote(col) for col in pk_columns)
        query += f" ORDER BY {order_cols}"
        
        # Add LIMIT
        if limit is not None:
            if db_type == 'sqlserver':
                query += f' OFFSET 0 ROWS FETCH NEXT {limit} ROWS ONLY'
            elif db_type != 'oracle':
                query += f' LIMIT {limit}'
        
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
        
        if db_type == 'postgres' or db_type == 'oracle':
            schema_part = f'"{schema}"."{table}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
        elif db_type == 'clickhouse':
            schema_part = f'`{schema}`.`{table}`'
        else:
            schema_part = f'{schema}.{table}'
        
        query = f'SELECT COUNT(*) FROM {schema_part}'
        
        if where_clause:
            # Normalize WHERE clause column quotes to match database type
            normalized_where = QueryBuilder._normalize_where_clause_column_quotes(where_clause, db_type)
            query += f' WHERE {normalized_where}'
        
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
        if db_type == 'postgres' or db_type == 'oracle':
            schema_part = f'"{schema}"."{table}"'
            col_identifier = lambda c: f'"{c}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
            col_identifier = lambda c: f'`{c}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
            col_identifier = lambda c: f'[{c}]'
        elif db_type == 'clickhouse':
            schema_part = f'`{schema}`.`{table}`'
            col_identifier = lambda c: f'`{c}`'
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
            # For ClickHouse, explicitly filter out NULL values in incremental column
            # This ensures NULL values don't interfere with incremental sync
            if db_type == 'clickhouse':
                query += f' WHERE {inc_col} > {formatted_value} AND {inc_col} IS NOT NULL'
            else:
                query += f' WHERE {inc_col} > {formatted_value}'
        else:
            # First sync - get all rows (WHERE 1=1 allows ORDER BY)
            # For ClickHouse, filter out NULL values in incremental column
            if db_type == 'clickhouse':
                query += f' WHERE {inc_col} IS NOT NULL'
            else:
                query += ' WHERE 1=1'
        
        # Add ORDER BY
        if order_by:
            # Format order_by columns
            if db_type == 'postgres' or db_type == 'oracle':
                order_cols = ', '.join(f'"{col.strip()}"' for col in order_by.split(','))
            elif db_type == 'mysql':
                order_cols = ', '.join(f'`{col.strip()}`' for col in order_by.split(','))
            elif db_type == 'sqlserver':
                order_cols = ', '.join(f'[{col.strip()}]' for col in order_by.split(','))
            elif db_type == 'clickhouse':
                order_cols = ', '.join(f'`{col.strip()}`' for col in order_by.split(','))
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
            db_type: Database type ('postgres', 'mysql', 'sqlserver', 'clickhouse')
            
        Returns:
            Formatted string for SQL query
        """
        if isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, bytes):
            if db_type == 'sqlserver':
                # MS SQL rowversion/timestamp is binary, needs 0x prefix
                return f"0x{value.hex()}"
            return f"'{value.hex()}'"
        elif isinstance(value, datetime):
            # Format datetime as ISO string for most DBs
            formatted = value.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            if db_type == 'postgres':
                return f"'{formatted}'::timestamp"
            elif db_type == 'clickhouse':
                return f"toDateTime64('{formatted}', 3)"
            elif db_type == 'sqlserver':
                return f"'{formatted}'"
            return f"'{formatted}'"
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
                elif db_type == 'clickhouse':
                    return f"toDateTime('{escaped}')"
                elif db_type == 'oracle':
                    return f"'{escaped}'"
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
        
        if db_type == 'postgres' or db_type == 'oracle':
            schema_part = f'"{schema}"."{table}"'
            col = f'"{column}"'
        elif db_type == 'mysql':
            schema_part = f'`{schema}`.`{table}`'
            col = f'`{column}`'
        elif db_type == 'sqlserver':
            schema_part = f'[{schema}].[{table}]'
            col = f'[{column}]'
        elif db_type == 'clickhouse':
            schema_part = f'`{schema}`.`{table}`'
            col = f'`{column}`'
        else:
            schema_part = f'{schema}.{table}'
            col = column
        
        return f'SELECT MAX({col}) FROM {schema_part}'
    
    @staticmethod
    def apply_column_transformations(
        columns: List[str],
        transformations: Dict[str, str],
        db_type: str
    ) -> str:
        """
        Apply column transformations to column list for SELECT clause
        
        Args:
            columns: List of column names
            transformations: Dict mapping column_name -> transformation_type
            db_type: Database type ('postgres', 'mysql', 'sqlserver')
            
        Returns:
            Formatted SELECT clause with transformations applied
            
        Example:
            columns = ['name', 'email']
            transformations = {'name': 'TRIM', 'email': 'UPPER'}
            db_type = 'postgres'
            Returns: 'TRIM("name") AS "name", UPPER("email") AS "email"'
        """
        ALLOWED_TRANSFORMATIONS = {'TRIM', 'UPPER', 'LOWER'}
        
        transformed_cols = []
        for col in columns:
            if col in transformations:
                transformation = transformations[col].upper()
                if transformation not in ALLOWED_TRANSFORMATIONS:
                    # Invalid transformation, use original column
                    logger.warning(f"Invalid transformation '{transformation}' for column '{col}', using original")
                    if db_type == 'postgres':
                        transformed_cols.append(f'"{col}"')
                    elif db_type == 'mysql':
                        transformed_cols.append(f'`{col}`')
                    elif db_type == 'sqlserver':
                        transformed_cols.append(f'[{col}]')
                    elif db_type == 'clickhouse':
                        transformed_cols.append(f'`{col}`')
                    else:
                        transformed_cols.append(col)
                    continue
                
                # Quote column based on DB type
                if db_type == 'postgres':
                    quoted_col = f'"{col}"'
                elif db_type == 'mysql':
                    quoted_col = f'`{col}`'
                elif db_type == 'sqlserver':
                    quoted_col = f'[{col}]'
                elif db_type == 'clickhouse':
                    quoted_col = f'`{col}`'
                else:
                    quoted_col = col
                
                # Apply transformation
                if transformation == 'TRIM':
                    if db_type == 'sqlserver':
                        # SQL Server uses LTRIM(RTRIM())
                        transformed = f'LTRIM(RTRIM({quoted_col}))'
                    else:
                        # PostgreSQL, MySQL, and ClickHouse use TRIM()
                        transformed = f'TRIM({quoted_col})'
                elif transformation == 'UPPER':
                    transformed = f'UPPER({quoted_col})'
                elif transformation == 'LOWER':
                    transformed = f'LOWER({quoted_col})'
                else:
                    transformed = quoted_col
                
                # Add AS clause to preserve column name
                transformed_cols.append(f'{transformed} AS {quoted_col}')
            else:
                # No transformation, use original with proper quoting
                if db_type == 'postgres':
                    transformed_cols.append(f'"{col}"')
                elif db_type == 'mysql':
                    transformed_cols.append(f'`{col}`')
                elif db_type == 'sqlserver':
                    transformed_cols.append(f'[{col}]')
                elif db_type == 'clickhouse':
                    transformed_cols.append(f'`{col}`')
                else:
                    transformed_cols.append(col)
        
        return ', '.join(transformed_cols)
    
    @staticmethod
    def _normalize_where_clause_column_quotes(where_clause: str, db_type: str) -> str:
        """
        Normalize column name quotes in WHERE clause to match database type
        
        Users might enter PostgreSQL-style quotes ("column") but source might be MySQL (needs `column`)
        or SQL Server (needs [column]). This function converts quotes to match the target database.
        
        Args:
            where_clause: WHERE clause string (e.g., "price" > 20 or price > 20)
            db_type: Target database type ('postgres', 'mysql', 'sqlserver')
            
        Returns:
            Normalized WHERE clause with correct quotes for the database type
            
        Examples:
            Input: "price" > 20, db_type: 'mysql'  -> Output: `price` > 20
            Input: "price" > 20, db_type: 'sqlserver'  -> Output: [price] > 20
            Input: `price` > 20, db_type: 'postgres'  -> Output: "price" > 20
        """
        if not where_clause:
            return where_clause
        
        # Handle Mock objects or non-string types
        if not isinstance(where_clause, str):
            return str(where_clause) if where_clause else ""
        
        # Replace PostgreSQL-style quotes (") with target database quotes
        if db_type == 'postgres':
            # Replace backticks and brackets with double quotes
            where_clause = re.sub(r'`([^`]+)`', r'"\1"', where_clause)  # `col` -> "col"
            where_clause = re.sub(r'\[([^\]]+)\]', r'"\1"', where_clause)  # [col] -> "col"
        elif db_type == 'oracle':
            # Oracle uses double quotes for identifiers, same normalization as PostgreSQL
            where_clause = re.sub(r'`([^`]+)`', r'"\1"', where_clause)  # `col` -> "col"
            where_clause = re.sub(r'\[([^\]]+)\]', r'"\1"', where_clause)  # [col] -> "col"
        elif db_type == 'mysql':
            # Replace double quotes and brackets with backticks
            where_clause = re.sub(r'"([^"]+)"', r'`\1`', where_clause)  # "col" -> `col`
            where_clause = re.sub(r'\[([^\]]+)\]', r'`\1`', where_clause)  # [col] -> `col`
        elif db_type == 'sqlserver':
            # Replace double quotes and backticks with brackets
            where_clause = re.sub(r'"([^"]+)"', r'[\1]', where_clause)  # "col" -> [col]
            where_clause = re.sub(r'`([^`]+)`', r'[\1]', where_clause)  # `col` -> [col]
        elif db_type == 'clickhouse':
            # Replace double quotes and brackets with backticks
            where_clause = re.sub(r'"([^"]+)"', r'`\1`', where_clause)  # "col" -> `col`
            where_clause = re.sub(r'\[([^\]]+)\]', r'`\1`', where_clause)  # [col] -> `col`
        
        return where_clause

