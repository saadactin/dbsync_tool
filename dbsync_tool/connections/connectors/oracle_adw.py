"""
Oracle Autonomous Data Warehouse (ADW) connector implementation.

This connector follows the same DBConnector interface used by the other
database backends (Postgres/MySQL/ClickHouse) so it can participate in:
- The shared connection pool
- Test-connection flows
- Future sync engine work (as source and destination)
"""
import logging
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import List, Tuple, Optional, Dict, Any

from .base import DBConnector, ColumnInfo
from core.exceptions import (
    DatabaseConnectionError,
    DatabaseTimeoutError,
    DatabaseQueryError,
    TableNotFoundError,
)

logger = logging.getLogger(__name__)

try:
    import oracledb  # type: ignore
except Exception as e:  # pragma: no cover - handled gracefully in connect()
    logger.warning("oracledb import failed: %s. Oracle ADW connections will be unavailable.", e)
    oracledb = None  # Fallback so tests can monkeypatch this attribute


class OracleADWConnector(DBConnector):
    """
    Oracle Autonomous Data Warehouse connector.

    Notes:
    - We treat `database_name` as the Oracle service name / TNS alias.
    - DSN format follows the Day 1 design: "<host>:<port>/<service_name>".
    - Wallet / SSL configuration is expected to be provided via environment
      variables and the Oracle client setup; we do NOT store wallet paths
      or secrets in the database.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        database_name: Optional[str] = None,
    ):
        super().__init__(host, port, username, password, database_name)
        # Precompute DSN using the agreed format
        service_name = (database_name or "").strip()
        if not service_name:
            # We still allow construction without service name so that callers
            # can surface a clear error message when trying to connect.
            self._dsn = f"{self.host}:{self.port}"
        else:
            self._dsn = f"{self.host}:{self.port}/{service_name}"

        # Conservative but reasonable defaults; can be tuned later
        self.arraysize = 1000

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_connect_kwargs(self) -> Dict[str, Any]:
        """
        Build keyword arguments for oracledb.connect().

        Uses ConnectParams with protocol tcps and ssl_server_dn_match for Oracle
        Autonomous Database (ADW), which requires TLS. When service name is
        missing, falls back to DSN. Wallet / config_dir from environment if set.
        """
        service_name = (self.database_name or "").strip() or None
        kwargs: Dict[str, Any] = {
            "user": self.username,
            "password": self.password,
            "encoding": "UTF-8",
            "nencoding": "UTF-8",
        }
        if service_name:
            params = oracledb.ConnectParams(
                host=self.host,
                port=self.port,
                service_name=service_name,
                protocol="tcps",
                ssl_server_dn_match=True,
            )
            config_dir = os.getenv("ORACLE_ADW_CONFIG_DIR") or os.getenv("TNS_ADMIN")
            if config_dir:
                params.config_dir = config_dir
            kwargs["params"] = params
        else:
            kwargs["dsn"] = self._dsn
            config_dir = os.getenv("ORACLE_ADW_CONFIG_DIR") or os.getenv("TNS_ADMIN")
            if config_dir:
                kwargs["config_dir"] = config_dir
        return kwargs

    def _interpret_oracle_error(self, error: Exception) -> DatabaseConnectionError:
        """
        Map low-level Oracle errors to user-friendly DatabaseConnectionError.
        """
        message = str(error)
        lower = message.lower()

        # Authentication failures
        if "ora-01017" in lower:
            return DatabaseConnectionError(
                "Connection failed: Invalid Oracle username or password (ORA-01017)."
            )

        # TNS / network / service name resolution errors (e.g. ORA-12514, DPY-6001)
        if (
            "ora-12154" in lower
            or "ora-12514" in lower
            or "ora-12541" in lower
            or "dpy-6001" in lower
            or "tns" in lower
            or "listener" in lower
            or "not registered with the listener" in lower
        ):
            return DatabaseConnectionError(
                "Connection failed: Service not registered with the listener. "
                "Verify host, port, and service name from your OCI Database connection string (TCPS). "
                "Ensure your client IP is in the Autonomous Database Access Control List (ACL) and the database is Running."
            )

        # Timeouts
        if "timeout" in lower or "timed out" in lower:
            return DatabaseTimeoutError(f"Connection timeout: {message}")

        # Generic fallback
        return DatabaseConnectionError(f"Connection failed: {message}")

    # ------------------------------------------------------------------
    # DBConnector interface
    # ------------------------------------------------------------------
    def connect(self):
        """Establish Oracle ADW connection with enhanced error handling."""
        if self._connection is not None:
            return self._connection

        if oracledb is None:
            raise DatabaseConnectionError(
                "Oracle driver 'oracledb' is not installed. Please install it to use Oracle ADW connections."
            )

        try:
            kwargs = self._build_connect_kwargs()
            logger.debug("Connecting to Oracle ADW with DSN %s", self._dsn)
            self._connection = oracledb.connect(**kwargs)

            # Use a reasonable arraysize for efficient fetching
            try:
                self._connection.cursor().arraysize = self.arraysize  # type: ignore[attr-defined]
            except Exception:
                # Not fatal; arraysize can also be set per-cursor
                pass

            return self._connection
        except Exception as e:
            logger.error("Error connecting to Oracle ADW: %s", e, exc_info=True)
            raise self._interpret_oracle_error(e)

    def test_connection(self) -> bool:
        """Test Oracle ADW connection using `SELECT 1 FROM DUAL`."""
        try:
            conn = self.connect()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()
            return True
        except (DatabaseConnectionError, DatabaseTimeoutError):
            # Propagate higher-level database exceptions to callers
            raise
        except Exception as e:
            logger.error("Error testing Oracle ADW connection: %s", e, exc_info=True)
            raise self._interpret_oracle_error(e)

    def get_schemas(self) -> List[str]:
        """
        Get list of schema names.

        For Oracle, we treat schema == owner; we list owners that the current
        user can see from ALL_USERS.
        """
        if not self._connection:
            self.connect()

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute("SELECT username FROM all_users ORDER BY username")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            raise DatabaseQueryError(f"Failed to get Oracle schemas: {e}")

    def list_databases(self) -> List[str]:
        """
        Oracle ADW does not expose multiple databases in the same way as
        Postgres/MySQL. For compatibility with the test-connection-and-list-
        databases flow, we simply surface the current service name (if any).
        """
        # Ensure connection works, then return the service name as a single entry
        self.test_connection()
        if self.database_name:
            return [self.database_name]
        return []

    def get_tables(self, schema: str) -> List[str]:
        """Get list of table names for a given Oracle schema/owner."""
        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute(
                    """
                    SELECT table_name
                    FROM all_tables
                    WHERE owner = :owner
                    ORDER BY table_name
                    """,
                    {"owner": owner},
                )
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            raise DatabaseQueryError(f"Failed to get tables for schema {schema}: {e}")

    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Get column metadata for a given table with rich type information.

        We deliberately embed precision/scale/length into the data_type string
        (e.g. ``NUMBER(38,10)``, ``VARCHAR2(255)``) so that downstream helpers
        like the type-mapping utilities can make non-lossy decisions using only
        ColumnInfo.
        """
        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        table_name = (table or "").upper()

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                # Verify table exists
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM all_tables
                    WHERE owner = :owner AND table_name = :table_name
                    """,
                    {"owner": owner, "table_name": table_name},
                )
                if cursor.fetchone()[0] == 0:
                    raise TableNotFoundError(f"Table {schema}.{table} does not exist")

                # Fetch column metadata, including precision/scale
                cursor.execute(
                    """
                    SELECT
                        column_name,
                        data_type,
                        data_length,
                        data_precision,
                        data_scale,
                        nullable
                    FROM all_tab_columns
                    WHERE owner = :owner AND table_name = :table_name
                    ORDER BY column_id
                    """,
                    {"owner": owner, "table_name": table_name},
                )

                columns: List[ColumnInfo] = []
                for (
                    col_name,
                    data_type,
                    data_length,
                    data_precision,
                    data_scale,
                    nullable,
                ) in cursor.fetchall():
                    # Build a richer type string when precision/scale or length are known.
                    type_upper = (data_type or "").upper()
                    type_str = data_type

                    if type_upper in ("NUMBER", "DECIMAL", "NUMERIC") and data_precision is not None:
                        if data_scale is not None:
                            type_str = f"{type_upper}({int(data_precision)},{int(data_scale)})"
                        else:
                            type_str = f"{type_upper}({int(data_precision)})"
                    elif type_upper in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR") and data_length is not None:
                        # Use length for text types so mapping can reason about truncation.
                        type_str = f"{type_upper}({int(data_length)})"

                    columns.append(
                        ColumnInfo(
                            name=col_name,
                            data_type=type_str,
                            is_nullable=(nullable == "Y"),
                            is_primary_key=False,  # PK detection can be added later
                            max_length=data_length,
                            default_value=None,
                        )
                    )
                return columns
        except TableNotFoundError:
            raise
        except Exception as e:
            raise DatabaseQueryError(
                f"Failed to get columns for table {schema}.{table}: {e}"
            )

    def get_row_count(self, schema: str, table: str) -> int:
        """Get row count for a table."""
        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        table_name = (table or "").upper()

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                query = f'SELECT COUNT(*) FROM "{owner}"."{table_name}"'
                cursor.execute(query)
                return int(cursor.fetchone()[0])
        except Exception as e:
            raise DatabaseQueryError(
                f"Failed to get row count for table {schema}.{table}: {e}"
            )

    def fetch_batch(
        self,
        query: str,
        batch_size: int,
        offset: int = 0,
        order_by: Optional[str] = None,
    ) -> List[Tuple]:
        """
        Fetch a batch of rows from a query using Oracle's OFFSET/FETCH syntax.
        """
        if not self._connection:
            self.connect()

        # Ensure deterministic ordering when possible
        query_upper = query.upper()
        if order_by and "ORDER BY" not in query_upper:
            query = f"{query} ORDER BY {order_by}"
        elif "ORDER BY" not in query_upper:
            logger.warning("OracleADWConnector.fetch_batch called without ORDER BY")

        paginated_query = (
            f"{query} OFFSET {int(offset)} ROWS FETCH NEXT {int(batch_size)} ROWS ONLY"
        )

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.arraysize = self.arraysize
                cursor.execute(paginated_query)
                return cursor.fetchall()
        except Exception as e:
            raise DatabaseQueryError(f"Failed to fetch batch from Oracle ADW: {e}")

    def get_query_row_count(self, query: str) -> int:
        """Get total row count for an arbitrary SELECT query."""
        if not self._connection:
            self.connect()

        count_query = f"SELECT COUNT(*) FROM ({query}) q"
        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute(count_query)
                return int(cursor.fetchone()[0])
        except Exception as e:
            raise DatabaseQueryError(
                f"Failed to get row count for query on Oracle ADW: {e}"
            )

    # ------------------------------------------------------------------
    # Target-side operations
    # ------------------------------------------------------------------
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        if not self._connection:
            self.connect()

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
            self._connection.commit()
        except Exception as e:
            raise DatabaseQueryError(f"Failed to execute Oracle query: {e}")

    def create_table(self, schema: str, table: str, columns: List[ColumnInfo]):
        """
        Create a table in Oracle ADW using the provided ColumnInfo list.

        The ColumnInfo.data_type values are expected to already be Oracle-aware
        type strings (e.g. ``NUMBER(38,10)``, ``VARCHAR2(255)``, ``CLOB``)
        produced by the type-mapping layer. We therefore avoid doing any
        additional cross-database mapping here and use the types verbatim.
        """
        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        table_name = (table or "").upper()

        column_defs: List[str] = []
        for col in columns:
            col_name = (col.name or "").upper()
            col_type = (col.data_type or "").upper()
            col_def = f'"{col_name}" {col_type}'
            if not col.is_nullable:
                col_def += " NOT NULL"
            # We deliberately do not attempt to translate default values here;
            # callers can encode Oracle expressions directly in ColumnInfo. For
            # now most flows do not rely on defaults for cross-db sync.
            column_defs.append(col_def)

        ddl = (
            f'CREATE TABLE "{owner}"."{table_name}" ('
            + ", ".join(column_defs)
            + ")"
        )

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute(ddl)
            self._connection.commit()
        except Exception as e:
            raise DatabaseQueryError(
                f"Failed to create Oracle table {schema}.{table}: {e}"
            )

    def table_exists(self, schema: str, table: str) -> bool:
        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        table_name = (table or "").upper()

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM all_tables
                    WHERE owner = :owner AND table_name = :table_name
                    """,
                    {"owner": owner, "table_name": table_name},
                )
                return cursor.fetchone()[0] > 0
        except Exception as e:
            raise DatabaseQueryError(
                f"Failed to check if table {schema}.{table} exists in Oracle ADW: {e}"
            )

    def truncate_table(self, schema: str, table: str):
        """Truncate a table in Oracle ADW."""
        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        table_name = (table or "").upper()

        sql = f'TRUNCATE TABLE "{owner}"."{table_name}"'
        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute(sql)
            self._connection.commit()
        except Exception as e:
            raise DatabaseQueryError(
                f"Failed to truncate Oracle table {schema}.{table}: {e}"
            )

    def _normalize_row(
        self, row: Tuple, column_types: Optional[List[str]] = None
    ) -> Tuple:
        """
        Normalize an incoming row tuple for Oracle executemany().

        Handles:
        - Row-like objects from other drivers (pyodbc, psycopg2, etc.)
        - Basic Python type coercions for maximum precision and compatibility.
        - When column_types provided: BLOB columns get int->bytes; CLOB gets Decimal->str.
        """
        # Convert Row-like objects to a plain tuple
        try:
            if not isinstance(row, (tuple, list)):
                if hasattr(row, "__len__") and hasattr(row, "__getitem__"):
                    row = tuple(row[i] for i in range(len(row)))  # type: ignore[index]
                else:
                    row = (row,)
        except Exception:
            # Best-effort fallback
            row = tuple(row)  # type: ignore[arg-type]

        normalized: List[Any] = []
        for i, value in enumerate(row):
            col_type = (column_types[i].upper() if column_types and i < len(column_types) else "") or ""

            if value is None:
                normalized.append(None)
            elif isinstance(value, bool):
                normalized.append(1 if value else 0)
            elif isinstance(value, timedelta):
                # MySQL TIME often comes as timedelta; Oracle TIMESTAMP expects datetime (ORA-00932).
                base = datetime(1970, 1, 1)
                normalized.append(base + value)
            elif isinstance(value, time):
                # Some drivers return datetime.time for TIME columns
                normalized.append(datetime.combine(date(1970, 1, 1), value))
            elif isinstance(value, bytearray):
                # BINARY/VARBINARY/BIT/BLOB: oracledb accepts bytes
                normalized.append(bytes(value))
            elif isinstance(value, (set, frozenset)):
                # MySQL SET type returns Python set; Oracle CLOB expects string (comma-separated)
                normalized.append(",".join(str(v) for v in sorted(value, key=str)))
            elif "BLOB" in col_type and isinstance(value, (int, float)):
                # MySQL BIT can return int; Oracle BLOB expects bytes (ORA-00932)
                n = int(value)
                if n < 0:
                    n = 0
                byte_len = max(1, (n.bit_length() + 7) // 8)
                normalized.append(n.to_bytes(byte_len, "big"))
            elif "CLOB" in col_type and isinstance(value, Decimal):
                # DECIMAL(65,30) mapped to CLOB; store as string (DPY-4003)
                normalized.append(str(value))
            elif "BINARY_DOUBLE" in col_type or "BINARY_FLOAT" in col_type:
                # Oracle binary float columns: bind as Python float so driver does not use NUMBER.
                # MySQL DOUBLE/FLOAT are now mapped to BINARY_* to avoid DPY-4003 for large values.
                if isinstance(value, Decimal):
                    normalized.append(float(value))
                else:
                    normalized.append(value)
            # bytes, date, datetime, Decimal (for NUMBER): pass through
            else:
                normalized.append(value)
        return tuple(normalized)

    def bulk_insert(
        self,
        schema: str,
        table: str,
        columns: List[str],
        rows: List[Tuple],
        target_column_types: Optional[List[str]] = None,
    ):
        """
        Bulk insert rows into Oracle ADW using executemany with bind variables.

        This is the main write path used by full and incremental sync when
        Oracle acts as the target. It is designed to be:
        - Type-safe: rely on Python -> Oracle type adapters without lossy casts.
        - Efficient: use arraysize/batched executemany for throughput.

        target_column_types: Optional list of Oracle column types (e.g. BLOB, CLOB)
            for type-aware normalization (int->bytes for BLOB, Decimal->str for CLOB).
        """
        if not rows:
            return

        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        table_name = (table or "").upper()

        col_list = ", ".join(f'"{(c or "").upper()}"' for c in columns)
        # Positional binds :1, :2, ...
        bind_placeholders = ", ".join(f":{i+1}" for i in range(len(columns)))
        insert_sql = (
            f'INSERT INTO "{owner}"."{table_name}" ({col_list}) '
            f"VALUES ({bind_placeholders})"
        )

        # Normalize all rows once up front (pass column types for BLOB/CLOB handling)
        normalized_rows = [
            self._normalize_row(r, target_column_types) for r in rows
        ]

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.arraysize = max(self.arraysize, len(normalized_rows))
                cursor.executemany(insert_sql, normalized_rows)
            self._connection.commit()
        except Exception as e:
            message = str(e)
            lower = message.lower()
            # Map common DML-time errors to clearer messages
            if "ora-00942" in lower:
                raise TableNotFoundError(
                    f"Target table {schema}.{table} does not exist in Oracle ADW"
                )
            if "dpy-4003" in lower or "cannot be represented as an oracle number" in lower:
                raise DatabaseQueryError(
                    f"Failed to bulk insert into Oracle ADW table {schema}.{table}: {message}. "
                    "This usually means the target table was created with NUMBER columns for "
                    "MySQL DOUBLE/FLOAT data. Drop the target table in Oracle, restart the "
                    "application server (so type mapping uses BINARY_DOUBLE/BINARY_FLOAT), "
                    "then re-run the sync so the table is recreated with the correct schema."
                )
            raise DatabaseQueryError(
                f"Failed to bulk insert into Oracle ADW table {schema}.{table}: {message}"
            )

    def ensure_schema_exists(self, schema: str):
        """
        Oracle schemas are generally created by DBAs and mapped to users.
        We do not attempt to create schemas from the application.
        """
        # No-op but present to satisfy interface
        return None

    def get_primary_key(self, schema: str, table: str) -> List[str]:
        """
        Return primary key column names for a table, if available.
        """
        if not self._connection:
            self.connect()

        owner = (schema or "").upper()
        table_name = (table or "").upper()

        try:
            with self._connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute(
                    """
                    SELECT cols.column_name
                    FROM all_constraints cons
                    JOIN all_cons_columns cols
                      ON cons.constraint_name = cols.constraint_name
                     AND cons.owner = cols.owner
                    WHERE cons.constraint_type = 'P'
                      AND cons.owner = :owner
                      AND cons.table_name = :table_name
                    ORDER BY cols.position
                    """,
                    {"owner": owner, "table_name": table_name},
                )
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(
                "Failed to get primary key for Oracle table %s.%s: %s",
                schema,
                table,
                e,
            )
            return []

    # DataFrame helpers are intentionally not implemented yet; they will be
    # provided when Oracle is supported as a full target in migration flows.
    def create_table_from_dataframe(self, schema: str, table: str, df):
        raise DatabaseConnectionError(
            "Creating Oracle ADW tables from DataFrames is not implemented yet."
        )

    def add_missing_columns(self, schema: str, table: str, df):
        raise DatabaseConnectionError(
            "Adding missing columns in Oracle ADW is not implemented yet."
        )

    def upsert_dataframe(
        self,
        schema: str,
        table: str,
        df,
        key_column: str,
    ):
        raise DatabaseConnectionError(
            "Upserting DataFrames into Oracle ADW is not implemented yet."
        )

