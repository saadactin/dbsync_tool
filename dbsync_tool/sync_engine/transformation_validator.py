"""
Validation service for transformation configurations

Prevents:
- SQL injection attacks
- Invalid column references
- Invalid transformation functions
"""
from typing import Optional, Tuple, Dict
from connections.connectors.base import DBConnector
import logging

logger = logging.getLogger(__name__)


class TransformationValidator:
    """
    Validates transformation configurations before application
    
    Prevents:
    - SQL injection attacks
    - Invalid column references
    - Invalid transformation functions
    """
    
    # Allowed transformation functions (Phase 1)
    ALLOWED_TRANSFORMATIONS = {'TRIM', 'UPPER', 'LOWER'}
    
    # Dangerous SQL keywords that should not appear in WHERE clauses
    DANGEROUS_KEYWORDS = {
        'DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER', 'CREATE', 
        'TRUNCATE', 'EXEC', 'EXECUTE', 'DECLARE', 'CURSOR'
    }
    
    def validate_where_clause(
        self,
        where_clause: str,
        schema: str,
        table: str,
        connector: DBConnector
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate WHERE clause syntax and security
        
        Args:
            where_clause: WHERE clause string (without WHERE keyword)
            schema: Schema name
            table: Table name
            connector: Database connector instance
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not where_clause or not where_clause.strip():
            return False, "WHERE clause cannot be empty"
        
        # Check for SQL injection patterns
        if self._check_sql_injection(where_clause):
            return False, "WHERE clause contains potentially dangerous SQL patterns"
        
        # Verify table/schema exists (basic check)
        try:
            tables = connector.get_tables(schema)
            if table not in tables:
                return False, f"Table '{table}' does not exist in schema '{schema}'"
        except Exception as e:
            logger.warning(f"Could not verify table existence: {str(e)}")
            # Don't fail validation if we can't verify, but log warning
        
        return True, None
    
    def validate_column_transformations(
        self,
        transformations: Dict[str, str],
        schema: str,
        table: str,
        connector: DBConnector
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate column transformations
        
        Checks:
        - Columns exist in table
        - Transformation functions are valid
        - No SQL injection patterns in column names
        
        Args:
            transformations: Dict mapping column_name -> transformation_type
            schema: Schema name
            table: Table name
            connector: Database connector instance
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not transformations:
            return True, None
        
        # Get table columns
        try:
            columns = connector.get_columns(schema, table)
            if not columns:
                return False, f"Table {schema}.{table} has no columns"
            
            column_names = {col.name for col in columns}
        except Exception as e:
            return False, f"Failed to get columns from table {schema}.{table}: {str(e)}"
        
        # Validate each transformation
        for col_name, transformation in transformations.items():
            # Check for SQL injection in column name
            if self._check_sql_injection(col_name):
                return False, f"Column name '{col_name}' contains potentially dangerous patterns"
            
            # Check column exists
            if col_name not in column_names:
                return False, f"Column '{col_name}' does not exist in table {schema}.{table}"
            
            # Check transformation function is valid
            if not self._validate_transformation_function(transformation):
                return False, (
                    f"Invalid transformation '{transformation}' for column '{col_name}'. "
                    f"Allowed: {', '.join(self.ALLOWED_TRANSFORMATIONS)}"
                )
        
        return True, None
    
    def _check_sql_injection(self, clause: str) -> bool:
        """
        Basic SQL injection detection
        
        Checks for dangerous patterns:
        - DROP, DELETE, INSERT, UPDATE statements
        - Semicolons (statement termination)
        - Comments (--, /*)
        - UNION, SELECT in suspicious contexts
        
        Args:
            clause: SQL clause to check
            
        Returns:
            True if potentially dangerous patterns detected, False otherwise
        """
        if not clause:
            return False
        
        clause_upper = clause.upper().strip()
        
        # Check for dangerous keywords
        for keyword in self.DANGEROUS_KEYWORDS:
            if keyword in clause_upper:
                # Allow if it's part of a column name (e.g., "user_id" contains "user")
                # Simple heuristic: check if keyword is surrounded by word boundaries
                import re
                pattern = r'\b' + re.escape(keyword) + r'\b'
                if re.search(pattern, clause_upper):
                    return True
        
        # Check for statement terminators
        if ';' in clause:
            return True
        
        # Check for SQL comments
        if '--' in clause or '/*' in clause:
            return True
        
        # Check for UNION SELECT (potential injection)
        if 'UNION' in clause_upper and 'SELECT' in clause_upper:
            # This is a heuristic - UNION SELECT in WHERE clause is suspicious
            return True
        
        return False
    
    def _validate_transformation_function(self, func: str) -> bool:
        """
        Validate transformation function name
        
        Args:
            func: Transformation function name
            
        Returns:
            True if valid, False otherwise
        """
        if not func:
            return False
        
        return func.upper() in self.ALLOWED_TRANSFORMATIONS
