"""
Table creation and management utilities
"""
from typing import List, Optional
from connections.connectors.base import DBConnector, ColumnInfo
from core.type_mapping import (
    map_data_type,
    map_oracle_to_target_type,
    map_source_to_oracle_type,
    normalize_data_type,
)
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
        elif 'ClickHouse' in class_name:
            return 'clickhouse'
        elif 'Oracle' in class_name:
            # Covers OracleADWConnector and similar Oracle connectors
            return 'oracle'
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
            
            # For ClickHouse targets: use database name (ClickHouse uses databases, not schemas)
            if self.target_db_type == 'clickhouse':
                # Prefer the database specified on the connection. If none is
                # specified, fall back to the source schema (e.g. 'public').
                preferred_db = getattr(self.target_connector, 'database_name', None) or schema
                target_schema = preferred_db
                logger.info(
                    f"ClickHouse uses databases - preferring connection database "
                    f"'{preferred_db}' (source schema '{schema}')"
                )
                
                # Check if the preferred database actually exists; if not, try the
                # original schema as a fallback (e.g. 'public').
                try:
                    databases = self.target_connector.list_databases()
                    if preferred_db in databases:
                        logger.info(f"ClickHouse database '{preferred_db}' already exists")
                        return  # Database already exists, no need to create
                    elif schema in databases:
                        target_schema = schema
                        logger.info(
                            f"Preferred ClickHouse database '{preferred_db}' not found; "
                            f"falling back to existing database '{schema}'"
                        )
                    # If neither exists, we'll attempt to create the preferred_db
                except Exception as e:
                    logger.warning(
                        f"Could not check database existence for ClickHouse databases "
                        f"('{preferred_db}' / '{schema}'): {e}. Will attempt to create."
                    )
            # For PostgreSQL and SQL Server: ensure the target schema exists
            # PostgreSQL: always use 'public'
            # SQL Server: always use 'dbo'
            elif self.target_db_type == 'postgres':
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
        source_schema: Optional[str] = None,
        column_type_overrides: Optional[dict] = None,
        column_name_overrides: Optional[dict] = None,
        excluded_columns: Optional[list] = None,
        protected_columns: Optional[list] = None,
        incremental_column: Optional[str] = None,
        target_table: Optional[str] = None,
    ) -> bool:
        """
        Create target table if it doesn't exist
        
        Args:
            schema: Target schema name
            table: Source table name (used for get_columns); also target name if target_table is None
            source_schema: Source schema name (if different from target)
            target_table: Optional target table name (e.g. with prefix). If None, use table.
            
        Returns:
            bool: True if table was created, False if it already existed
            
        Raises:
            TableCreationError: If table creation fails
        """
        if source_schema is None:
            source_schema = schema
        if target_table is None:
            target_table = table

        # Schema mapping for different database combinations
        # For databases WITH schemas (PostgreSQL, SQL Server): always use target's default schema
        # For databases WITHOUT schemas (MySQL, ClickHouse): use database name directly
        target_schema = schema
        if self.target_db_type == 'mysql':
            # MySQL doesn't have schemas - use database name directly
            target_schema = self.target_connector.database_name
            logger.info(f"Mapping source schema '{schema}' to MySQL database '{target_schema}' (no schema concept in MySQL)")
        elif self.target_db_type == 'clickhouse':
            # ClickHouse uses databases, not schemas.
            # Prefer the database specified in the connection; if not present,
            # fall back to the source schema (e.g. 'public').
            target_schema = getattr(self.target_connector, 'database_name', None) or schema
            logger.info(
                f"Mapping source schema '{schema}' to ClickHouse database '{target_schema}' "
                f"(connection database overrides schema when provided)"
            )
        elif self.target_db_type == 'postgres':
            # PostgreSQL: Always use 'public' schema regardless of source schema
            target_schema = 'public'
            logger.info(f"Mapping source schema '{schema}' to PostgreSQL schema 'public' (all tables in public schema)")
        elif self.target_db_type == 'sqlserver':
            # SQL Server: Always use 'dbo' schema regardless of source schema
            target_schema = 'dbo'
            logger.info(f"Mapping source schema '{schema}' to SQL Server schema 'dbo' (all tables in dbo schema)")
        elif self.target_db_type == 'oracle':
            # Oracle: schema = owner = database user. Use the connected user so tables are created in their schema.
            target_schema = (getattr(self.target_connector, 'username', None) or '').strip().upper() or schema
            logger.info(
                f"Mapping source schema '{schema}' to Oracle owner '{target_schema}' (connected user; ORA-01918 avoided)"
            )

        # Oracle-aware flows (either source or target participates as Oracle ADW).
        # We handle these separately to leverage the dedicated Oracle type-mapping
        # helpers and to enforce strict non-lossy schema rules.
        if self.source_db_type == 'oracle' or self.target_db_type == 'oracle':
            return self._create_table_oracle_aware(
                source_schema=source_schema,
                target_schema=target_schema,
                table=table,
                column_type_overrides=column_type_overrides,
                column_name_overrides=column_name_overrides,
                target_table=target_table,
            )

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
        # Apply Step 3 exclusion/protection to target DDL contract.
        excluded = {(c or "").strip().lower() for c in (excluded_columns or []) if c}
        protected = {(c or "").strip().lower() for c in (protected_columns or []) if c}
        effective_excluded = excluded - protected
        if effective_excluded:
            source_columns = [c for c in source_columns if c.name.lower() not in effective_excluded]
            if not source_columns:
                raise TableCreationError(
                    f"No migratable columns remain for source table {source_schema}.{table}"
                )
        
        # Map columns to target database types
        rename_map = { (k or "").lower(): v for k, v in (column_name_overrides or {}).items() }
        target_columns = []
        for col in source_columns:
            # Extract precision and scale for numeric types
            precision = None
            scale = None
            if col.data_type and '(' in col.data_type:
                # Try to extract precision and scale from data type
                try:
                    params = col.data_type.split('(')[1].split(')')[0]
                    if ',' in params:
                        parts = params.split(',')
                        precision = int(parts[0].strip())
                        scale = int(parts[1].strip())
                    else:
                        precision = int(params.strip())
                except (ValueError, IndexError):
                    pass
            
            mapped_type = map_data_type(
                source_type=col.data_type,
                source_db=self.source_db_type,
                target_db=self.target_db_type,
                max_length=col.max_length,
                precision=precision,
                scale=scale
            )
            
            # For AUTO_INCREMENT columns in MySQL, clear default_value
            # MySQL handles auto-increment internally, default values are not allowed
            # For IDENTITY columns in SQL Server, also clear default_value
            # For ClickHouse, no special handling needed (no auto-increment concept)
            default_value = col.default_value
            if self.target_db_type == 'mysql' and 'AUTO_INCREMENT' in mapped_type.upper():
                default_value = None
                logger.debug(f"Clearing default value for AUTO_INCREMENT column {col.name} (mapped type: {mapped_type})")
            elif self.target_db_type == 'sqlserver' and 'IDENTITY' in mapped_type.upper():
                default_value = None
                logger.debug(f"Clearing default value for IDENTITY column {col.name} (mapped type: {mapped_type})")
            
            target_col = ColumnInfo(
                # Apply Step 3 target-side rename (only when user provided an override).
                # Keys are stored as lowercased source column names.
                name=rename_map.get(col.name.lower(), col.name),
                data_type=mapped_type,
                is_nullable=col.is_nullable,
                is_primary_key=col.is_primary_key,
                max_length=col.max_length,
                default_value=default_value
            )
            target_columns.append(target_col)

        # Fail fast on rename collisions (case-insensitive).
        target_names_lower = [c.name.lower() for c in target_columns if c.name]
        if len(set(target_names_lower)) != len(target_names_lower):
            seen = set()
            dups = set()
            for nm in target_names_lower:
                if nm in seen:
                    dups.add(nm)
                seen.add(nm)
            raise TableCreationError(
                f"Target column rename collision while creating {target_schema}.{target_table}. "
                f"Conflicting target names: {', '.join(sorted(dups))}"
            )
        
        # Check if table exists and whether schema matches expected target columns.
        table_exists = False
        try:
            table_exists = self.target_connector.table_exists(target_schema, target_table)
        except Exception as e:
            logger.warning(
                f"Error checking if table exists {target_schema}.{target_table}: {str(e)}. Will attempt to create."
            )
        if table_exists:
            try:
                existing_cols = self.target_connector.get_columns(target_schema, target_table)
                existing_set = {c.name.lower() for c in existing_cols if c.name}
                expected_set = {c.name.lower() for c in target_columns if c.name}
                if existing_set == expected_set:
                    logger.info(f"Table {target_schema}.{target_table} already exists in target")
                    return False
                logger.info(
                    "Recreating table %s.%s due schema mismatch (expected=%s, existing=%s)",
                    target_schema,
                    target_table,
                    sorted(expected_set),
                    sorted(existing_set),
                )
                self._drop_target_table(target_schema, target_table)
            except Exception as e:
                raise TableCreationError(
                    f"Failed to align existing target table {target_schema}.{target_table}: {str(e)}"
                )

        # Ensure schema exists before create.
        self.ensure_schema_exists(target_schema)

        # Create table
        try:
            # Use target_schema (which is already set above for MySQL/ClickHouse targets)
            # For ClickHouse, pass the source_db_type and incremental_column so connector can handle ENGINE/ORDER BY
            if self.target_db_type == 'clickhouse':
                # Pass incremental_column as version to ReplacingMergeTree if provided
                self.target_connector.create_table(
                    target_schema,
                    target_table,
                    target_columns,
                    target_db_type=self.source_db_type,
                    incremental_column=incremental_column
                )
            else:
                self.target_connector.create_table(target_schema, target_table, target_columns)
            logger.info(f"Created table {target_schema}.{target_table} in target database")
            return True
        except Exception as e:
            raise TableCreationError(
                f"Failed to create table {target_schema}.{target_table}: {str(e)}"
            )

    def _drop_target_table(self, schema: str, table: str):
        """Drop target table using connector-specific SQL."""
        if self.target_db_type == "postgres":
            query = f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE'
        elif self.target_db_type == "mysql":
            query = f"DROP TABLE IF EXISTS `{schema}`.`{table}`"
        elif self.target_db_type == "sqlserver":
            query = f"DROP TABLE [{schema}].[{table}]"
        elif self.target_db_type == "clickhouse":
            query = f"DROP TABLE IF EXISTS `{schema}`.`{table}`"
        elif self.target_db_type == "oracle":
            query = f'DROP TABLE "{schema}"."{table}"'
        else:
            raise TableCreationError(f"Unsupported target DB type for table drop: {self.target_db_type}")
        self.target_connector.execute_query(query)
    
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

    def _create_table_oracle_aware(
        self,
        source_schema: str,
        target_schema: str,
        table: str,
        column_type_overrides: Optional[dict] = None,
        column_name_overrides: Optional[dict] = None,
        target_table: Optional[str] = None,
    ) -> bool:
        """
        Oracle-aware table creation logic.

        Handles both:
        - Oracle (source) -> Postgres/MySQL/ClickHouse (target)
        - Postgres/MySQL/ClickHouse (source) -> Oracle (target)

        The goal is to:
        - Use rich Oracle type mappings (no silent truncation/rounding).
        - Reuse existing target tables when they are compatible.
        - Fail fast with a clear message when a mismatch could cause data loss.
        """
        source_is_oracle = self.source_db_type == 'oracle'
        target_is_oracle = self.target_db_type == 'oracle'

        # Load source columns
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

        if target_table is None:
            target_table = table

        # Build target column specs using Oracle-aware type mapping helpers.
        target_columns: List[ColumnInfo] = []
        overrides = { (k or "").lower(): v for k, v in (column_type_overrides or {}).items() }
        rename_map = { (k or "").lower(): v for k, v in (column_name_overrides or {}).items() }

        if target_is_oracle and not source_is_oracle:
            # Postgres/MySQL/ClickHouse -> Oracle
            for col in source_columns:
                override_type = overrides.get(col.name.lower())
                if override_type:
                    # Use user-selected Oracle type directly
                    oracle_type = override_type
                    base_type, max_len, prec, scale = normalize_data_type(
                        oracle_type, "oracle"
                    )
                else:
                    base_type, max_len, prec, scale = normalize_data_type(
                        col.data_type, self.source_db_type
                    )
                    oracle_type = map_source_to_oracle_type(
                        source_type=col.data_type,
                        source_db=self.source_db_type,
                        max_length=col.max_length or max_len,
                        precision=prec,
                        scale=scale,
                    )
                target_columns.append(
                    ColumnInfo(
                        name=rename_map.get(col.name.lower(), col.name),
                        data_type=oracle_type,
                        is_nullable=col.is_nullable,
                        is_primary_key=col.is_primary_key,
                        max_length=col.max_length or max_len,
                        default_value=col.default_value,
                    )
                )
        elif source_is_oracle and not target_is_oracle:
            # Oracle -> Postgres/MySQL/ClickHouse
            for col in source_columns:
                base_type, max_len, prec, scale = normalize_data_type(
                    col.data_type, "oracle"
                )
                target_type = map_oracle_to_target_type(
                    oracle_type=col.data_type,
                    target_db=self.target_db_type,
                    max_length=col.max_length or max_len,
                    precision=prec,
                    scale=scale,
                )
                target_columns.append(
                    ColumnInfo(
                        name=rename_map.get(col.name.lower(), col.name),
                        data_type=target_type,
                        is_nullable=col.is_nullable,
                        is_primary_key=col.is_primary_key,
                        max_length=col.max_length or max_len,
                        default_value=col.default_value,
                    )
                )
        else:
            # Oracle -> Oracle (rare; mostly for copy-within-Oracle). In this case
            # we preserve the original column definitions, but still apply Step 3 renames.
            target_columns = [
                ColumnInfo(
                    name=rename_map.get(c.name.lower(), c.name),
                    data_type=c.data_type,
                    is_nullable=c.is_nullable,
                    is_primary_key=c.is_primary_key,
                    max_length=c.max_length,
                    default_value=c.default_value,
                )
                for c in source_columns
            ]

        # Fail fast on rename collisions (case-insensitive).
        target_names_lower = [c.name.lower() for c in target_columns if c.name]
        if len(set(target_names_lower)) != len(target_names_lower):
            seen = set()
            dups = set()
            for nm in target_names_lower:
                if nm in seen:
                    dups.add(nm)
                seen.add(nm)
            raise TableCreationError(
                f"Target column rename collision while creating {target_schema}.{target_table}. "
                f"Conflicting target names: {', '.join(sorted(dups))}"
            )

        # Check if target table already exists.
        try:
            exists = self.target_connector.table_exists(target_schema, target_table)
        except Exception as e:
            logger.warning(
                "Oracle-based sync: error checking if table %s.%s exists: %s",
                target_schema,
                target_table,
                str(e),
            )
            exists = False

        if exists:
            # Compare existing target schema to desired schema to prevent
            # destructive or lossy changes.
            try:
                existing_columns = self.target_connector.get_columns(
                    target_schema, target_table
                )
            except Exception as e:
                raise TableCreationError(
                    f"Failed to inspect existing target table {target_schema}.{target_table}: {str(e)}"
                )

            existing_by_name = {
                col.name.upper(): col for col in existing_columns
            }
            expected_by_name = {
                col.name.upper(): col for col in target_columns
            }

            schema_mismatch = False
            mismatch_col_name = None
            mismatch_exp_base = None
            mismatch_act_base = None

            for name, expected_col in expected_by_name.items():
                if name not in existing_by_name:
                    raise TableCreationError(
                        f"Existing Oracle-based target table {target_schema}.{target_table} "
                        f"is missing column {expected_col.name}. Schema must be aligned manually."
                    )

                actual_col = existing_by_name[name]

                # Normalize both type strings for comparison.
                exp_base, exp_len, exp_prec, exp_scale = normalize_data_type(
                    expected_col.data_type, self.target_db_type if not target_is_oracle else "oracle"
                )
                act_base, act_len, act_prec, act_scale = normalize_data_type(
                    actual_col.data_type, self.target_db_type if not target_is_oracle else "oracle"
                )

                # If base types differ (e.g. CLOB vs NUMBER) treat as schema mismatch.
                # We will drop and recreate instead of failing, since full sync re-inserts anyway.
                if exp_base != act_base:
                    schema_mismatch = True
                    mismatch_col_name = expected_col.name
                    mismatch_exp_base = exp_base
                    mismatch_act_base = act_base
                    break

                # For VARCHAR-like types, ensure target length is at least expected.
                if any(t in exp_base for t in ("CHAR", "VARCHAR")):
                    if exp_len is not None and act_len is not None and act_len < exp_len:
                        raise TableCreationError(
                            f"Column {expected_col.name} in target table {target_schema}.{target_table} "
                            f"has length {act_len}, which is smaller than required {exp_len}. "
                            f"Increase the column length in Oracle to avoid truncation."
                        )

                # For numeric types, ensure precision/scale are sufficient where known.
                if exp_base in ("NUMBER", "DECIMAL", "NUMERIC"):
                    if (
                        exp_prec is not None
                        and act_prec is not None
                        and act_prec < exp_prec
                    ):
                        raise TableCreationError(
                            f"Column {expected_col.name} in target table {target_schema}.{target_table} "
                            f"has precision {act_prec}, which is smaller than required {exp_prec}. "
                            f"Increase the precision to avoid overflow or rounding."
                        )
                    if (
                        exp_scale is not None
                        and act_scale is not None
                        and act_scale < exp_scale
                    ):
                        raise TableCreationError(
                            f"Column {expected_col.name} in target table {target_schema}.{target_table} "
                            f"has scale {act_scale}, which is smaller than required {exp_scale}. "
                            f"Increase the scale to avoid rounding."
                        )

            else:
                # No break - all columns compatible
                logger.info(
                    "Oracle-based sync detected (source_db_type=%s, target_db_type=%s). "
                    "Existing target table %s.%s is compatible; reusing without DDL.",
                    self.source_db_type,
                    self.target_db_type,
                    target_schema,
                    target_table,
                )
                return False

            if schema_mismatch:
                logger.warning(
                    "Type mismatch for column %s in target table %s.%s: expected %s, found %s. "
                    "Dropping table and recreating with correct schema.",
                    mismatch_col_name,
                    target_schema,
                    target_table,
                    mismatch_exp_base,
                    mismatch_act_base,
                )
                try:
                    owner = (target_schema or "").upper()
                    tbl = (target_table or "").upper()
                    self.target_connector.execute_query(
                        f'DROP TABLE "{owner}"."{tbl}"'
                    )
                except Exception as e:
                    raise TableCreationError(
                        f"Failed to drop table {target_schema}.{target_table} for schema mismatch: {str(e)}"
                    )
                # Fall through to create block below

        # Table does not exist yet – create it safely.
        try:
            # For non-Oracle targets we still ensure schema exists. For Oracle,
            # ensure_schema_exists is a no-op (schema/owner is managed by DBAs).
            self.ensure_schema_exists(target_schema)
        except Exception as e:
            raise TableCreationError(
                f"Failed to ensure target schema {target_schema}: {str(e)}"
            )

        try:
            # ClickHouse create_table expects an extra target_db_type kwarg to
            # know where the columns originated; others (including Oracle) use
            # the ColumnInfo list verbatim.
            if self.target_db_type == "clickhouse":
                self.target_connector.create_table(
                    target_schema, target_table, target_columns, target_db_type=self.source_db_type
                )
            else:
                self.target_connector.create_table(target_schema, target_table, target_columns)
            logger.info(
                "Created target table %s.%s for Oracle-based sync (source_db_type=%s, target_db_type=%s)",
                target_schema,
                target_table,
                self.source_db_type,
                self.target_db_type,
            )
            return True
        except Exception as e:
            raise TableCreationError(
                f"Failed to create target table {target_schema}.{table}: {str(e)}"
            )
    
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

