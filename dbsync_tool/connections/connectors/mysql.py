"""
MySQL database connector implementation
"""
import mysql.connector
from mysql.connector import Error
from typing import List, Tuple, Optional, Dict, Any
from .base import DBConnector, ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError
from core.type_mapping import map_data_type
from decimal import Decimal
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)


class MySQLConnector(DBConnector):
    """MySQL database connector"""
    
    def connect(self):
        """Establish MySQL connection with enhanced error handling"""
        try:
            # MySQL can connect without database_name parameter
            connect_params = {
                'host': self.host,
                'port': self.port,
                'user': self.username,
                'password': self.password,
                'connection_timeout': 10,
                'autocommit': False
            }
            if self.database_name:
                connect_params['database'] = self.database_name
            self._connection = mysql.connector.connect(**connect_params)
            return self._connection
        except Error as e:
            error_msg = str(e).lower()
            error_code = e.errno if hasattr(e, 'errno') else None
            
            # Provide specific error messages
            if error_code == 2003 or 'timeout' in error_msg or 'timed out' in error_msg:
                from core.exceptions import DatabaseTimeoutError
                raise DatabaseTimeoutError(f"Connection timeout: Unable to reach MySQL server at {self.host}:{self.port}")
            elif error_code == 1045 or 'access denied' in error_msg or 'password' in error_msg:
                raise DatabaseConnectionError("Connection failed: Invalid credentials. Please check your username and password.")
            elif error_code == 2002 or 'could not connect' in error_msg or 'connection refused' in error_msg:
                raise DatabaseConnectionError(f"Connection failed: Host unreachable. Unable to connect to {self.host}:{self.port}")
            elif error_code == 1049 or ('database' in error_msg and 'does not exist' in error_msg):
                raise DatabaseConnectionError(f"Connection failed: Database '{self.database_name}' not found.")
            elif 'port' in error_msg:
                raise DatabaseConnectionError(f"Connection failed: Port {self.port} is not accessible.")
            else:
                raise DatabaseConnectionError(f"Connection failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to MySQL: {str(e)}", exc_info=True)
            raise DatabaseConnectionError(f"Unexpected error connecting to MySQL: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test MySQL connection with timeout handling"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return True
        except DatabaseConnectionError:
            # Re-raise connection errors
            raise
        except Exception as e:
            logger.error(f"Error testing MySQL connection: {str(e)}", exc_info=True)
            raise DatabaseConnectionError(f"Connection test failed: {str(e)}")
    
    def get_schemas(self) -> List[str]:
        """Get list of database names (MySQL uses databases like schemas)"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute("SHOW DATABASES")
        databases = [row[0] for row in cursor.fetchall()]
        cursor.close()
        
        # Filter out system databases
        exclude = ['information_schema', 'performance_schema', 'mysql', 'sys']
        return [db for db in databases if db not in exclude]
    
    def list_databases(self) -> List[str]:
        """Get list of all databases on the MySQL server"""
        try:
            if not self._connection:
                self.connect()
            
            cursor = self._connection.cursor()
            cursor.execute("SHOW DATABASES")
            databases = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            # Filter out system databases
            exclude = ['information_schema', 'performance_schema', 'mysql', 'sys']
            return [db for db in databases if db not in exclude]
        except Error as e:
            raise DatabaseConnectionError(f"Failed to list databases: {str(e)}")
        except Exception as e:
            raise DatabaseConnectionError(f"Unexpected error listing databases: {str(e)}")
    
    def get_tables(self, schema: str) -> List[str]:
        """Get list of table names in a database"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute(f"USE `{schema}`")
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return tables
    
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Get column information for a table"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute(f"USE `{schema}`")
        
        # Verify table exists
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = %s AND table_name = %s
        """, (schema, table))
        if cursor.fetchone()[0] == 0:
            cursor.close()
            raise TableNotFoundError(f"Table {schema}.{table} does not exist")
        
        # Get column information
        cursor.execute("""
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                IS_NULLABLE,
                COLUMN_KEY,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (schema, table))
        
        columns = []
        for row in cursor.fetchall():
            col_name, data_type, max_length, is_nullable, col_key, default_value = row
            columns.append(ColumnInfo(
                name=col_name,
                data_type=data_type,
                is_nullable=is_nullable == 'YES',
                is_primary_key=col_key == 'PRI',
                max_length=max_length,
                default_value=default_value
            ))
        cursor.close()
        return columns
    
    def get_row_count(self, schema: str, table: str) -> int:
        """Get row count for a table"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute(f"USE `{schema}`")
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        count = cursor.fetchone()[0]
        cursor.close()
        return count
    
    def fetch_batch(self, query: str, batch_size: int, offset: int = 0, order_by: Optional[str] = None) -> List[Tuple]:
        """Fetch batch with proper ordering"""
        if not self._connection:
            self.connect()
        
        query_upper = query.upper()
        if order_by and 'ORDER BY' not in query_upper:
            query = f"{query} ORDER BY {order_by}"
        elif 'ORDER BY' not in query_upper:
            logger.warning(f"Query without ORDER BY: {query}")
        
        paginated_query = f"{query} LIMIT {batch_size} OFFSET {offset}"
        
        cursor = self._connection.cursor()
        cursor.execute(paginated_query)
        result = cursor.fetchall()
        cursor.close()
        return result
    
    def get_query_row_count(self, query: str) -> int:
        """Get total row count for a query (for progress tracking)"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        # Wrap query in COUNT(*)
        count_query = f"SELECT COUNT(*) FROM ({query}) AS subquery"
        cursor.execute(count_query)
        result = cursor.fetchone()[0]
        cursor.close()
        return result
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        """Execute a query"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        self._connection.commit()
        cursor.close()
        return cursor
    
    def _format_default_value(self, default_value: str, data_type: str) -> str:
        """
        Format default value for MySQL
        
        Args:
            default_value: The default value string
            data_type: The column data type
            
        Returns:
            Formatted default value string, or empty string if should be skipped
        """
        if not default_value:
            return ''
        
        default_value = default_value.strip()
        
        # Skip PostgreSQL sequence defaults (nextval(...) syntax) - handled by AUTO_INCREMENT
        if 'nextval' in default_value.lower() and '::regclass' in default_value.lower():
            logger.debug(f"Skipping PostgreSQL sequence default: {default_value}")
            return ''
        
        # Skip if column type includes AUTO_INCREMENT - MySQL handles defaults automatically
        if 'AUTO_INCREMENT' in data_type.upper():
            logger.debug(f"Skipping default for AUTO_INCREMENT column with type: {data_type}")
            return ''
        
        # Check if it's a PostgreSQL sequence function
        if 'nextval' in default_value.lower():
            logger.debug(f"Skipping PostgreSQL sequence default: {default_value}")
            return ''
        
        # Check if it's already a function call or expression (but not PostgreSQL-specific)
        if '(' in default_value and ')' in default_value:
            # Allow MySQL-compatible functions
            mysql_functions = ['CURRENT_TIMESTAMP', 'NOW', 'CURDATE', 'CURTIME', 'UNIX_TIMESTAMP']
            if any(func in default_value.upper() for func in mysql_functions):
                return default_value
            # Skip PostgreSQL-specific functions
            pg_functions = ['nextval', 'currval', 'lastval', '::']
            if any(func in default_value.lower() for func in pg_functions):
                logger.debug(f"Skipping PostgreSQL-specific function: {default_value}")
                return ''
            # For other functions, return as-is (might be MySQL compatible)
            return default_value
        
        # Check if it's a MySQL keyword/constant
        mysql_constants = ['CURRENT_TIMESTAMP', 'CURRENT_DATE', 'CURRENT_TIME', 'TRUE', 'FALSE', 'NULL']
        if default_value.upper() in mysql_constants:
            return default_value.upper()
        
        # Check if it's a number
        try:
            float(default_value)
            return default_value
        except ValueError:
            pass
        
        # Check if it's a boolean
        if default_value.upper() in ('TRUE', 'FALSE', '1', '0'):
            if default_value.upper() in ('TRUE', '1'):
                return '1'
            else:
                return '0'
        
        # For text types, quote the value and escape single quotes
        escaped_value = default_value.replace("'", "''").replace("\\", "\\\\")
        return f"'{escaped_value}'"
    
    def create_table(self, schema: str, table: str, columns: List[ColumnInfo], target_db_type: str = 'mysql'):
        """
        Create a table in MySQL
        
        Args:
            schema: Database name (or schema name for cross-database syncs)
            table: Table name
            columns: List of ColumnInfo objects
            target_db_type: Target database type (for type mapping) - defaults to 'mysql'
        """
        if not self._connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self._connection.cursor()
            
            # For cross-database syncs, use the connected database instead of creating new ones
            # This handles PostgreSQL/SQL Server -> MySQL where schemas don't map to databases
            actual_schema = schema
            if schema != self.database_name:
                try:
                    # Try to create and use the schema database
                    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{schema}`")
                    cursor.execute(f"USE `{schema}`")
                    actual_schema = schema
                    self._connection.commit()
                except Exception as e:
                    # If we can't create/use the schema database, use the connected database
                    self._connection.rollback()
                    logger.warning(f"Cannot use database {schema}, using connected database {self.database_name}: {str(e)}")
                    cursor.execute(f"USE `{self.database_name}`")
                    actual_schema = self.database_name
            else:
                # Schema matches connected database, just use it
                cursor.execute(f"USE `{self.database_name}`")
                actual_schema = self.database_name
            
            # Build column definitions using centralized mapping
            column_defs = []
            for col in columns:
                mapped_type = map_data_type(
                    source_type=col.data_type,
                    source_db='mysql',  # Source is mysql for this connector
                    target_db=target_db_type,
                    max_length=col.max_length
                )
                col_def = f"`{col.name}` {mapped_type}"
                if not col.is_nullable:
                    col_def += ' NOT NULL'
                
                # Only add default value if column doesn't have AUTO_INCREMENT
                # AUTO_INCREMENT columns should not have DEFAULT clause in MySQL
                if col.default_value and 'AUTO_INCREMENT' not in mapped_type.upper():
                    formatted_default = self._format_default_value(col.default_value, mapped_type)
                    if formatted_default:
                        col_def += f' DEFAULT {formatted_default}'
                column_defs.append(col_def)
            
            create_query = f"CREATE TABLE IF NOT EXISTS `{table}` ({', '.join(column_defs)}) ENGINE=InnoDB"
            cursor.execute(create_query)
            self._connection.commit()
        except Exception as e:
            if self._connection:
                self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to create table {schema}.{table}: {str(e)}")
        finally:
            if cursor:
                cursor.close()
    
    def table_exists(self, schema: str, table: str) -> bool:
        """Check if table exists"""
        if not self._connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self._connection.cursor()
            
            # For cross-database syncs, check in the connected database if schema doesn't match
            actual_schema = schema
            if schema != self.database_name:
                try:
                    cursor.execute(f"USE `{schema}`")
                    actual_schema = schema
                except Exception:
                    # If we can't use the schema database, check in connected database
                    cursor.execute(f"USE `{self.database_name}`")
                    actual_schema = self.database_name
            else:
                cursor.execute(f"USE `{self.database_name}`")
                actual_schema = self.database_name
            
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            """, (actual_schema, table))
            exists = cursor.fetchone()[0] > 0
            return exists
        except Exception as e:
            # If transaction is in error state, rollback and retry
            try:
                if self._connection:
                    self._connection.rollback()
                if cursor:
                    cursor.close()
                cursor = self._connection.cursor()
                cursor.execute(f"USE `{self.database_name}`")
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = %s AND table_name = %s
                """, (schema, table))
                exists = cursor.fetchone()[0] > 0
                return exists
            except Exception:
                raise DatabaseConnectionError(f"Failed to check if table exists: {str(e)}")
        finally:
            if cursor:
                cursor.close()
    
    def ensure_schema_exists(self, schema: str):
        """
        Ensure database exists in MySQL (schemas are databases)
        
        Note: If schema matches the connected database, we don't need to create it.
        For cross-database syncs (PostgreSQL/SQL Server -> MySQL), we use the 
        connected database instead of creating new databases.
        """
        if not self._connection:
            self.connect()
        
        # If the schema is the same as the connected database, no need to create
        if schema == self.database_name:
            logger.info(f"Schema {schema} matches connected database, no creation needed")
            return
        
        # Try to create the database (may fail due to permissions, but that's okay)
        # For cross-database syncs, we'll use the connected database instead
        try:
            cursor = self._connection.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{schema}`")
            self._connection.commit()
            cursor.close()
            logger.info(f"Created or verified database {schema}")
        except Exception as e:
            logger.warning(f"Could not create database {schema}: {str(e)}. Will use connected database {self.database_name} instead.")
            # Don't raise - we'll use the connected database
    
    def get_primary_key(self, schema: str, table: str) -> List[str]:
        """Get primary key column names for a table"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        
        # Use connected database if schema doesn't match
        actual_schema = schema
        if schema != self.database_name:
            try:
                cursor.execute(f"USE `{schema}`")
                actual_schema = schema
            except Exception:
                # Use connected database instead
                cursor.execute(f"USE `{self.database_name}`")
                actual_schema = self.database_name
        else:
            cursor.execute(f"USE `{self.database_name}`")
            actual_schema = self.database_name
        
        cursor.execute("""
            SELECT column_name
            FROM information_schema.key_column_usage
            WHERE table_schema = %s
                AND table_name = %s
                AND constraint_name = 'PRIMARY'
            ORDER BY ordinal_position
        """, (actual_schema, table))
        result = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return result
    
    def truncate_table(self, schema: str, table: str):
        """Truncate a table"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        
        # Use connected database if schema doesn't match
        if schema != self.database_name:
            try:
                cursor.execute(f"USE `{schema}`")
            except Exception:
                # Use connected database instead
                cursor.execute(f"USE `{self.database_name}`")
        else:
            cursor.execute(f"USE `{self.database_name}`")
        
        cursor.execute(f"TRUNCATE TABLE `{table}`")
        self._connection.commit()
        cursor.close()
    
    def _normalize_row(self, row: Any) -> Tuple:
        """
        Normalize a row to a tuple compatible with MySQL executemany
        
        Handles:
        - Row objects from pyodbc (SQL Server)
        - Tuples from psycopg2 (PostgreSQL)
        - Data type conversions (Decimal, date, datetime, bool)
        
        Args:
            row: Row object, tuple, or list
            
        Returns:
            Tuple of normalized values
        """
        # Convert Row object to tuple/list if needed
        # pyodbc Row objects need special handling
        try:
            # Check if it's a Row-like object (has length and can be indexed)
            if hasattr(row, '__len__') and hasattr(row, '__getitem__'):
                # Convert Row to tuple by iterating through indices
                if hasattr(row, '__iter__'):
                    try:
                        # Try direct tuple conversion first
                        row_tuple = tuple(row)
                        # Verify it worked by checking type
                        if isinstance(row_tuple, tuple):
                            row = row_tuple
                        else:
                            # Fallback: manual conversion
                            row = tuple(row[i] for i in range(len(row)))
                    except (TypeError, AttributeError):
                        # Fallback: manual conversion by index
                        row = tuple(row[i] for i in range(len(row)))
                else:
                    # Manual conversion by index
                    row = tuple(row[i] for i in range(len(row)))
            # Handle regular tuples and lists
            elif isinstance(row, (tuple, list)):
                # Already in correct format
                pass
            # Handle other iterables
            elif hasattr(row, '__iter__') and not isinstance(row, (str, bytes)):
                try:
                    row = tuple(row)
                except Exception:
                    # Last resort: try to convert to list
                    row = list(row)
            else:
                # Single value (shouldn't happen, but handle it)
                row = (row,)
        except Exception as e:
            logger.warning(f"Error converting row to tuple: {str(e)}, row type: {type(row)}")
            # Last resort: try tuple() directly
            try:
                row = tuple(row)
            except Exception:
                raise DatabaseConnectionError(f"Cannot convert row to tuple: {type(row)}")
        
        # Normalize each value in the row
        normalized = []
        for value in row:
            # Handle None
            if value is None:
                normalized.append(None)
            # Handle Decimal -> convert to float for MySQL
            elif isinstance(value, Decimal):
                normalized.append(float(value))
            # Handle date -> convert to string (YYYY-MM-DD)
            elif isinstance(value, date):
                normalized.append(value.isoformat())
            # Handle datetime -> convert to string (YYYY-MM-DD HH:MM:SS)
            elif isinstance(value, datetime):
                normalized.append(value.strftime('%Y-%m-%d %H:%M:%S'))
            # Handle bytes -> convert to string (if possible) or keep as bytes
            elif isinstance(value, bytes):
                try:
                    normalized.append(value.decode('utf-8'))
                except UnicodeDecodeError:
                    # Keep as bytes, MySQL BLOB can handle it
                    normalized.append(value)
            # Handle boolean -> convert to int (0/1) for MySQL
            elif isinstance(value, bool):
                normalized.append(1 if value else 0)
            # All other types (int, float, str, etc.) - pass through
            else:
                normalized.append(value)
        
        return tuple(normalized)
    
    def bulk_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]):
        """Bulk insert rows - optimized for MySQL"""
        if not self._connection:
            self.connect()
        
        if not rows:
            return
        
        cursor = self._connection.cursor()
        try:
            # Use connected database if schema doesn't match
            if schema != self.database_name:
                try:
                    cursor.execute(f"USE `{schema}`")
                except Exception:
                    # Use connected database instead
                    cursor.execute(f"USE `{self.database_name}`")
            else:
                cursor.execute(f"USE `{self.database_name}`")
            
            # Build column names
            col_names = ', '.join(f"`{col}`" for col in columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            insert_query = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"
            
            # Normalize all rows to tuples with compatible data types
            normalized_rows = [self._normalize_row(row) for row in rows]
            
            # Use executemany for batch insert
            cursor.executemany(insert_query, normalized_rows)
            self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to bulk insert into MySQL: {str(e)}")
        finally:
            cursor.close()

