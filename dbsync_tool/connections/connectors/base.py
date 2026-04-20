"""
Base connector class for database operations
All database-specific connectors inherit from this class
"""
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
import pandas as pd


@dataclass
class ColumnInfo:
    """
    Data class to represent column information
    """
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool = False
    max_length: Optional[int] = None
    default_value: Optional[str] = None


class DBConnector(ABC):
    """
    Abstract base class for database connectors
    All database-specific connectors must implement these methods
    """
    
    def __init__(self, host: str, port: int, username: str, password: str, database_name: Optional[str] = None):
        """
        Initialize connector with connection parameters
        
        Args:
            host: Database host address
            port: Database port number
            username: Database username
            password: Database password (plaintext)
            database_name: Database name (optional, for listing databases)
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database_name = database_name
        self._connection = None
    
    @abstractmethod
    def connect(self):
        """
        Establish database connection
        Should set self._connection to the connection object
        
        Raises:
            DatabaseConnectionError: If connection fails
        """
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test if connection is successful
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_schemas(self) -> List[str]:
        """
        Get list of schema names (or database names for MySQL)
        
        Returns:
            List[str]: List of schema/database names
        """
        pass
    
    @abstractmethod
    def list_databases(self) -> List[str]:
        """
        Get list of all databases on the server
        This method connects without specifying a database to list all available databases
        
        Returns:
            List[str]: List of database names (filtered to exclude system databases)
        """
        pass
    
    @abstractmethod
    def get_tables(self, schema: str) -> List[str]:
        """
        Get list of table names in a schema
        
        Args:
            schema: Schema/database name
            
        Returns:
            List[str]: List of table names
        """
        pass
    
    @abstractmethod
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """
        Get column information for a table
        
        Args:
            schema: Schema/database name
            table: Table name
            
        Returns:
            List[ColumnInfo]: List of column information objects
        """
        pass
    
    @abstractmethod
    def get_row_count(self, schema: str, table: str) -> int:
        """
        Get row count for a table
        
        Args:
            schema: Schema/database name
            table: Table name
            
        Returns:
            int: Number of rows in the table
        """
        pass
    
    @abstractmethod
    def fetch_batch(self, query: str, batch_size: int, offset: int = 0, order_by: Optional[str] = None) -> List[Tuple]:
        """
        Fetch a batch of rows from a query
        
        Args:
            query: SQL query to execute
            batch_size: Number of rows to fetch
            offset: Number of rows to skip
            order_by: Optional ORDER BY clause (if not in query)
            
        Returns:
            List[Tuple]: List of row tuples
        """
        pass
    
    @abstractmethod
    def get_query_row_count(self, query: str) -> int:
        """
        Get total row count for a query (for progress tracking)
        
        Args:
            query: SQL query (SELECT statement)
        
        Returns:
            Total number of rows that would be returned by query
        """
        pass
    
    @abstractmethod
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        """
        Execute a query (INSERT, UPDATE, DELETE, etc.)
        
        Args:
            query: SQL query to execute
            params: Optional query parameters
            
        Returns:
            Cursor or result object
        """
        pass

    def execute_query_fetchall(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple]:
        """
        Execute a SELECT query and return all rows.

        This exists because some connectors' `execute_query()` implementations
        close the cursor before returning (so `cursor.fetchall()` can't be
        called by the caller).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.execute_query_fetchall is not implemented"
        )

    def get_database_size_bytes(self) -> Optional[int]:
        """
        Return the whole-database allocated/logical size in bytes.

        Default returns None, meaning "not supported / cannot compute".
        Concrete connectors override this with engine-specific queries.
        Implementations MUST swallow their own errors and return None on failure.
        """
        return None

    def get_table_size_bytes(self, schema: str, table: str) -> Optional[int]:
        """
        Return the size of a single table in bytes (including indexes if the
        engine reports them together, to stay apples-to-apples per engine).

        Default returns None. Implementations MUST return None on failure.
        """
        return None
    
    @abstractmethod
    def create_table(self, schema: str, table: str, columns: List[ColumnInfo]):
        """
        Create a table in the target database
        
        Args:
            schema: Schema/database name
            table: Table name
            columns: List of ColumnInfo objects
        """
        pass
    
    @abstractmethod
    def table_exists(self, schema: str, table: str) -> bool:
        """
        Check if table exists
        
        Args:
            schema: Schema/database name
            table: Table name
            
        Returns:
            bool: True if table exists, False otherwise
        """
        pass
    
    @abstractmethod
    def truncate_table(self, schema: str, table: str):
        """
        Truncate a table (remove all rows)
        
        Args:
            schema: Schema/database name
            table: Table name
        """
        pass
    
    @abstractmethod
    def bulk_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]):
        """
        Bulk insert rows into a table
        
        Args:
            schema: Schema/database name
            table: Table name
            columns: List of column names
            rows: List of row tuples to insert
        """
        pass
    
    @abstractmethod
    def ensure_schema_exists(self, schema: str):
        """
        Ensure schema exists, create if not
        
        Args:
            schema: Schema/database name to ensure exists
        """
        pass
    
    @abstractmethod
    def get_primary_key(self, schema: str, table: str) -> List[str]:
        """
        Get primary key column names for a table
        
        Args:
            schema: Schema/database name
            table: Table name
        
        Returns:
            List of primary key column names (empty list if no PK)
        """
        pass
    
    def close(self):
        """Close database connection"""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass  # Ignore errors during close
            finally:
                self._connection = None
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        self.close()
    
    @abstractmethod
    def create_table_from_dataframe(self, schema: str, table: str, df: pd.DataFrame):
        """
        Create a table from a pandas DataFrame
        
        Args:
            schema: Schema/database name
            table: Table name
            df: DataFrame with data structure
        """
        pass
    
    @abstractmethod
    def add_missing_columns(self, schema: str, table: str, df: pd.DataFrame):
        """
        Add missing columns to an existing table based on DataFrame
        
        Args:
            schema: Schema/database name
            table: Table name
            df: DataFrame with new columns
        """
        pass
    
    @abstractmethod
    def upsert_dataframe(
        self, 
        schema: str, 
        table: str, 
        df: pd.DataFrame, 
        key_column: str
    ):
        """
        Upsert (insert or update) DataFrame rows into table
        
        Args:
            schema: Schema/database name
            table: Table name
            df: DataFrame with data
            key_column: Primary key or unique identifier column name
        """
        pass

