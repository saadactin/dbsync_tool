"""
Table creation and management utilities
"""
from typing import List, Optional
from connections.connectors.base import DBConnector, ColumnInfo
from core.type_mapping import map_data_type
from sync_engine.exceptions import SchemaCreationError, TableCreationError
import logging

logger = logging.getLogger(__name__)

class TableHandler:
    """Handles table creation and schema management"""
    
    def __init__(self, source_connector: DBConnector, target_connector: DBConnector):
        """
        Initialize table handler
        
        Args:
            source_connector: Source database connector
            target_connector: Target database connector
        """
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.source_db_type = self._get_db_type(source_connector)
        self.target_db_type = self._get_db_type(target_connector)
    
    def _get_db_type(self, connector: DBConnector) -> str:
        """Extract database type from connector class name"""
        class_name = connector.__class__.__name__
        if 'Postgres' in class_name:
            return 'postgres'
        elif 'MySQL' in class_name:
            return 'mysql'
        elif 'SQLServer' in class_name:
            return 'sqlserver'
        else:
            raise ValueError(f"Unknown connector type: {class_name}")
    
    def ensure_schema_exists(self, schema: str):
        """
        Ensure target schema exists, create if not
        
        Args:
            schema: Schema/database name to ensure exists
            
        Raises:
            SchemaCreationError: If schema creation fails
        """
        try:
            # For MySQL targets: no schema concept, skip schema creation
            if self.target_db_type == 'mysql':
                logger.info(f"MySQL doesn't use schemas - skipping schema creation for {schema}")
                return
            
            # For PostgreSQL and SQL Server: ensure the target schema exists
            # PostgreSQL: always use 'public'
            # SQL Server: always use 'dbo'
            if self.target_db_type == 'postgres':
                target_schema = 'public'
            elif self.target_db_type == 'sqlserver':
                target_schema = 'dbo'
            else:
                target_schema = schema
            
            self.target_connector.ensure_schema_exists(target_schema)
            logger.info(f"Schema {target_schema} ensured in target database")
        except Exception as e:
            raise SchemaCreationError(f"Failed to create schema {target_schema}: {str(e)}")
    
    def create_table_if_not_exists(
        self,
        schema: str,
        table: str,
        source_schema: Optional[str] = None
    ) -> bool:
        """
        Create target table if it doesn't exist
        
        Args:
            schema: Target schema name
            table: Target table name
            source_schema: Source schema name (if different from target)
            
        Returns:
            bool: True if table was created, False if it already existed
            
        Raises:
            TableCreationError: If table creation fails
        """
        if source_schema is None:
            source_schema = schema
        
        # Schema mapping for different database combinations
        # For databases WITH schemas (PostgreSQL, SQL Server): always use target's default schema
        # For databases WITHOUT schemas (MySQL): use database name directly
        target_schema = schema
        if self.target_db_type == 'mysql':
            # MySQL doesn't have schemas - use database name directly
            target_schema = self.target_connector.database_name
            logger.info(f"Mapping source schema '{schema}' to MySQL database '{target_schema}' (no schema concept in MySQL)")
        elif self.target_db_type == 'postgres':
            # PostgreSQL: Always use 'public' schema regardless of source schema
            target_schema = 'public'
            logger.info(f"Mapping source schema '{schema}' to PostgreSQL schema 'public' (all tables in public schema)")
        elif self.target_db_type == 'sqlserver':
            # SQL Server: Always use 'dbo' schema regardless of source schema
            target_schema = 'dbo'
            logger.info(f"Mapping source schema '{schema}' to SQL Server schema 'dbo' (all tables in dbo schema)")
        
        # Check if table exists (with error handling for transaction issues)
        try:
            if self.target_connector.table_exists(target_schema, table):
                logger.info(f"Table {target_schema}.{table} already exists in target")
                return False
        except Exception as e:
            # If table_exists fails, log warning but continue (might be transaction error)
            logger.warning(f"Error checking if table exists {target_schema}.{table}: {str(e)}. Will attempt to create.")
        
        # Ensure schema exists
        self.ensure_schema_exists(target_schema)
        
        # Get source table columns (with transaction error handling)
        try:
            source_columns = self.source_connector.get_columns(source_schema, table)
        except Exception as e:
            raise TableCreationError(
                f"Failed to get source columns for {source_schema}.{table}: {str(e)}"
            )
        
        if not source_columns:
            raise TableCreationError(
                f"No columns found for source table {source_schema}.{table}"
            )
        
        # Map columns to target database types
        target_columns = []
        for col in source_columns:
            mapped_type = map_data_type(
                source_type=col.data_type,
                source_db=self.source_db_type,
                target_db=self.target_db_type,
                max_length=col.max_length
            )
            
            # For AUTO_INCREMENT columns in MySQL, clear default_value
            # MySQL handles auto-increment internally, default values are not allowed
            # For IDENTITY columns in SQL Server, also clear default_value
            default_value = col.default_value
            if self.target_db_type == 'mysql' and 'AUTO_INCREMENT' in mapped_type.upper():
                default_value = None
                logger.debug(f"Clearing default value for AUTO_INCREMENT column {col.name} (mapped type: {mapped_type})")
            elif self.target_db_type == 'sqlserver' and 'IDENTITY' in mapped_type.upper():
                default_value = None
                logger.debug(f"Clearing default value for IDENTITY column {col.name} (mapped type: {mapped_type})")
            
            target_col = ColumnInfo(
                name=col.name,
                data_type=mapped_type,
                is_nullable=col.is_nullable,
                is_primary_key=col.is_primary_key,
                max_length=col.max_length,
                default_value=default_value
            )
            target_columns.append(target_col)
        
        # Create table
        try:
            # Use target_schema (which is already set above for MySQL targets)
            self.target_connector.create_table(target_schema, table, target_columns)
            logger.info(f"Created table {target_schema}.{table} in target database")
            return True
        except Exception as e:
            raise TableCreationError(
                f"Failed to create table {target_schema}.{table}: {str(e)}"
            )
    
    def get_table_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """
        Get columns for a table
        
        Args:
            schema: Schema name
            table: Table name
            
        Returns:
            List of ColumnInfo objects
        """
        return self.target_connector.get_columns(schema, table)
    
    def verify_table_structure(
        self,
        source_schema: str,
        source_table: str,
        target_schema: str,
        target_table: str
    ) -> bool:
        """
        Verify that target table structure matches source (column names)
        
        Args:
            source_schema: Source schema name
            source_table: Source table name
            target_schema: Target schema name
            target_table: Target table name
            
        Returns:
            bool: True if structures match
        """
        source_columns = self.source_connector.get_columns(source_schema, source_table)
        target_columns = self.target_connector.get_columns(target_schema, target_table)
        
        source_col_names = {col.name for col in source_columns}
        target_col_names = {col.name for col in target_columns}
        
        return source_col_names == target_col_names

