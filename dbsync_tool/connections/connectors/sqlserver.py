"""
SQL Server database connector implementation
"""
import pyodbc
from typing import List, Tuple, Optional, Dict, Any
from .base import DBConnector, ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError
from core.type_mapping import map_data_type
import logging

logger = logging.getLogger(__name__)


class SQLServerConnector(DBConnector):
    """SQL Server database connector"""
    
    def _get_connection_string(self, database_name: Optional[str] = None) -> str:
        """Build SQL Server connection string"""
        # If no database_name specified, connect to 'master' database (default)
        db_name = database_name if database_name else (self.database_name if self.database_name else 'master')
        
        # Try different drivers
        drivers = [
            'ODBC Driver 17 for SQL Server',
            'ODBC Driver 13 for SQL Server',
            'SQL Server Native Client 11.0',
            'SQL Server'
        ]
        
        for driver in drivers:
            try:
                # Test if driver exists
                available_drivers = pyodbc.drivers()
                if driver in available_drivers:
                    conn_str = (
                        f"DRIVER={{{driver}}};"
                        f"SERVER={self.host},{self.port};"
                        f"DATABASE={db_name};"
                        f"UID={self.username};"
                        f"PWD={self.password};"
                        f"TrustServerCertificate=yes;"
                    )
                    return conn_str
            except:
                continue
        
        # Fallback to first driver
        return (
            f"DRIVER={{{drivers[0]}}};"
            f"SERVER={self.host},{self.port};"
            f"DATABASE={db_name};"
            f"UID={self.username};"
            f"PWD={self.password};"
            f"TrustServerCertificate=yes;"
        )
    
    def connect(self):
        """Establish SQL Server connection"""
        try:
            # Use database_name if provided, otherwise connect to 'master'
            db_name = self.database_name if self.database_name else 'master'
            conn_str = self._get_connection_string(db_name)
            self._connection = pyodbc.connect(conn_str, timeout=10)
            return self._connection
        except pyodbc.Error as e:
            raise DatabaseConnectionError(f"Failed to connect to SQL Server: {str(e)}")
        except Exception as e:
            raise DatabaseConnectionError(f"Unexpected error connecting to SQL Server: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test SQL Server connection"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return True
        except Exception:
            return False
    
    def get_schemas(self) -> List[str]:
        """Get list of schema names"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute("""
            SELECT name 
            FROM sys.schemas 
            WHERE name NOT IN ('guest', 'INFORMATION_SCHEMA', 'sys', 'db_owner', 'db_accessadmin', 
                              'db_securityadmin', 'db_ddladmin', 'db_backupoperator', 
                              'db_datareader', 'db_datawriter', 'db_denydatareader', 'db_denydatawriter')
            ORDER BY name
        """)
        schemas = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return schemas
    
    def list_databases(self) -> List[str]:
        """Get list of all databases on the SQL Server"""
        try:
            if not self._connection:
                self.connect()
            
            cursor = self._connection.cursor()
            cursor.execute("""
                SELECT name 
                FROM sys.databases 
                WHERE database_id > 4 
                ORDER BY name
            """)
            databases = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return databases
        except pyodbc.Error as e:
            raise DatabaseConnectionError(f"Failed to list databases: {str(e)}")
        except Exception as e:
            raise DatabaseConnectionError(f"Unexpected error listing databases: {str(e)}")
    
    def get_tables(self, schema: str) -> List[str]:
        """Get list of table names in a schema"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """, (schema,))
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return tables
    
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Get column information for a table"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        
        # Verify table exists
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        """, (schema, table))
        if cursor.fetchone()[0] == 0:
            cursor.close()
            raise TableNotFoundError(f"Table {schema}.{table} does not exist")
        
        # Get column information
        cursor.execute("""
            SELECT 
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.CHARACTER_MAXIMUM_LENGTH,
                c.IS_NULLABLE,
                CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END as IS_PK,
                c.COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                    ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                    AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
                    AND tc.TABLE_NAME = ku.TABLE_NAME
                WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ) pk ON c.TABLE_SCHEMA = pk.TABLE_SCHEMA 
                AND c.TABLE_NAME = pk.TABLE_NAME 
                AND c.COLUMN_NAME = pk.COLUMN_NAME
            WHERE c.TABLE_SCHEMA = ? AND c.TABLE_NAME = ?
            ORDER BY c.ORDINAL_POSITION
        """, (schema, table))
        
        columns = []
        for row in cursor.fetchall():
            col_name, data_type, max_length, is_nullable, is_pk, default_value = row
            columns.append(ColumnInfo(
                name=col_name,
                data_type=data_type,
                is_nullable=is_nullable == 'YES',
                is_primary_key=bool(is_pk),
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
        cursor.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}]")
        count = cursor.fetchone()[0]
        cursor.close()
        return count
    
    def get_approximate_row_count(self, schema: str, table: str) -> Optional[int]:
        """
        Get approximate row count using sys.dm_db_partition_stats (safe, no table scan)
        
        Args:
            schema: Schema name
            table: Table name
            
        Returns:
            Optional[int]: Approximate row count or None if unavailable
        """
        if not self._connection:
            self.connect()
        
        try:
            cursor = self._connection.cursor()
            # Use sys.dm_db_partition_stats for approximate count
            cursor.execute("""
                SELECT SUM(row_count)
                FROM sys.dm_db_partition_stats
                WHERE object_id = OBJECT_ID(?)
                AND index_id IN (0, 1)
            """, (f"{schema}.{table}",))
            result = cursor.fetchone()
            cursor.close()
            if result and result[0] is not None:
                return int(result[0])
            return None
        except Exception as e:
            logger.warning(f"Failed to get approximate row count for {schema}.{table}: {str(e)}")
            return None
    
    def fetch_batch(self, query: str, batch_size: int, offset: int = 0, order_by: Optional[str] = None) -> List[Tuple]:
        """Fetch batch with proper ordering"""
        if not self._connection:
            self.connect()
        
        query_upper = query.upper()
        if order_by and 'ORDER BY' not in query_upper:
            query = f"{query} ORDER BY {order_by}"
        elif 'ORDER BY' not in query_upper:
            logger.warning(f"Query without ORDER BY: {query}")
        
        # SQL Server uses OFFSET/FETCH syntax
        paginated_query = f"{query} OFFSET {offset} ROWS FETCH NEXT {batch_size} ROWS ONLY"
        
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
        Format default value for SQL Server
        
        Args:
            default_value: The default value string
            data_type: The column data type
            
        Returns:
            Formatted default value string, or empty string if should be skipped
        """
        if not default_value:
            return ''
        
        default_value = default_value.strip()
        
        # Skip PostgreSQL sequence defaults (nextval(...) syntax) - SQL Server uses IDENTITY instead
        if 'nextval' in default_value.lower() and '::regclass' in default_value.lower():
            logger.debug(f"Skipping PostgreSQL sequence default: {default_value}")
            return ''
        
        # Skip PostgreSQL-specific syntax (:: operator)
        if '::' in default_value:
            logger.debug(f"Skipping PostgreSQL-specific syntax: {default_value}")
            return ''
        
        # Skip if column type includes IDENTITY - SQL Server handles defaults automatically
        if 'IDENTITY' in data_type.upper():
            logger.debug(f"Skipping default for IDENTITY column with type: {data_type}")
            return ''
        
        # Check if it's a PostgreSQL sequence function
        if 'nextval' in default_value.lower():
            logger.debug(f"Skipping PostgreSQL sequence default: {default_value}")
            return ''
        
        # Check if it's already a function call or expression (but not PostgreSQL-specific)
        if '(' in default_value and ')' in default_value:
            # Convert PostgreSQL now() to SQL Server GETDATE()
            if default_value.strip().lower() == 'now()':
                logger.debug(f"Converting PostgreSQL now() to SQL Server GETDATE()")
                return 'GETDATE()'
            
            # Allow SQL Server-compatible functions
            sqlserver_functions = ['CURRENT_TIMESTAMP', 'GETDATE', 'GETUTCDATE', 'SYSDATETIME', 'NEWID', 'NEWSEQUENTIALID']
            if any(func in default_value.upper() for func in sqlserver_functions):
                return default_value
            # Skip PostgreSQL-specific functions
            pg_functions = ['nextval', 'currval', 'lastval', '::']
            if any(func in default_value.lower() for func in pg_functions):
                logger.debug(f"Skipping PostgreSQL-specific function: {default_value}")
                return ''
            # For other functions, return as-is (might be SQL Server compatible)
            return default_value
        
        # Check if it's a SQL Server keyword/constant
        sqlserver_constants = ['CURRENT_TIMESTAMP', 'GETDATE()', 'GETUTCDATE()', 'SYSDATETIME()', 'TRUE', 'FALSE', 'NULL']
        if default_value.upper() in sqlserver_constants or default_value.upper() in ['GETDATE()', 'GETUTCDATE()', 'SYSDATETIME()']:
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
        escaped_value = default_value.replace("'", "''")
        return f"'{escaped_value}'"
    
    def create_table(self, schema: str, table: str, columns: List[ColumnInfo], target_db_type: str = 'sqlserver'):
        """
        Create a table in SQL Server
        
        Args:
            schema: Schema name
            table: Table name
            columns: List of ColumnInfo objects
            target_db_type: Target database type (for type mapping) - defaults to 'sqlserver'
        """
        if not self._connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self._connection.cursor()
            
            # Use ensure_schema_exists method which has better error handling
            # This handles cases where 'public' might conflict with reserved words
            # It returns the actual schema name used (might be 'dbo' instead of 'public')
            actual_schema = self.ensure_schema_exists(schema)
            
            # Build column definitions using centralized mapping
            column_defs = []
            for col in columns:
                mapped_type = map_data_type(
                    source_type=col.data_type,
                    source_db='sqlserver',  # Source is sqlserver for this connector
                    target_db=target_db_type,
                    max_length=col.max_length
                )
                col_def = f"[{col.name}] {mapped_type}"
                if not col.is_nullable:
                    col_def += ' NOT NULL'
                if col.default_value:
                    formatted_default = self._format_default_value(col.default_value, col.data_type)
                    if formatted_default:
                        col_def += f' DEFAULT {formatted_default}'
                column_defs.append(col_def)
            
            # Use the actual schema name (might be 'dbo' instead of 'public')
            create_query = f"IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[{actual_schema}].[{table}]') AND type in (N'U')) CREATE TABLE [{actual_schema}].[{table}] ({', '.join(column_defs)})"
            cursor.execute(create_query)
            self._connection.commit()
        except Exception as e:
            if self._connection:
                try:
                    self._connection.rollback()
                except Exception:
                    pass
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
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (schema, table))
            exists = cursor.fetchone()[0] > 0
            return exists
        except Exception as e:
            # If transaction is in error state, rollback and retry
            try:
                if self._connection:
                    try:
                        self._connection.rollback()
                    except Exception:
                        pass
                if cursor:
                    cursor.close()
                cursor = self._connection.cursor()
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                """, (schema, table))
                exists = cursor.fetchone()[0] > 0
                return exists
            except Exception:
                raise DatabaseConnectionError(f"Failed to check if table exists: {str(e)}")
        finally:
            if cursor:
                cursor.close()

    def ensure_schema_exists(self, schema: str):
        """Ensure schema exists in SQL Server"""
        if not self._connection:
            self.connect()
        
        # In SQL Server, 'public' is a reserved word (it's a built-in database role)
        # Map 'public' schema to 'dbo' which is the default schema in SQL Server
        if schema.lower() == 'public':
            schema = 'dbo'
            logger.debug(f"Mapped 'public' schema to 'dbo' for SQL Server compatibility")
        
        cursor = self._connection.cursor()
        try:
            # Check if schema exists first
            cursor.execute("""
                SELECT COUNT(*) 
                FROM sys.schemas 
                WHERE name = ?
            """, (schema,))
            exists = cursor.fetchone()[0] > 0
            
            # Only create if it doesn't exist
            if not exists:
                # Use dynamic SQL to create schema (avoiding parameterization issues)
                # Escape single quotes in schema name
                escaped_schema = schema.replace("'", "''")
                cursor.execute(f"""
                    IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = '{escaped_schema}')
                    BEGIN
                        EXEC('CREATE SCHEMA [{escaped_schema}]')
                    END
                """)
                self._connection.commit()
            else:
                # Schema already exists, just commit any pending transaction
                self._connection.commit()
        except Exception as e:
            # If error is about schema already existing, that's fine
            error_str = str(e).lower()
            if 'already an object named' in error_str or 'already exists' in error_str:
                logger.debug(f"Schema {schema} already exists, continuing")
                self._connection.commit()
            else:
                self._connection.rollback()
                raise DatabaseConnectionError(f"Failed to ensure schema exists: {str(e)}")
        finally:
            cursor.close()
        
        return schema  # Return the actual schema name used (might be 'dbo' instead of 'public')
    
    def get_primary_key(self, schema: str, table: str) -> List[str]:
        """Get primary key column names for a table"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute("""
            SELECT c.name
            FROM sys.key_constraints kc
            JOIN sys.index_columns ic ON kc.parent_object_id = ic.object_id
                AND kc.unique_index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id
                AND ic.column_id = c.column_id
            WHERE kc.type = 'PK'
                AND SCHEMA_NAME(kc.parent_object_id) = ?
                AND OBJECT_NAME(kc.parent_object_id) = ?
            ORDER BY ic.key_ordinal
        """, (schema, table))
        result = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return result
    
    def truncate_table(self, schema: str, table: str):
        """Truncate a table"""
        if not self._connection:
            self.connect()
        
        cursor = self._connection.cursor()
        cursor.execute(f"TRUNCATE TABLE [{schema}].[{table}]")
        self._connection.commit()
        cursor.close()

    def bulk_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]):
        """Bulk insert rows - optimized for SQL Server"""
        if not self._connection:
            self.connect()
        
        if not rows:
            return
        
        cursor = self._connection.cursor()
        try:
            # Build column names
            col_names = ', '.join(f"[{col}]" for col in columns)
            placeholders = ', '.join(['?'] * len(columns))
            
            insert_query = f"INSERT INTO [{schema}].[{table}] ({col_names}) VALUES ({placeholders})"
            
            # Use executemany for batch insert
            cursor.executemany(insert_query, rows)
            self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to bulk insert into SQL Server: {str(e)}")
        finally:
            cursor.close()

