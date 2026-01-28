"""
ClickHouse database connector implementation
"""
import clickhouse_connect
from typing import List, Tuple, Optional, Dict, Any
from .base import DBConnector, ColumnInfo
from core.exceptions import DatabaseConnectionError, TableNotFoundError, DatabaseTimeoutError, DatabaseException, DatabaseQueryError
from decimal import Decimal
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)


class ClickHouseConnector(DBConnector):
    """ClickHouse database connector"""
    
    def connect(self):
        """Establish ClickHouse connection with enhanced error handling"""
        try:
            # ClickHouse can connect without database_name parameter
            connect_params = {
                'host': self.host,
                'port': self.port,
                'username': self.username,
                'password': self.password,
                'connect_timeout': 10,
            }
            if self.database_name:
                connect_params['database'] = self.database_name
            else:
                # Default to 'default' database if not specified
                connect_params['database'] = 'default'
            
            self._connection = clickhouse_connect.get_client(**connect_params)
            return self._connection
        except Exception as e:
            error_msg = str(e).lower()
            error_code = getattr(e, 'code', None)
            
            # ClickHouse-specific error detection with enhanced messages
            if 'timeout' in error_msg or 'timed out' in error_msg:
                raise DatabaseTimeoutError(
                    f"Connection timeout: Unable to reach ClickHouse server at {self.host}:{self.port}. "
                    "Please check network connectivity and server status."
                )
            elif 'authentication' in error_msg or 'password' in error_msg or 'access denied' in error_msg:
                raise DatabaseConnectionError(
                    "Connection failed: Invalid credentials. Please check your username and password."
                )
            elif 'connection refused' in error_msg or 'could not connect' in error_msg or 'network' in error_msg:
                raise DatabaseConnectionError(
                    f"Connection failed: Host unreachable. Unable to connect to {self.host}:{self.port}. "
                    "Please verify the host and port are correct."
                )
            elif 'database' in error_msg and ('does not exist' in error_msg or 'not found' in error_msg):
                raise DatabaseConnectionError(
                    f"Connection failed: Database '{self.database_name}' not found. "
                    "Please verify the database name is correct."
                )
            elif 'port' in error_msg:
                raise DatabaseConnectionError(
                    f"Connection failed: Port {self.port} is not accessible. "
                    "Please verify the port is correct (native: 9000, HTTP: 8123)."
                )
            elif 'disk' in error_msg and 'full' in error_msg:
                from core.exceptions import DatabaseException
                raise DatabaseException(
                    "ClickHouse server disk is full. Please free up disk space on the server."
                )
            elif 'memory' in error_msg and ('limit' in error_msg or 'exceeded' in error_msg):
                from core.exceptions import DatabaseException
                raise DatabaseException(
                    "ClickHouse server memory limit exceeded. Please reduce query complexity or increase server memory."
                )
            else:
                raise DatabaseConnectionError(f"Connection failed: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test ClickHouse connection with timeout handling"""
        try:
            conn = self.connect()
            # Execute simple query to test connection
            result = conn.query("SELECT 1")
            conn.close()
            return True
        except DatabaseConnectionError:
            # Re-raise connection errors
            raise
        except Exception as e:
            logger.error(f"Error testing ClickHouse connection: {str(e)}", exc_info=True)
            raise DatabaseConnectionError(f"Connection test failed: {str(e)}")
    
    def get_schemas(self) -> List[str]:
        """Get list of database names (ClickHouse uses databases like schemas)"""
        if not self._connection:
            self.connect()
        
        result = self._connection.query("SHOW DATABASES")
        databases = [row[0] for row in result.result_rows]
        
        # Filter out system databases (but keep 'default' as it's a user database)
        exclude = ['system', 'information_schema', 'INFORMATION_SCHEMA']
        return [db for db in databases if db not in exclude]
    
    def list_databases(self) -> List[str]:
        """Get list of all databases on the ClickHouse server"""
        try:
            if not self._connection:
                self.connect()
            
            result = self._connection.query("SHOW DATABASES")
            databases = [row[0] for row in result.result_rows]
            
            # Filter out system databases
            exclude = ['system', 'information_schema', 'INFORMATION_SCHEMA']
            return [db for db in databases if db not in exclude]
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to list databases: {str(e)}")
    
    def get_tables(self, schema: str) -> List[str]:
        """Get list of table names in a database"""
        if not self._connection:
            self.connect()
        
        try:
            # ClickHouse uses database.table format
            query = f"SHOW TABLES FROM `{schema}`"
            result = self._connection.query(query)
            tables = [row[0] for row in result.result_rows]
            return tables
        except Exception as e:
            error_msg = str(e).lower()
            if 'database' in error_msg and ('does not exist' in error_msg or 'not found' in error_msg):
                raise DatabaseConnectionError(f"Database '{schema}' does not exist.")
            elif 'table' in error_msg and 'not found' in error_msg:
                # Empty database, return empty list
                return []
            else:
                raise DatabaseConnectionError(f"Failed to get tables from database '{schema}': {str(e)}")
    
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Get column information for a table"""
        if not self._connection:
            self.connect()
        
        # Verify table exists
        check_query = f"""
            SELECT count() 
            FROM system.tables 
            WHERE database = '{schema}' AND name = '{table}'
        """
        result = self._connection.query(check_query)
        if result.result_rows[0][0] == 0:
            raise TableNotFoundError(f"Table {schema}.{table} does not exist")
        
        # Get column information using DESCRIBE TABLE
        describe_query = f"DESCRIBE TABLE `{schema}`.`{table}`"
        result = self._connection.query(describe_query)
        
        columns = []
        for row in result.result_rows:
            col_name = row[0]
            data_type = row[1]
            default_type = row[2] if len(row) > 2 else None
            default_expression = row[3] if len(row) > 3 else None
            comment = row[4] if len(row) > 4 else None
            codec_expression = row[5] if len(row) > 5 else None
            ttl_expression = row[6] if len(row) > 6 else None
            
            # Parse Nullable types
            is_nullable = False
            base_type = data_type
            if data_type.startswith('Nullable('):
                is_nullable = True
                # Extract inner type from Nullable(Type)
                base_type = data_type[9:-1]  # Remove 'Nullable(' and ')'
            
            # Extract max_length from String types
            max_length = None
            if 'String' in base_type or 'FixedString' in base_type:
                # FixedString(N) has length, String doesn't
                if 'FixedString' in base_type:
                    try:
                        # Extract number from FixedString(N)
                        import re
                        match = re.search(r'FixedString\((\d+)\)', base_type)
                        if match:
                            max_length = int(match.group(1))
                    except:
                        pass
            
            # ClickHouse doesn't have traditional primary keys
            # We'll check ORDER BY columns later if needed
            is_primary_key = False
            
            # Use default_expression as default_value if available
            default_value = default_expression if default_expression else None
            
            columns.append(ColumnInfo(
                name=col_name,
                data_type=base_type,  # Store base type without Nullable wrapper
                is_nullable=is_nullable,
                is_primary_key=is_primary_key,
                max_length=max_length,
                default_value=default_value
            ))
        
        return columns
    
    def get_row_count(self, schema: str, table: str) -> int:
        """Get row count for a table"""
        if not self._connection:
            self.connect()
        
        query = f"SELECT count() FROM `{schema}`.`{table}`"
        result = self._connection.query(query)
        count = result.result_rows[0][0]
        return int(count)
    
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
        
        result = self._connection.query(paginated_query)
        return result.result_rows
    
    def get_query_row_count(self, query: str) -> int:
        """Get total row count for a query (for progress tracking)"""
        if not self._connection:
            self.connect()
        
        # Wrap query in COUNT(*)
        count_query = f"SELECT count() FROM ({query}) AS subquery"
        result = self._connection.query(count_query)
        count = result.result_rows[0][0]
        return int(count)
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        """Execute a query"""
        if not self._connection:
            self.connect()
        
        try:
            # ClickHouse-connect doesn't support parameterized queries the same way
            # For now, execute query directly
            # TODO: Add parameter substitution if needed
            result = self._connection.command(query)
            return result
        except Exception as e:
            error_msg = str(e).lower()
            from core.exceptions import DatabaseQueryError
            
            # Provide specific error messages for query errors
            if 'syntax error' in error_msg or 'syntax' in error_msg:
                raise DatabaseQueryError(f"Invalid ClickHouse query syntax: {str(e)}")
            elif 'table' in error_msg and ('does not exist' in error_msg or 'not found' in error_msg):
                raise TableNotFoundError(f"Table not found: {str(e)}")
            elif 'database' in error_msg and ('does not exist' in error_msg or 'not found' in error_msg):
                raise DatabaseConnectionError(f"Database not found: {str(e)}")
            elif 'timeout' in error_msg or 'timed out' in error_msg:
                raise DatabaseTimeoutError(f"Query timeout: {str(e)}")
            else:
                raise DatabaseQueryError(f"Query execution failed: {str(e)}")
    
    def create_table(self, schema: str, table: str, columns: List[ColumnInfo], target_db_type: str = 'clickhouse'):
        """
        Create a table in ClickHouse
        
        Args:
            schema: Database name (or schema name for cross-database syncs)
            table: Table name
            columns: List of ColumnInfo objects
            target_db_type: Target database type (for type mapping) - defaults to 'clickhouse'
        """
        if not self._connection:
            self.connect()
        
        try:
            # Ensure database exists
            self.ensure_schema_exists(schema)
            
            # Build column definitions
            column_defs = []
            for col in columns:
                # Map data type if coming from another database
                if target_db_type != 'clickhouse':
                    from core.type_mapping import map_data_type
                    mapped_type = map_data_type(
                        source_type=col.data_type,
                        source_db=target_db_type,
                        target_db='clickhouse',
                        max_length=col.max_length
                    )
                else:
                    mapped_type = col.data_type
                
                # Handle ClickHouse-specific type edge cases
                # 1. Handle LowCardinality types - strip wrapper, use base type
                if mapped_type.startswith('LowCardinality('):
                    # Extract inner type from LowCardinality(Type)
                    mapped_type = mapped_type[15:-1]  # Remove 'LowCardinality(' and ')'
                    logger.debug(f"Stripped LowCardinality wrapper from {col.name}, using base type: {mapped_type}")
                
                # 2. Handle Array types - convert to String (JSON) for compatibility
                if mapped_type.startswith('Array('):
                    logger.warning(
                        f"Array type detected for column {col.name}. "
                        "Converting to String for compatibility. "
                        "Consider using JSON format for array data."
                    )
                    mapped_type = 'String'
                
                # 3. Handle Nested types - convert to String (JSON) for compatibility
                if mapped_type.startswith('Nested('):
                    logger.warning(
                        f"Nested type detected for column {col.name}. "
                        "Converting to String (JSON) for compatibility."
                    )
                    mapped_type = 'String'
                
                # Add Nullable wrapper if column is nullable
                if col.is_nullable:
                    mapped_type = f'Nullable({mapped_type})'
                
                col_def = f"`{col.name}` {mapped_type}"
                if not col.is_nullable:
                    # ClickHouse doesn't use NOT NULL, but we can document it
                    pass
                
                # Add default value if available
                if col.default_value:
                    # Format default value appropriately
                    formatted_default = self._format_default_value(col.default_value, mapped_type)
                    if formatted_default:
                        col_def += f' DEFAULT {formatted_default}'
                
                column_defs.append(col_def)
            
            # Determine ORDER BY clause
            # Use primary key columns if available, otherwise first column
            order_by_cols = []
            for col in columns:
                if col.is_primary_key:
                    order_by_cols.append(f"`{col.name}`")
            
            if not order_by_cols:
                # Use first column as fallback
                if columns:
                    order_by_cols.append(f"`{columns[0].name}`")
                else:
                    # If no columns, we can't create table, but this shouldn't happen
                    raise DatabaseConnectionError("Cannot create table without columns")
            
            order_by_clause = ', '.join(order_by_cols)
            
            # Create table with MergeTree engine
            create_query = f"""
                CREATE TABLE IF NOT EXISTS `{schema}`.`{table}` (
                    {', '.join(column_defs)}
                ) ENGINE = MergeTree()
                ORDER BY ({order_by_clause})
            """
            
            self._connection.command(create_query)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to create table {schema}.{table}: {str(e)}")
    
    def _format_default_value(self, default_value: str, data_type: str) -> str:
        """
        Format default value for ClickHouse
        
        Args:
            default_value: The default value string
            data_type: The column data type
            
        Returns:
            Formatted default value string, or empty string if should be skipped
        """
        if not default_value:
            return ''
        
        default_value = default_value.strip()
        
        # Skip PostgreSQL sequence defaults (nextval(...) syntax)
        if 'nextval' in default_value.lower():
            logger.debug(f"Skipping PostgreSQL sequence default: {default_value}")
            return ''
        
        # Check if it's already a function call or expression
        if '(' in default_value and ')' in default_value:
            # Allow ClickHouse-compatible functions
            clickhouse_functions = ['now', 'today', 'today()', 'now()', 'toString', 'toDate']
            if any(func in default_value.lower() for func in clickhouse_functions):
                return default_value
            # Skip PostgreSQL-specific functions
            pg_functions = ['nextval', 'currval', 'lastval', '::']
            if any(func in default_value.lower() for func in pg_functions):
                logger.debug(f"Skipping PostgreSQL-specific function: {default_value}")
                return ''
            # For other functions, return as-is (might be ClickHouse compatible)
            return default_value
        
        # Check if it's a ClickHouse keyword/constant
        clickhouse_constants = ['now()', 'today()', 'NULL']
        if default_value.upper() in ['NULL', 'TRUE', 'FALSE']:
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
    
    def table_exists(self, schema: str, table: str) -> bool:
        """Check if table exists"""
        if not self._connection:
            self.connect()
        
        try:
            query = f"""
                SELECT count() 
                FROM system.tables 
                WHERE database = '{schema}' AND name = '{table}'
            """
            result = self._connection.query(query)
            exists = result.result_rows[0][0] > 0
            return bool(exists)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to check if table exists: {str(e)}")
    
    def ensure_schema_exists(self, schema: str):
        """
        Ensure database exists in ClickHouse (schemas are databases)
        
        Handles edge cases:
        - Special characters in database names (uses backticks)
        - Database already exists (checks before creating)
        - Default database handling
        """
        if not self._connection:
            self.connect()
        
        # Handle default database
        if not schema or schema == 'default':
            schema = 'default'
        
        # If the schema is the same as the connected database, no need to create
        if schema == self.database_name:
            logger.info(f"Schema {schema} matches connected database, no creation needed")
            return
        
        # Check if database exists before creating (edge case: avoid errors if already exists)
        try:
            databases = self.list_databases()
            if schema in databases:
                logger.info(f"ClickHouse database '{schema}' already exists")
                return
        except Exception as e:
            logger.warning(f"Could not check database existence for '{schema}': {e}. Will attempt to create.")
        
        # Try to create the database (may fail due to permissions, but that's okay)
        # Use backticks to handle special characters in database names
        try:
            # Escape backticks in schema name if present
            escaped_schema = schema.replace('`', '``')
            create_query = f"CREATE DATABASE IF NOT EXISTS `{escaped_schema}`"
            self._connection.command(create_query)
            logger.info(f"Created or verified database {schema}")
        except Exception as e:
            error_msg = str(e).lower()
            # If database already exists, that's fine
            if 'already exists' in error_msg or 'exists' in error_msg:
                logger.info(f"Database {schema} already exists")
            else:
                logger.warning(f"Could not create database {schema}: {str(e)}. Will use connected database {self.database_name} instead.")
                # Don't raise - we'll use the connected database
    
    def get_primary_key(self, schema: str, table: str) -> List[str]:
        """
        Get primary key column names for a table
        ClickHouse doesn't have traditional primary keys, so we return ORDER BY columns
        """
        if not self._connection:
            self.connect()
        
        try:
            # Get ORDER BY columns from table definition
            query = f"SHOW CREATE TABLE `{schema}`.`{table}`"
            result = self._connection.query(query)
            create_statement = result.result_rows[0][0] if result.result_rows else ""
            
            # Parse ORDER BY clause from CREATE TABLE statement
            import re
            order_by_match = re.search(r'ORDER BY\s*\(([^)]+)\)', create_statement, re.IGNORECASE)
            if order_by_match:
                order_by_cols = order_by_match.group(1)
                # Extract column names (remove backticks and whitespace)
                cols = [col.strip().strip('`') for col in order_by_cols.split(',')]
                return cols
            
            return []
        except Exception as e:
            logger.warning(f"Failed to get primary key for {schema}.{table}: {str(e)}")
            return []
    
    def truncate_table(self, schema: str, table: str):
        """Truncate a table"""
        if not self._connection:
            self.connect()
        
        try:
            query = f"TRUNCATE TABLE IF EXISTS `{schema}`.`{table}`"
            self._connection.command(query)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to truncate table: {str(e)}")
    
    def _normalize_row(self, row: Any) -> Tuple:
        """
        Normalize a row to a tuple compatible with ClickHouse insert
        
        Handles:
        - Row objects from other connectors
        - Tuples from other databases
        - Data type conversions (Decimal, date, datetime, bool)
        
        Args:
            row: Row object, tuple, or list
            
        Returns:
            Tuple of normalized values
        """
        # Convert Row object to tuple/list if needed
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
            # Handle Decimal -> convert to float for ClickHouse
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
                    # Keep as bytes, ClickHouse String can handle it as base64
                    normalized.append(value)
            # Handle boolean -> convert to int (0/1) for ClickHouse
            elif isinstance(value, bool):
                normalized.append(1 if value else 0)
            # All other types (int, float, str, etc.) - pass through
            else:
                normalized.append(value)
        
        return tuple(normalized)
    
    def _normalize_value(self, value: Any) -> Any:
        """
        Normalize a single value for ClickHouse insert
        Used when we need to normalize individual values based on column types
        """
        # Handle None
        if value is None:
            return None
        # Handle Decimal -> convert to float for ClickHouse
        elif isinstance(value, Decimal):
            return float(value)
        # Handle date -> keep as date object (will be handled by column type check)
        elif isinstance(value, date):
            return value
        # Handle datetime -> keep as datetime object (will be handled by column type check)
        elif isinstance(value, datetime):
            return value
        # Handle bytes -> convert to string (if possible) or keep as bytes
        elif isinstance(value, bytes):
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                # Keep as bytes, ClickHouse String can handle it as base64
                return value
        # Handle boolean -> convert to int (0/1) for ClickHouse
        elif isinstance(value, bool):
            return 1 if value else 0
        # All other types (int, float, str, etc.) - pass through
        else:
            return value
    
    def bulk_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]):
        """Bulk insert rows - optimized for ClickHouse"""
        if not self._connection:
            self.connect()
        
        if not rows:
            return
        
        try:
            # Get actual column types from ClickHouse table schema
            # This ensures we coerce data to match the actual table types
            column_types = {}
            try:
                table_columns = self.get_columns(schema, table)
                for col_info in table_columns:
                    if col_info.name in columns:
                        col_idx = columns.index(col_info.name)
                        # Store normalized type (remove Nullable wrapper, lowercase)
                        col_type = col_info.data_type.lower()
                        # Remove 'nullable(' and ')' wrapper if present
                        if col_type.startswith('nullable(') and col_type.endswith(')'):
                            col_type = col_type[9:-1]  # Remove 'nullable(' and ')'
                        column_types[col_idx] = col_type
            except Exception as e:
                logger.warning(f"Could not get column types for {schema}.{table}: {e}. Using data-based inference.")
                # Fallback: detect string columns from data
                column_types = {}
                for row in rows:
                    for idx, value in enumerate(row):
                        if isinstance(value, (str, bytes)) and idx not in column_types:
                            column_types[idx] = 'string'
            
            # Coerce data to match column types BEFORE normalization
            # This ensures clickhouse-connect receives consistent types
            coerced_rows = []
            for row in rows:
                coerced_values = []
                for idx, value in enumerate(row):
                    if value is None:
                        coerced_values.append(None)
                    elif idx in column_types:
                        col_type = column_types[idx]
                        # If column is String type, ensure ALL values are strings
                        # This is critical - clickhouse-connect's String type expects len() to work on all values
                        if 'string' in col_type or 'fixedstring' in col_type:
                            if not isinstance(value, (str, bytes)):
                                coerced_values.append(str(value))
                            else:
                                coerced_values.append(value)
                        # For Date/DateTime columns, ensure values are date/datetime objects, not strings
                        elif 'date' in col_type:
                            if isinstance(value, str):
                                # Try to parse string to date
                                try:
                                    # datetime is already imported at top of file
                                    # Try different date formats
                                    parsed_dt = None
                                    for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d', '%d/%m/%Y']:
                                        try:
                                            parsed_dt = datetime.strptime(value, fmt)
                                            break
                                        except ValueError:
                                            continue
                                    
                                    if parsed_dt:
                                        if 'datetime' in col_type or 'timestamp' in col_type:
                                            coerced_values.append(parsed_dt)
                                        else:
                                            coerced_values.append(parsed_dt.date())
                                    else:
                                        # Couldn't parse, keep as string (will cause error but better than crash)
                                        coerced_values.append(value)
                                except Exception:
                                    coerced_values.append(value)
                            elif isinstance(value, (date, datetime)):
                                # Already a date/datetime object
                                coerced_values.append(value)
                            else:
                                # Other type, keep as-is (normalization will handle)
                                coerced_values.append(value)
                        # For numeric types, keep as numeric (normalization will handle Decimal, etc.)
                        else:
                            coerced_values.append(value)
                    else:
                        # No type info - check if any value in this column position is a string
                        # If so, convert all to strings to avoid type inference issues
                        has_string = any(
                            isinstance(r[idx], (str, bytes)) 
                            for r in rows 
                            if idx < len(r)
                        )
                        if has_string and not isinstance(value, (str, bytes)) and value is not None:
                            coerced_values.append(str(value))
                        else:
                            coerced_values.append(value)
                coerced_rows.append(tuple(coerced_values))
            
            # Normalize all rows to tuples with compatible data types
            # BUT: Don't convert dates to strings if they're Date/DateTime columns
            normalized_rows = []
            for row in coerced_rows:
                normalized = []
                for idx, value in enumerate(row):
                    if value is None:
                        normalized.append(None)
                    elif idx in column_types:
                        col_type = column_types[idx]
                        # For Date/DateTime columns, keep as date/datetime objects (NOT strings)
                        if 'date' in col_type and 'datetime' not in col_type and 'timestamp' not in col_type:
                            # Date column - needs date object
                            if isinstance(value, date):
                                normalized.append(value)
                            elif isinstance(value, datetime):
                                normalized.append(value.date())
                            elif isinstance(value, str):
                                # Try to parse string to date
                                try:
                                    parsed_dt = None
                                    for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S']:
                                        try:
                                            parsed_dt = datetime.strptime(value, fmt)
                                            break
                                        except ValueError:
                                            continue
                                    
                                    if parsed_dt:
                                        normalized.append(parsed_dt.date())
                                    else:
                                        # Couldn't parse, keep as string (will error but better than crash)
                                        normalized.append(value)
                                except Exception:
                                    normalized.append(value)
                            else:
                                normalized.append(value)
                        elif 'datetime' in col_type or 'timestamp' in col_type:
                            # DateTime/Timestamp column - needs datetime object
                            if isinstance(value, datetime):
                                normalized.append(value)
                            elif isinstance(value, date):
                                # Convert date to datetime (midnight)
                                normalized.append(datetime.combine(value, datetime.min.time()))
                            elif isinstance(value, str):
                                # Try to parse string to datetime
                                try:
                                    parsed_dt = None
                                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y']:
                                        try:
                                            parsed_dt = datetime.strptime(value, fmt)
                                            break
                                        except ValueError:
                                            continue
                                    
                                    if parsed_dt:
                                        normalized.append(parsed_dt)
                                    else:
                                        normalized.append(value)
                                except Exception:
                                    normalized.append(value)
                            else:
                                normalized.append(value)
                        else:
                            # Not a date column - use standard normalization
                            normalized.append(self._normalize_value(value))
                    else:
                        # No type info - use standard normalization
                        normalized.append(self._normalize_value(value))
                normalized_rows.append(tuple(normalized))
            
            # Build column names
            col_names = ', '.join(f"`{col}`" for col in columns)
            
            # Use insert method from clickhouse-connect
            # Format: INSERT INTO table (columns) VALUES (row1), (row2), ...
            data = normalized_rows
            
            # ClickHouse-connect insert method
            self._connection.insert(
                table=f"{schema}.{table}",
                data=data,
                column_names=columns
            )
        except Exception as e:
            error_msg = str(e).lower()
            
            # Provide specific error messages for insert errors
            if 'table' in error_msg and ('does not exist' in error_msg or 'not found' in error_msg):
                raise TableNotFoundError(f"Table {schema}.{table} does not exist.")
            elif 'type mismatch' in error_msg or 'cannot convert' in error_msg:
                raise DatabaseQueryError(f"Data type mismatch in bulk insert: {str(e)}")
            elif 'memory' in error_msg and ('limit' in error_msg or 'exceeded' in error_msg):
                raise DatabaseException(
                    "ClickHouse server memory limit exceeded during bulk insert. "
                    "Please reduce batch size or increase server memory."
                )
            elif 'disk' in error_msg and 'full' in error_msg:
                raise DatabaseException(
                    "ClickHouse server disk is full. Please free up disk space."
                )
            else:
                raise DatabaseQueryError(f"Failed to bulk insert into ClickHouse: {str(e)}")
    
    def close(self):
        """Close database connection"""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass  # Ignore errors during close
            finally:
                self._connection = None
