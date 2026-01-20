"""
Transformation engine for applying data transformations during sync

Supports:
- WHERE clause filtering (applied in SQL)
- Column transformations: TRIM, UPPER, LOWER (applied in SQL SELECT or Python)
- Database-agnostic implementation
"""
from typing import Optional, Dict, List, Tuple, Any
from connections.connectors.base import DBConnector
from sync_engine.query_builder import QueryBuilder
from sync_engine.exceptions import QueryBuilderError
import logging

logger = logging.getLogger(__name__)


class TransformationEngine:
    """
    Engine for applying data transformations during sync
    
    Supports:
    - WHERE clause filtering (applied in SQL)
    - Column transformations: TRIM, UPPER, LOWER (applied in SQL SELECT or Python)
    - Database-agnostic implementation
    """
    
    # Allowed transformation functions (Phase 1)
    ALLOWED_TRANSFORMATIONS = {'TRIM', 'UPPER', 'LOWER'}
    
    def apply_query_transformations(
        self,
        query: str,
        where_clause: Optional[str] = None,
        column_transformations: Optional[Dict[str, str]] = None,
        connector: DBConnector = None
    ) -> str:
        """
        Apply WHERE clause and column transformations to SQL query
        
        Args:
            query: Base SQL query (SELECT ... FROM ...)
            where_clause: Optional WHERE clause to append
            column_transformations: Optional dict mapping column_name -> transformation_type
            connector: Database connector instance (required for column transformations)
            
        Returns:
            Modified query with transformations applied
            
        Raises:
            QueryBuilderError: If connector is required but not provided
        """
        if not query:
            return query
        
        # Apply WHERE clause if provided
        if where_clause:
            # Check if query already has WHERE clause
            query_upper = query.upper()
            if ' WHERE ' in query_upper:
                # Combine with AND
                query += f' AND {where_clause}'
            else:
                query += f' WHERE {where_clause}'
        
        # Apply column transformations if provided
        if column_transformations and connector:
            query = self._apply_column_transformations_to_query(
                query, column_transformations, connector
            )
        
        return query
    
    def _apply_column_transformations_to_query(
        self,
        query: str,
        column_transformations: Dict[str, str],
        connector: DBConnector
    ) -> str:
        """
        Apply column transformations to SELECT clause of query
        
        Args:
            query: SQL query string
            column_transformations: Dict mapping column_name -> transformation_type
            connector: Database connector instance
            
        Returns:
            Modified query with column transformations in SELECT clause
        """
        db_type = QueryBuilder.get_db_type(connector)
        
        # Extract SELECT clause
        query_upper = query.upper()
        select_idx = query_upper.find('SELECT')
        from_idx = query_upper.find(' FROM')
        
        if select_idx == -1 or from_idx == -1:
            # Malformed query, return as-is
            logger.warning(f"Could not parse query for column transformations: {query}")
            return query
        
        select_clause = query[select_idx + 6:from_idx].strip()
        rest_of_query = query[from_idx:]
        
        # Parse existing columns
        if select_clause == '*':
            # Can't transform * - need column list
            logger.warning("Cannot apply column transformations to SELECT * - column list required")
            return query
        
        # Split columns by comma (handle quoted identifiers)
        columns = self._parse_column_list(select_clause, db_type)
        
        # Apply transformations
        transformed_columns = []
        for col in columns:
            col_name = self._unquote_column(col, db_type)
            if col_name in column_transformations:
                transformation = column_transformations[col_name].upper()
                if transformation in self.ALLOWED_TRANSFORMATIONS:
                    transformed_col = self._apply_column_transformation_to_select(
                        col_name, transformation, db_type
                    )
                    transformed_columns.append(transformed_col)
                else:
                    # Invalid transformation, use original column
                    logger.warning(f"Invalid transformation '{transformation}' for column '{col_name}', skipping")
                    transformed_columns.append(col)
            else:
                # No transformation, use original
                transformed_columns.append(col)
        
        # Rebuild query
        new_select_clause = ', '.join(transformed_columns)
        return f'SELECT {new_select_clause}{rest_of_query}'
    
    def _parse_column_list(self, select_clause: str, db_type: str) -> List[str]:
        """
        Parse column list from SELECT clause, handling quoted identifiers
        
        Args:
            select_clause: SELECT clause string (e.g., '"col1", "col2"')
            db_type: Database type
            
        Returns:
            List of column identifiers (may be quoted)
        """
        columns = []
        current_col = ''
        in_quotes = False
        quote_char = None
        close_char = None
        
        # Determine quote characters based on DB type
        if db_type == 'postgres':
            quote_char = '"'
            close_char = '"'
        elif db_type == 'mysql':
            quote_char = '`'
            close_char = '`'
        elif db_type == 'sqlserver':
            quote_char = '['
            close_char = ']'
        
        i = 0
        while i < len(select_clause):
            char = select_clause[i]
            
            if not in_quotes:
                if char == quote_char:
                    in_quotes = True
                    current_col += char
                elif char == ',':
                    if current_col.strip():
                        columns.append(current_col.strip())
                    current_col = ''
                else:
                    current_col += char
            else:
                current_col += char
                if char == close_char:
                    # Check if it's closing quote (not escaped)
                    if db_type == 'sqlserver':
                        # SQL Server uses [] brackets, no escaping needed
                        in_quotes = False
                    elif i + 1 < len(select_clause) and select_clause[i + 1] == quote_char:
                        # Escaped quote (for postgres/mysql)
                        current_col += select_clause[i + 1]
                        i += 1
                    else:
                        # Closing quote
                        in_quotes = False
            
            i += 1
        
        if current_col.strip():
            columns.append(current_col.strip())
        
        return columns
    
    def _unquote_column(self, column: str, db_type: str) -> str:
        """
        Remove quotes from column identifier
        
        Args:
            column: Column identifier (may be quoted)
            db_type: Database type
            
        Returns:
            Unquoted column name
        """
        if db_type == 'postgres':
            if column.startswith('"') and column.endswith('"'):
                return column[1:-1]
        elif db_type == 'mysql':
            if column.startswith('`') and column.endswith('`'):
                return column[1:-1]
        elif db_type == 'sqlserver':
            if column.startswith('[') and column.endswith(']'):
                return column[1:-1]
        
        return column
    
    def _apply_column_transformation_to_select(
        self,
        column: str,
        transformation: str,
        db_type: str
    ) -> str:
        """
        Generate database-specific SQL for column transformation in SELECT clause
        
        Args:
            column: Column name (unquoted)
            transformation: Transformation type (TRIM, UPPER, LOWER)
            db_type: Database type ('postgres', 'mysql', 'sqlserver')
            
        Returns:
            Formatted SELECT clause expression with transformation applied
            
        Examples:
            - PostgreSQL: TRIM("name") AS "name"
            - MySQL: TRIM(`name`) AS `name`
            - SQL Server: LTRIM(RTRIM([name])) AS [name]
        """
        transformation = transformation.upper()
        
        # Quote column based on DB type
        if db_type == 'postgres':
            quoted_col = f'"{column}"'
        elif db_type == 'mysql':
            quoted_col = f'`{column}`'
        elif db_type == 'sqlserver':
            quoted_col = f'[{column}]'
        else:
            quoted_col = column
        
        # Apply transformation
        if transformation == 'TRIM':
            if db_type == 'sqlserver':
                # SQL Server uses LTRIM(RTRIM())
                transformed = f'LTRIM(RTRIM({quoted_col}))'
            else:
                # PostgreSQL and MySQL use TRIM()
                transformed = f'TRIM({quoted_col})'
        elif transformation == 'UPPER':
            transformed = f'UPPER({quoted_col})'
        elif transformation == 'LOWER':
            transformed = f'LOWER({quoted_col})'
        else:
            # Unknown transformation, return original
            logger.warning(f"Unknown transformation '{transformation}', using original column")
            return quoted_col
        
        # Add AS clause to preserve column name
        return f'{transformed} AS {quoted_col}'
    
    def apply_row_transformations(
        self,
        batch: List[tuple],
        column_names: List[str],
        column_transformations: Dict[str, str]
    ) -> List[tuple]:
        """
        Apply Python-based transformations to fetched rows
        
        Used for transformations that cannot be applied in SQL or as fallback
        
        Args:
            batch: List of row tuples
            column_names: List of column names in order
            column_transformations: Dict mapping column_name -> transformation_type
            
        Returns:
            Transformed batch with same structure
        """
        if not batch or not column_transformations:
            return batch
        
        # Create column index map
        col_index_map = {col: idx for idx, col in enumerate(column_names)}
        
        transformed_batch = []
        for row in batch:
            transformed_row = list(row)
            
            for col_name, transformation in column_transformations.items():
                if col_name not in col_index_map:
                    continue
                
                col_idx = col_index_map[col_name]
                original_value = row[col_idx]
                
                # Skip NULL values
                if original_value is None:
                    continue
                
                # Apply transformation
                transformation = transformation.upper()
                if transformation == 'TRIM' and isinstance(original_value, str):
                    transformed_row[col_idx] = original_value.strip()
                elif transformation == 'UPPER' and isinstance(original_value, str):
                    transformed_row[col_idx] = original_value.upper()
                elif transformation == 'LOWER' and isinstance(original_value, str):
                    transformed_row[col_idx] = original_value.lower()
                # If transformation doesn't apply (wrong type), keep original
            
            transformed_batch.append(tuple(transformed_row))
        
        return transformed_batch
    
    def validate_transformations(
        self,
        schema: str,
        table: str,
        where_clause: Optional[str] = None,
        column_transformations: Optional[Dict[str, str]] = None,
        connector: DBConnector = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate transformation configuration
        
        Args:
            schema: Schema name
            table: Table name
            where_clause: Optional WHERE clause
            column_transformations: Optional column transformations dict
            connector: Database connector instance (required for validation)
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not connector:
            return False, "Connector is required for validation"
        
        # Validate WHERE clause if provided
        if where_clause:
            # Basic validation - check for dangerous patterns
            dangerous_keywords = ['DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER', 'CREATE', 'TRUNCATE']
            where_upper = where_clause.upper()
            for keyword in dangerous_keywords:
                if keyword in where_upper:
                    return False, f"WHERE clause contains dangerous keyword: {keyword}"
            
            # Check for statement terminators
            if ';' in where_clause:
                return False, "WHERE clause contains statement terminator (;)"
            
            # Check for comments
            if '--' in where_clause or '/*' in where_clause:
                return False, "WHERE clause contains SQL comments"
        
        # Validate column transformations if provided
        if column_transformations:
            # Get table columns
            try:
                columns = connector.get_columns(schema, table)
                if not columns:
                    return False, f"Table {schema}.{table} has no columns"
                
                column_names = {col.name for col in columns}
            except Exception as e:
                return False, f"Failed to get columns from table {schema}.{table}: {str(e)}"
            
            # Validate each transformation
            for col_name, transformation in column_transformations.items():
                # Check column exists
                if col_name not in column_names:
                    return False, f"Column '{col_name}' does not exist in table {schema}.{table}"
                
                # Check transformation is valid
                transformation_upper = transformation.upper()
                if transformation_upper not in self.ALLOWED_TRANSFORMATIONS:
                    return False, f"Invalid transformation '{transformation}'. Allowed: {', '.join(self.ALLOWED_TRANSFORMATIONS)}"
        
        return True, None
