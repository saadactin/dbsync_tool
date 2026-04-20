"""
PostgreSQL database connector implementation
"""
import re
import math
import numbers
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT, new_type, register_type
from typing import List, Tuple, Optional, Dict, Any, Union
from decimal import Decimal
import json
from .base import DBConnector, ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError
from core.type_mapping import map_data_type
from datetime import date, datetime
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def _pg_temporal_leading_iso_year(s: str) -> Optional[int]:
    """
    Leading calendar year for typical PostgreSQL text date/timestamp wire values.
    Returns None if the prefix is not YYYY- or unparseable.
    """
    s = (s or "").strip()
    if not s or len(s) < 4:
        return None
    if s[0:9].lower() in ("infinity", "-infinity"):
        return None
    neg = s[0] == "-"
    body = s[1:] if neg else s
    m = re.match(r"^(\d{4,})-", body)
    if not m:
        return None
    y = int(m.group(1))
    return -y if neg else y


def _safe_pg_date_cast(value: object, cursor) -> Union[date, str, None]:
    """Decode PostgreSQL date OID; return str if outside Python date/datetime year range."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    v = str(value).strip()
    if re.fullmatch(r"-?infinity", v, re.I):
        return v
    y = _pg_temporal_leading_iso_year(v)
    if y is not None and (y < 1 or y > 9999):
        return v
    try:
        return date.fromisoformat(v)
    except (ValueError, OverflowError):
        return v


def _safe_pg_timestamp_cast(value: object, cursor) -> Union[datetime, str, None]:
    """
    Decode PostgreSQL timestamp / timestamptz OID.
    Avoids ValueError('year ... is out of range') for edge instants near datetime.max
    when session timezone shifts representation, or for years outside 1..9999.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    v = str(value).strip()
    if re.fullmatch(r"-?infinity", v, re.I):
        return v
    y = _pg_temporal_leading_iso_year(v)
    if y is not None and (y < 1 or y > 9999):
        return v
    try:
        if len(v) > 10 and v[10] == " " and "T" not in v:
            v = v[:10] + "T" + v[11:]
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return v


def _register_safe_pg_temporal_types(conn) -> None:
    """Per-connection typecasters so fetchall() never dies on Python datetime year limits."""
    try:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT typname, oid FROM pg_type
                WHERE typname IN ('date', 'timestamp', 'timestamptz')
                  AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'pg_catalog')
                """
            )
            rows = c.fetchall()
        for typname, oid in rows:
            if typname == "date":
                t = new_type((oid,), f"pg_{typname}_py_safe", _safe_pg_date_cast)
            else:
                t = new_type((oid,), f"pg_{typname}_py_safe", _safe_pg_timestamp_cast)
            register_type(t, conn)
    except Exception as e:
        logger.warning("Could not register safe PostgreSQL temporal typecasters: %s", e, exc_info=True)


class PostgresConnector(DBConnector):
    """PostgreSQL database connector"""

    def _execute_values_resilient(
        self,
        cursor,
        query,
        rows: List[Tuple[Any, ...]],
        page_size: int = 1000,
        context: str = "",
    ) -> Tuple[int, int]:
        """
        Execute values with row-level resilience.

        Strategy:
        - Try chunk as a whole.
        - If it fails, rollback to savepoint and split the chunk.
        - Recursively isolate unrecoverable rows and skip only those rows.

        Returns:
            (applied_rows, skipped_rows)
        """
        if not rows:
            return 0, 0

        applied_rows = 0
        skipped_rows = 0
        stack: List[List[Tuple[Any, ...]]] = [rows]
        savepoint_counter = 0

        while stack:
            chunk = stack.pop()
            if not chunk:
                continue

            savepoint_counter += 1
            savepoint = f"sp_resilient_{savepoint_counter}"
            cursor.execute(f"SAVEPOINT {savepoint}")
            try:
                execute_values(cursor, query, chunk, page_size=min(page_size, len(chunk)))
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
                applied_rows += len(chunk)
            except Exception as exc:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
                if len(chunk) == 1:
                    skipped_rows += 1
                    logger.warning(
                        "Skipping one bad row during resilient write (%s): %s",
                        context or "postgres_write",
                        str(exc),
                    )
                    continue
                mid = len(chunk) // 2
                # Process smaller chunks to isolate problematic rows.
                stack.append(chunk[mid:])
                stack.append(chunk[:mid])

        return applied_rows, skipped_rows
    
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
                connect_timeout=10,  # 10 second timeout
                # Keep timestamptz decoding in UTC so instants near Python's datetime.max
                # are not shifted into year 10000+ in local/session time zones.
                options="-c timezone=UTC",
            )
            _register_safe_pg_temporal_types(self._connection)
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
    
    def get_database_size_bytes(self) -> Optional[int]:
        """Return whole-database size using pg_database_size() on the current DB."""
        try:
            if not self._connection:
                self.connect()
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT pg_database_size(current_database())")
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else None
        except Exception as e:
            logger.warning(f"Failed to get Postgres database size: {str(e)}")
            return None

    def get_table_size_bytes(self, schema: str, table: str) -> Optional[int]:
        """Return pg_total_relation_size (heap + indexes + toast) for schema.table."""
        try:
            if not self._connection:
                self.connect()
            with self._connection.cursor() as cursor:
                # Use to_regclass to avoid raising relation-does-not-exist errors.
                qualified = f'"{schema}"."{table}"'
                cursor.execute(
                    """
                    SELECT
                        CASE
                            WHEN to_regclass(%s) IS NULL THEN NULL
                            ELSE pg_total_relation_size(to_regclass(%s))
                        END
                    """,
                    (qualified, qualified),
                )
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else None
        except Exception as e:
            # Clear failed transaction state so subsequent fallback probes can run.
            try:
                if self._connection:
                    self._connection.rollback()
            except Exception:
                pass
            logger.warning(
                f"Failed to get Postgres table size for {schema}.{table}: {str(e)}"
            )
            return None

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
            def _normalize_pg_param(value: Any) -> Any:
                if value is None:
                    return None
                if isinstance(value, str):
                    return value.replace("\x00", "")
                if hasattr(value, "to_decimal") and "decimal128" in value.__class__.__name__.lower():
                    try:
                        return value.to_decimal()
                    except Exception:
                        return str(value)
                if isinstance(value, Decimal):
                    return value
                if isinstance(value, (dict, list, tuple, set)):
                    try:
                        return json.dumps(value, default=str, ensure_ascii=False).replace("\x00", "")
                    except Exception:
                        return str(value).replace("\x00", "")
                return value

            normalized_rows = [tuple(_normalize_pg_param(v) for v in row) for row in rows]
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
                
                applied, skipped = self._execute_values_resilient(
                    cursor=cursor,
                    query=insert_query,
                    rows=normalized_rows,
                    page_size=1000,
                    context=f"bulk_insert {schema}.{table}",
                )
                if skipped > 0:
                    logger.warning(
                        "Resilient bulk insert for %s.%s skipped %s row(s), applied %s row(s).",
                        schema,
                        table,
                        skipped,
                        applied,
                    )
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
    
    def _normalize_rows_for_upsert(
        self,
        schema: str,
        table: str,
        df: pd.DataFrame,
    ) -> List[Tuple[Any, ...]]:
        """
        Normalize DataFrame values for PostgreSQL upsert:
        - Convert pandas/NumPy null-like values to None.
        - Convert Timestamp to Python datetime.
        - Remove null bytes from strings.
        - Guard BIGINT overflow by coercing out-of-range values to NULL.
        """
        try:
            target_columns = self.get_columns(schema, table)
        except Exception:
            target_columns = []
        type_by_col = {
            (getattr(c, "name", "") or "").lower(): (getattr(c, "data_type", "") or "").lower()
            for c in target_columns
            if getattr(c, "name", None)
        }

        bigint_min = -9223372036854775808
        bigint_max = 9223372036854775807

        def _is_missing(value: Any) -> bool:
            if value is None:
                return True
            try:
                return bool(pd.isna(value))
            except Exception:
                return False

        def _normalize_value(col_name: str, value: Any) -> Any:
            col_type = type_by_col.get((col_name or "").lower(), "")

            if _is_missing(value):
                return None

            if isinstance(value, pd.Timestamp):
                return None if _is_missing(value) else value.to_pydatetime()

            if isinstance(value, str):
                cleaned = value.replace("\x00", "")
                lowered = cleaned.strip().lower()
                if lowered in {"nat", "nan", "none", "null"}:
                    if any(token in col_type for token in ("timestamp", "date", "time", "int", "numeric", "decimal", "double", "real")):
                        return None
                return cleaned

            if isinstance(value, Decimal):
                return value

            if isinstance(value, bool):
                return value

            if isinstance(value, numbers.Integral) and not isinstance(value, bool):
                int_val = int(value)
                if "bigint" in col_type and (int_val < bigint_min or int_val > bigint_max):
                    logger.warning(
                        "BIGINT overflow detected for %s.%s column '%s'; coercing value to NULL.",
                        schema,
                        table,
                        col_name,
                    )
                    return None
                return int_val

            if isinstance(value, str) and "bigint" in col_type:
                s = value.strip()
                if re.fullmatch(r"[+-]?\d+", s or ""):
                    try:
                        int_val = int(s)
                        if int_val < bigint_min or int_val > bigint_max:
                            logger.warning(
                                "BIGINT overflow detected for %s.%s column '%s'; coercing value to NULL.",
                                schema,
                                table,
                                col_name,
                            )
                            return None
                    except Exception:
                        return None

            if isinstance(value, int):
                if "bigint" in col_type and (value < bigint_min or value > bigint_max):
                    logger.warning(
                        "BIGINT overflow detected for %s.%s column '%s'; coercing value to NULL.",
                        schema,
                        table,
                        col_name,
                    )
                    return None
                return value

            if isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    return None
                return value

            if hasattr(value, "to_decimal") and "decimal128" in value.__class__.__name__.lower():
                try:
                    return value.to_decimal()
                except Exception:
                    return str(value)

            if isinstance(value, (dict, list, tuple, set)):
                try:
                    return json.dumps(value, default=str, ensure_ascii=False).replace("\x00", "")
                except Exception:
                    return str(value).replace("\x00", "")

            return value

        normalized_rows: List[Tuple[Any, ...]] = []
        for row in df.itertuples(index=False, name=None):
            normalized_rows.append(
                tuple(_normalize_value(col_name, cell) for col_name, cell in zip(df.columns, row))
            )
        return normalized_rows

    def _has_matching_conflict_constraint(
        self,
        schema: str,
        table: str,
        key_columns: List[str],
    ) -> bool:
        if not key_columns:
            return False
        normalized_keys = [k.lower() for k in key_columns]
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.indkey::text, i.indnkeyatts
                FROM pg_index i
                JOIN pg_class t ON t.oid = i.indrelid
                JOIN pg_namespace ns ON ns.oid = t.relnamespace
                WHERE ns.nspname = %s
                  AND t.relname = %s
                  AND (i.indisunique OR i.indisexclusion)
                """,
                (schema, table),
            )
            index_rows = cursor.fetchall()
            if not index_rows:
                return False
            # Resolve attnums -> ordered column names per index.
            cursor.execute(
                """
                SELECT a.attnum, a.attname
                FROM pg_attribute a
                JOIN pg_class t ON t.oid = a.attrelid
                JOIN pg_namespace ns ON ns.oid = t.relnamespace
                WHERE ns.nspname = %s
                  AND t.relname = %s
                  AND a.attnum > 0
                """,
                (schema, table),
            )
            attname_by_num = {int(num): str(name).lower() for num, name in cursor.fetchall()}

        for indkey_text, indnkeyatts in index_rows:
            try:
                key_nums = [int(x) for x in str(indkey_text).split()[: int(indnkeyatts or 0)]]
            except Exception:
                continue
            idx_cols = [attname_by_num.get(n) for n in key_nums if attname_by_num.get(n)]
            if idx_cols == normalized_keys:
                return True
        return False

    def upsert_dataframe(
        self,
        schema: str,
        table: str,
        df: pd.DataFrame,
        key_column: str,
        key_columns: Optional[List[str]] = None,
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
            effective_keys = key_columns or [key_column]
            effective_keys = [k for k in effective_keys if k]
            missing_keys = [k for k in effective_keys if k not in df.columns]
            if missing_keys:
                raise DatabaseConnectionError(f"Key column {key_column} not found in DataFrame")
            if not effective_keys:
                raise DatabaseConnectionError("At least one upsert key column is required")

            normalized_rows = self._normalize_rows_for_upsert(schema, table, df)
            if not normalized_rows:
                return

            columns = list(df.columns)
            # Keep latest row for duplicate key combinations in the same batch
            # using normalized python tuples (prevents pandas coercing None back to NaT/NaN).
            key_idx = [columns.index(k) for k in effective_keys]
            dedup_map: Dict[Tuple[Any, ...], Tuple[Any, ...]] = {}
            dedup_order: List[Tuple[Any, ...]] = []
            for row in normalized_rows:
                key = tuple(row[i] for i in key_idx)
                if key not in dedup_map:
                    dedup_order.append(key)
                dedup_map[key] = row
            rows = [dedup_map[k] for k in dedup_order]

            with self._connection.cursor() as cursor:
                # Build column identifiers
                col_identifiers = sql.SQL(', ').join(
                    sql.Identifier(col) for col in columns
                )

                # Use ON CONFLICT only when matching unique/exclusion index exists.
                if self._has_matching_conflict_constraint(schema, table, effective_keys):
                    update_cols = [col for col in columns if col not in effective_keys]
                    if update_cols:
                        update_clause = sql.SQL(', ').join(
                            sql.SQL("{} = EXCLUDED.{}").format(
                                sql.Identifier(col),
                                sql.Identifier(col)
                            )
                            for col in update_cols
                        )
                        insert_query = sql.SQL("""
                            INSERT INTO {}.{} ({})
                            VALUES %s
                            ON CONFLICT ({}) DO UPDATE SET {}
                        """).format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                            col_identifiers,
                            sql.SQL(', ').join(sql.Identifier(k) for k in effective_keys),
                            update_clause
                        )
                    else:
                        # Key-only table: on conflict do nothing.
                        insert_query = sql.SQL("""
                            INSERT INTO {}.{} ({})
                            VALUES %s
                            ON CONFLICT ({}) DO NOTHING
                        """).format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                            col_identifiers,
                            sql.SQL(', ').join(sql.Identifier(k) for k in effective_keys),
                        )
                    applied, skipped = self._execute_values_resilient(
                        cursor=cursor,
                        query=insert_query,
                        rows=rows,
                        page_size=1000,
                        context=f"upsert_on_conflict {schema}.{table}",
                    )
                else:
                    # Fallback strategy (industry-safe degradation):
                    # emulate upsert by deleting matching keys then inserting batch.
                    # This keeps incremental flow alive for tables without unique constraints.
                    if len(effective_keys) == 1:
                        key = effective_keys[0]
                        key_idx = columns.index(key)
                        key_values = [r[key_idx] for r in rows if r[key_idx] is not None]
                        if key_values:
                            delete_query = sql.SQL("DELETE FROM {}.{} WHERE {} = ANY(%s)").format(
                                sql.Identifier(schema),
                                sql.Identifier(table),
                                sql.Identifier(key),
                            )
                            cursor.execute(delete_query, (key_values,))
                    else:
                        tuple_parts = []
                        params: List[Any] = []
                        for row in rows:
                            key_vals = [row[columns.index(k)] for k in effective_keys]
                            if any(v is None for v in key_vals):
                                continue
                            tuple_parts.append(
                                "(" + ", ".join(["%s"] * len(effective_keys)) + ")"
                            )
                            params.extend(key_vals)
                        if tuple_parts:
                            key_expr = ", ".join([f'"{k}"' for k in effective_keys])
                            delete_sql = (
                                f'DELETE FROM "{schema}"."{table}" '
                                f'WHERE ({key_expr}) IN ({", ".join(tuple_parts)})'
                            )
                            cursor.execute(delete_sql, params)

                    insert_query = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        col_identifiers,
                    )
                    applied, skipped = self._execute_values_resilient(
                        cursor=cursor,
                        query=insert_query,
                        rows=rows,
                        page_size=1000,
                        context=f"upsert_delete_insert {schema}.{table}",
                    )
                if skipped > 0:
                    logger.warning(
                        "Resilient upsert for %s.%s skipped %s row(s), applied %s row(s).",
                        schema,
                        table,
                        skipped,
                        applied,
                    )
                if applied == 0 and skipped > 0:
                    logger.warning(
                        "All rows in current batch were invalid for %s.%s (skipped=%s). Continuing without failing table.",
                        schema,
                        table,
                        skipped,
                    )
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise DatabaseConnectionError(f"Failed to upsert DataFrame: {str(e)}")

