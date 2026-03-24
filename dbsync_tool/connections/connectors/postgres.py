"""
PostgreSQL database connector implementation
"""
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from typing import List, Tuple, Optional, Dict, Any
from .base import DBConnector, ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError
from core.type_mapping import map_data_type
from datetime import date, datetime
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class PostgresConnector(DBConnector):
    """PostgreSQL database connector"""
    
    def connect(self):
        """Establish PostgreSQL connection with enhanced error handling"""
        try:
            # If no database_name specified, connect to 'postgres' database (default)
            db_name = self.database_name if self.database_name else 'postgres'
            self._connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                user=self.username,
                password=self.password,
                database=db_name,
                connect_timeout=10  # 10 second timeout
            )
            return self._connection
        except psycopg2.OperationalError as e:
            error_msg = str(e).lower()
            # Provide specific error messages
            if 'timeout' in error_msg or 'timed out' in error_msg:
                from core.exceptions import DatabaseTimeoutError
                raise DatabaseTimeoutError(f"Connection timeout: Unable to reach PostgreSQL server at {self.host}:{self.port}")
            elif 'authentication failed' in error_msg or 'password' in error_msg:
                raise DatabaseConnectionError("Connection failed: Invalid credentials. Please check your username and password.")
            elif 'could not connect' in error_msg or 'connection refused' in error_msg:
                raise DatabaseConnectionError(f"Connection failed: Host unreachable. Unable to connect to {self.host}:{self.port}")
            elif 'database' in error_msg and 'does not exist' in error_msg:
                raise DatabaseConnectionError(f"Connection failed: Database '{db_name}' not found.")
            elif 'port' in error_msg:
                raise DatabaseConnectionError(f"Connection failed: Port {self.port} is not accessible.")
            else:
                raise DatabaseConnectionError(f"Connection failed: {str(e)}")
        except psycopg2.InterfaceError as e:
            raise DatabaseConnectionError(f"Connection interface error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to PostgreSQL: {str(e)}", exc_info=True)
            raise DatabaseConnectionError(f"Unexpected error connecting to PostgreSQL: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test PostgreSQL connection with timeout handling"""
        try:
            conn = self.connect()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            conn.close()
            return True
        except DatabaseConnectionError:
            # Re-raise connection errors
            raise
        except Exception as e:
            logger.error(f"Error testing PostgreSQL connection: {str(e)}", exc_info=True)
            raise DatabaseConnectionError(f"Connection test failed: {str(e)}")
    
    def get_schemas(self) -> List[str]:
        """Get list of schema names"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                ORDER BY schema_name
            """)
            return [row[0] for row in cursor.fetchall()]
    
    def list_databases(self) -> List[str]:
        """Get list of all databases on the PostgreSQL server"""
        try:
            if not self._connection:
                self.connect()
            
            with self._connection.cursor() as cursor:
                cursor.execute("""
                    SELECT datname 
                    FROM pg_database 
                    WHERE datistemplate = false 
                    AND datname NOT IN ('postgres')
                    ORDER BY datname
                """)
                databases = [row[0] for row in cursor.fetchall()]
                return databases
        except psycopg2.OperationalError as e:
            raise DatabaseConnectionError(f"Failed to list databases: {str(e)}")
        except Exception as e:
            raise DatabaseConnectionError(f"Unexpected error listing databases: {str(e)}")
    
    def get_tables(self, schema: str) -> List[str]:
        """Get list of table names in a schema"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """, (schema,))
            return [row[0] for row in cursor.fetchall()]
    
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Get column information for a table"""
        if not self._connection:
            self.connect()
        
        try:
            with self._connection.cursor() as cursor:
                # Verify table exists
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = %s
                    )
                """, (schema, table))
                if not cursor.fetchone()[0]:
                    raise TableNotFoundError(f"Table {schema}.{table} does not exist")
                
                # Get columns with primary key information
                cursor.execute("""
                    SELECT 
                        c.column_name,
                        c.data_type,
                        c.character_maximum_length,
                        c.is_nullable,
                        CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END as is_pk,
                        c.column_default
                    FROM information_schema.columns c
                    LEFT JOIN (
                        SELECT ku.table_schema, ku.table_name, ku.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage ku
                            ON tc.constraint_name = ku.constraint_name
                            AND tc.table_schema = ku.table_schema
                            AND tc.table_name = ku.table_name
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                    ) pk ON c.table_schema = pk.table_schema 
                        AND c.table_name = pk.table_name 
                        AND c.column_name = pk.column_name
                    WHERE c.table_schema = %s AND c.table_name = %s
                    ORDER BY c.ordinal_position
                """, (schema, table))
                
                columns = []
                for row in cursor.fetchall():
                    col_name, data_type, max_length, is_nullable, is_pk, default_value = row
                    columns.append(ColumnInfo(
                        name=col_name,
                        data_type=data_type,
                        is_nullable=is_nullable == 'YES',
                        is_primary_key=is_pk,
                        max_length=max_length,
                        default_value=default_value
                    ))
                return columns
        except Exception as e:
            # If transaction is in error state, rollback and retry
            if 'InFailedSqlTransaction' in str(type(e).__name__) or 'transaction is aborted' in str(e).lower():
                try:
                    self._connection.rollback()
                    with self._connection.cursor() as cursor:
                        # Verify table exists
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = %s AND table_name = %s
                            )
                        """, (schema, table))
                        if not cursor.fetchone()[0]:
                            raise TableNotFoundError(f"Table {schema}.{table} does not exist")
                        
                        # Get columns with primary key information
                        cursor.execute("""
                            SELECT 
                                c.column_name,
                                c.data_type,
                                c.character_maximum_length,
                                c.is_nullable,
                                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END as is_pk,
                                c.column_default
                            FROM information_schema.columns c
                            LEFT JOIN (
                                SELECT ku.table_schema, ku.table_name, ku.column_name
                                FROM information_schema.table_constraints tc
                                JOIN information_schema.key_column_usage ku
                                    ON tc.constraint_name = ku.constraint_name
                                    AND tc.table_schema = ku.table_schema
                                    AND tc.table_name = ku.table_name
                                WHERE tc.constraint_type = 'PRIMARY KEY'
                            ) pk ON c.table_schema = pk.table_schema 
                                AND c.table_name = pk.table_name 
                                AND c.column_name = pk.column_name
                            WHERE c.table_schema = %s AND c.table_name = %s
                            ORDER BY c.ordinal_position
                        """, (schema, table))
                        
                        columns = []
                        for row in cursor.fetchall():
                            col_name, data_type, max_length, is_nullable, is_pk, default_value = row
                            columns.append(ColumnInfo(
                                name=col_name,
                                data_type=data_type,
                                is_nullable=is_nullable == 'YES',
                                is_primary_key=is_pk,
                                max_length=max_length,
                                default_value=default_value
                            ))
                        return columns
                except Exception as retry_error:
                    raise DatabaseConnectionError(f"Failed to get columns after rollback: {str(retry_error)}")
            else:
                raise
    
    def get_row_count(self, schema: str, table: str) -> int:
        """Get row count for a table"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            query = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table)
            )
            cursor.execute(query)
            return cursor.fetchone()[0]
    
    def get_approximate_row_count(self, schema: str, table: str) -> Optional[int]:
        """
        Get approximate row count using pg_class statistics (safe, no table scan)
        
        Args:
            schema: Schema name
            table: Table name
            
        Returns:
            Optional[int]: Approximate row count or None if unavailable
        """
        if not self._connection:
            self.connect()
        
        try:
            with self._connection.cursor() as cursor:
                # Use pg_class.reltuples for approximate count (much faster than COUNT(*))
                cursor.execute("""
                    SELECT reltuples::bigint AS approx_rows
                    FROM pg_class
                    WHERE relname = %s
                    AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = %s)
                """, (table, schema))
                result = cursor.fetchone()
                if result and result[0] is not None:
                    return int(result[0])
                return None
        except Exception as e:
            logger.warning(f"Failed to get approximate row count for {schema}.{table}: {str(e)}")
            return None
    
    def fetch_batch(self, query: str, batch_size: int, offset: int = 0, order_by: Optional[str] = None) -> List[Tuple]:
        """
        Fetch batch with proper ordering
        
        Args:
            query: SQL query (should not include ORDER BY if order_by is provided)
            batch_size: Number of rows to fetch
            offset: Number of rows to skip
            order_by: Optional ORDER BY clause (if not in query)
        """
        if not self._connection:
            self.connect()
        
        # Ensure query has ORDER BY for deterministic results
        query_upper = query.upper()
        if order_by and 'ORDER BY' not in query_upper:
            query = f"{query} ORDER BY {order_by}"
        elif 'ORDER BY' not in query_upper:
            # No ordering specified - this should be handled by caller
            # but we'll add a warning
            logger.warning(f"Query without ORDER BY: {query}")
        
        paginated_query = f"{query} LIMIT {batch_size} OFFSET {offset}"
        
        with self._connection.cursor() as cursor:
            cursor.execute(paginated_query)
            return cursor.fetchall()
    
    def get_query_row_count(self, query: str) -> int:
        """Get total row count for a query (for progress tracking)"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            # Wrap query in COUNT(*)
            count_query = f"SELECT COUNT(*) FROM ({query}) AS subquery"
            cursor.execute(count_query)
            return cursor.fetchone()[0]
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        """Execute a query"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            self._connection.commit()
            return cursor

    def execute_query_fetchall(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple]:
        """
        Execute a SELECT query and return all rows.

        Important: we fetch inside the cursor context so the caller doesn't
        attempt to `fetchall()` from an already-closed cursor.
        """
        if not self._connection:
            self.connect()

        with self._connection.cursor() as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()
    
    def _format_default_value(self, default_value: str, data_type: str) -> str:
        """
        Format default value for PostgreSQL
        
        Args:
            default_value: The default value string
            data_type: The column data type
            
        Returns:
            Formatted default value string
        """
        if not default_value:
            return ''
        
        # Remove any existing quotes
        default_value = default_value.strip()
        
        # Check if it's already a function call or expression (contains parentheses)
        if '(' in default_value and ')' in default_value:
            # Likely a function like CURRENT_TIMESTAMP(), NOW(), etc.
            return default_value
        
        # Check if it's a PostgreSQL keyword/constant
        pg_constants = ['CURRENT_TIMESTAMP', 'CURRENT_DATE', 'CURRENT_TIME', 'TRUE', 'FALSE', 'NULL']
        if default_value.upper() in pg_constants:
            return default_value.upper()
        
        # Check if it's a number (integer or decimal)
        try:
            float(default_value)
            return default_value
        except ValueError:
            pass
        
        # Check if it's a boolean
        if default_value.upper() in ('TRUE', 'FALSE', '1', '0'):
            if default_value.upper() in ('TRUE', '1'):
                return 'TRUE'
            else:
                return 'FALSE'
        
        # For text types, quote the value and escape single quotes
        # Escape single quotes by doubling them
        escaped_value = default_value.replace("'", "''")
        return f"'{escaped_value}'"
    
    def create_table(self, schema: str, table: str, columns: List[ColumnInfo], target_db_type: str = 'postgres'):
        """
        Create a table in PostgreSQL
        
        Args:
            schema: Schema name
            table: Table name
            columns: List of ColumnInfo objects
            target_db_type: Target database type (for type mapping) - defaults to 'postgres'
        """
        if not self._connection:
            self.connect()
        
        # Create schema if not exists (in separate transaction)
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(schema)
                ))
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to create schema {schema}: {str(e)}")
        
        # Build column definitions using centralized mapping
        column_defs = []
        for col in columns:
            mapped_type = map_data_type(
                source_type=col.data_type,
                source_db='postgres',  # Source is postgres for this connector
                target_db=target_db_type,
                max_length=col.max_length
            )
            col_def = f'"{col.name}" {mapped_type}'
            if not col.is_nullable:
                col_def += ' NOT NULL'
            if col.default_value:
                formatted_default = self._format_default_value(col.default_value, col.data_type)
                if formatted_default:
                    col_def += f' DEFAULT {formatted_default}'
            column_defs.append(col_def)
        
        # Create table with proper error handling and transaction management
        try:
            with self._connection.cursor() as cursor:
                create_query = sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {}.{} ({})
                """).format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    sql.SQL(', '.join(column_defs))
                )
                cursor.execute(create_query)
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to create table {schema}.{table}: {str(e)}")
    
    def table_exists(self, schema: str, table: str) -> bool:
        """Check if table exists"""
        if not self._connection:
            self.connect()
        
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = %s
                    )
                """, (schema, table))
                return cursor.fetchone()[0]
        except Exception as e:
            # If transaction is in error state, rollback and retry
            try:
                self._connection.rollback()
                with self._connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = %s AND table_name = %s
                        )
                    """, (schema, table))
                    return cursor.fetchone()[0]
            except Exception:
                # If retry fails, re-raise original error
                raise DatabaseConnectionError(f"Failed to check if table exists: {str(e)}")
    
    def ensure_schema_exists(self, schema: str):
        """Ensure schema exists in PostgreSQL"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(schema)
            ))
            self._connection.commit()
    
    def get_primary_key(self, schema: str, table: str) -> List[str]:
        """Get primary key column names for a table"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            cursor.execute("""
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                    ON tc.constraint_name = ku.constraint_name
                    AND tc.table_schema = ku.table_schema
                    AND tc.table_name = ku.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = %s
                    AND tc.table_name = %s
                ORDER BY ku.ordinal_position
            """, (schema, table))
            return [row[0] for row in cursor.fetchall()]
    
    def truncate_table(self, schema: str, table: str):
        """Truncate a table"""
        if not self._connection:
            self.connect()
        
        with self._connection.cursor() as cursor:
            query = sql.SQL("TRUNCATE TABLE {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table)
            )
            cursor.execute(query)
            self._connection.commit()
    
    def bulk_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]):
        """Bulk insert rows using execute_values for efficiency"""
        if not self._connection:
            self.connect()
        
        if not rows:
            return
        
        try:
            with self._connection.cursor() as cursor:
                # Build column identifiers
                col_identifiers = sql.SQL(', ').join(
                    sql.Identifier(col) for col in columns
                )
                
                # Build INSERT query
                insert_query = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    col_identifiers
                )
                
                # Use execute_values for efficient bulk insert
                execute_values(cursor, insert_query, rows, page_size=1000)
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to bulk insert into PostgreSQL: {str(e)}")
    
    def create_table_from_dataframe(self, schema: str, table: str, df: pd.DataFrame):
        """
        Create a table from a pandas DataFrame
        
        Args:
            schema: Schema name
            table: Table name
            df: DataFrame with data structure
        """
        if not self._connection:
            self.connect()
        
        if df.empty:
            raise DatabaseConnectionError(f"Cannot create table from empty DataFrame")
        
        try:
            # Ensure schema exists
            self.ensure_schema_exists(schema)
            
            # Infer column types from DataFrame
            columns = []
            for col_name in df.columns:
                dtype = df[col_name].dtype
                
                # Map pandas dtype to PostgreSQL type
                if pd.api.types.is_integer_dtype(dtype):
                    if dtype == 'int64':
                        pg_type = 'BIGINT'
                    elif dtype == 'int32':
                        pg_type = 'INTEGER'
                    elif dtype == 'int16':
                        pg_type = 'SMALLINT'
                    else:
                        pg_type = 'INTEGER'
                elif pd.api.types.is_float_dtype(dtype):
                    pg_type = 'DOUBLE PRECISION'
                elif pd.api.types.is_bool_dtype(dtype):
                    pg_type = 'BOOLEAN'
                elif pd.api.types.is_datetime64_any_dtype(dtype):
                    pg_type = 'TIMESTAMP'
                elif pd.api.types.is_object_dtype(dtype):
                    # Check sample values
                    sample = df[col_name].dropna().head(1)
                    if len(sample) > 0:
                        val = sample.iloc[0]
                        if isinstance(val, (date, datetime)):
                            pg_type = 'TIMESTAMP'
                        else:
                            pg_type = 'TEXT'
                    else:
                        pg_type = 'TEXT'
                else:
                    pg_type = 'TEXT'
                
                # Check if column has nulls
                has_nulls = df[col_name].isna().any()
                
                columns.append(ColumnInfo(
                    name=col_name,
                    data_type=pg_type,
                    is_nullable=has_nulls,
                    is_primary_key=False,
                    max_length=None
                ))
            
            # Create table using existing create_table method
            self.create_table(schema, table, columns, target_db_type='postgres')
            
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to create table from DataFrame: {str(e)}")
    
    def add_missing_columns(self, schema: str, table: str, df: pd.DataFrame):
        """
        Add missing columns to an existing table based on DataFrame
        
        Args:
            schema: Schema name
            table: Table name
            df: DataFrame with new columns
        """
        if not self._connection:
            self.connect()
        
        if df.empty:
            return
        
        try:
            # Get existing columns
            existing_columns = self.get_columns(schema, table)
            existing_col_names = {col.name for col in existing_columns}
            
            # Find new columns
            new_columns = []
            for col_name in df.columns:
                if col_name not in existing_col_names:
                    dtype = df[col_name].dtype
                    
                    # Map pandas dtype to PostgreSQL type (same logic as create_table_from_dataframe)
                    if pd.api.types.is_integer_dtype(dtype):
                        pg_type = 'BIGINT' if dtype == 'int64' else 'INTEGER'
                    elif pd.api.types.is_float_dtype(dtype):
                        pg_type = 'DOUBLE PRECISION'
                    elif pd.api.types.is_bool_dtype(dtype):
                        pg_type = 'BOOLEAN'
                    elif pd.api.types.is_datetime64_any_dtype(dtype):
                        pg_type = 'TIMESTAMP'
                    else:
                        pg_type = 'TEXT'
                    
                    new_columns.append((col_name, pg_type))
            
            # Add new columns
            with self._connection.cursor() as cursor:
                for col_name, pg_type in new_columns:
                    alter_query = sql.SQL("ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(col_name),
                        sql.SQL(pg_type)
                    )
                    cursor.execute(alter_query)
                    logger.info(f"Added column {col_name} ({pg_type}) to table {schema}.{table}")
                self._connection.commit()
            
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to add missing columns: {str(e)}")
    
    def upsert_dataframe(
        self, 
        schema: str, 
        table: str, 
        df: pd.DataFrame, 
        key_column: str
    ):
        """
        Upsert (insert or update) DataFrame rows into table using INSERT ... ON CONFLICT
        
        Args:
            schema: Schema name
            table: Table name
            df: DataFrame with data
            key_column: Primary key or unique identifier column name
        """
        if not self._connection:
            self.connect()
        
        if df.empty:
            return
        
        try:
            if key_column not in df.columns:
                raise DatabaseConnectionError(f"Key column {key_column} not found in DataFrame")
            
            columns = list(df.columns)
            rows = [tuple(row) for row in df.values]
            
            with self._connection.cursor() as cursor:
                # Build column identifiers
                col_identifiers = sql.SQL(', ').join(
                    sql.Identifier(col) for col in columns
                )
                
                # Build placeholders
                placeholders = sql.SQL(', ').join([sql.Placeholder()] * len(columns))
                
                # Build UPDATE clause (update all columns except key)
                update_cols = [col for col in columns if col != key_column]
                update_clause = sql.SQL(', ').join(
                    sql.SQL("{} = EXCLUDED.{}").format(
                        sql.Identifier(col),
                        sql.Identifier(col)
                    )
                    for col in update_cols
                )
                
                # Build INSERT ... ON CONFLICT query
                insert_query = sql.SQL("""
                    INSERT INTO {}.{} ({}) 
                    VALUES ({})
                    ON CONFLICT ({}) DO UPDATE SET {}
                """).format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    col_identifiers,
                    placeholders,
                    sql.Identifier(key_column),
                    update_clause
                )
                
                # Execute for each row
                for row in rows:
                    cursor.execute(insert_query, row)
                
                self._connection.commit()
            
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to upsert DataFrame: {str(e)}")

