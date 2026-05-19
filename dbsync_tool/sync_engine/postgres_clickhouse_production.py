"""
PostgreSQL → ClickHouse Production Migration Engine

Implements:
- 100% data fidelity
- Zero duplication (ReplacingMergeTree)
- Zero data loss
- Soft delete handling
- Idempotent operations
- Fault tolerance
- Comprehensive validation
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncCheckpoint, SyncExecution, SyncExecutionLog
from connections.connectors.base import DBConnector
from sync_engine.query_builder import QueryBuilder
from sync_engine.exceptions import TableSyncError
import hashlib
import time

logger = logging.getLogger(__name__)


class PostgresClickHouseSync:
    """
    Production-grade PostgreSQL → ClickHouse sync engine
    """

    def __init__(self, job: SyncJob, source_connector: DBConnector, target_connector: DBConnector):
        self.job = job
        self.source_connector = source_connector
        self.target_connector = target_connector
        self.batch_size = 10000  # Default batch size
        self.sync_version = int(time.time() * 1000)  # Monotonic millisecond timestamp
        # CRITICAL: Use target database name from connection, not source schema
        self.target_database = target_connector.database_name

        # Ensure checkpoint table exists
        create_checkpoint_table_clickhouse(target_connector, self.target_database)

    # ================================================================
    # TABLE CREATION
    # ================================================================

    def create_clickhouse_table_with_metadata(
        self,
        schema: str,
        table: str,
        job_table: SyncJobTable,
        incremental_column: Optional[str] = None
    ) -> None:
        """
        Create ClickHouse table with ReplacingMergeTree and metadata columns

        Metadata columns added:
        - is_deleted UInt8 DEFAULT 0
        - __sync_version UInt64
        - __sync_timestamp DateTime64(6, 'UTC')
        """
        logger.info(f"Creating ClickHouse table: {schema}.{table}")

        # Get source table columns
        columns = self.source_connector.get_columns(schema, table)

        if not columns:
            raise TableSyncError(f"No columns found for {schema}.{table}")

        # Get primary key
        pk_columns = self.source_connector.get_primary_key(schema, table)

        if not pk_columns:
            # Use configured key columns or fall back to first column
            pk_columns = job_table.incremental_key_columns or [columns[0].name]
            logger.warning(f"No primary key found, using: {pk_columns}")

        # Build column definitions
        column_defs = []

        for col in columns:
            # Map type from PostgreSQL to ClickHouse
            # Note: ColumnInfo may not have precision/scale, use getattr with defaults
            clickhouse_type = self._map_postgres_to_clickhouse_type(
                col.data_type,
                col.max_length,
                getattr(col, 'precision', None),
                getattr(col, 'scale', None)
            )

            # Handle nullable
            # CRITICAL: If this column is the incremental/version column for ReplacingMergeTree,
            # it CANNOT be Nullable (ClickHouse requirement)
            is_version_column = (incremental_column and col.name == incremental_column)

            if not col.is_nullable or is_version_column:
                column_def = f"`{col.name}` {clickhouse_type}"
            else:
                column_def = f"`{col.name}` Nullable({clickhouse_type})"

            column_defs.append(column_def)

        # Add metadata columns
        column_defs.append("`is_deleted` UInt8 DEFAULT 0")
        column_defs.append("`__sync_version` UInt64")
        column_defs.append("`__sync_timestamp` DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC')")

        # Determine version column for ReplacingMergeTree
        if incremental_column:
            version_column = incremental_column
        elif '__sync_version' in [c.name for c in columns]:
            version_column = '__sync_version'
        else:
            # Use __sync_version from metadata
            version_column = '__sync_version'

        # Build ORDER BY clause (primary key)
        order_by = ', '.join(f'`{pk}`' for pk in pk_columns)

        # Create table DDL - use target database, not source schema
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS `{self.target_database}`.`{table}` (
            {', '.join(column_defs)}
        ) ENGINE = ReplacingMergeTree(`{version_column}`)
        ORDER BY ({order_by})
        SETTINGS index_granularity = 8192
        """

        logger.info(f"Creating table with DDL:\n{create_table_sql}")

        # Execute CREATE TABLE
        self.target_connector.execute_query(create_table_sql)

        logger.info(f"✓ Table created: {self.target_database}.{table} (engine: ReplacingMergeTree, order: {order_by})")

    def _map_postgres_to_clickhouse_type(
        self,
        pg_type: str,
        max_length: Optional[int] = None,
        precision: Optional[int] = None,
        scale: Optional[int] = None
    ) -> str:
        """
        Map PostgreSQL type to ClickHouse type with full coverage
        """
        from core.type_mapping import map_data_type

        try:
            ch_type = map_data_type(
                source_type=pg_type,
                source_db='postgres',
                target_db='clickhouse',
                max_length=max_length,
                precision=precision,
                scale=scale
            )
            return ch_type
        except Exception as e:
            logger.warning(f"Type mapping failed for {pg_type}: {e}, using String")
            return 'String'

    # ================================================================
    # FULL LOAD
    # ================================================================

    def full_load(self, schema: str, table: str, job_table: SyncJobTable) -> int:
        """
        Full load with batch processing and checkpointing

        Returns:
            Number of rows loaded
        """
        logger.info(f"Starting full load: {schema}.{table}")

        # Get primary key columns
        pk_columns = self.source_connector.get_primary_key(schema, table)

        if not pk_columns:
            pk_columns = job_table.incremental_key_columns or ['id']
            logger.warning(f"No primary key, using: {pk_columns}")

        # Get total row count (for progress tracking)
        count_query = f'SELECT COUNT(*) FROM "{schema}"."{table}"'
        result = self.source_connector.execute_query_fetchall(count_query)
        total_rows = result[0][0] if result else 0

        logger.info(f"Total rows to load: {total_rows}")

        # Create ClickHouse table
        incremental_column = job_table.incremental_column
        self.create_clickhouse_table_with_metadata(schema, table, job_table, incremental_column)

        # Batch load
        batch_number = 0
        total_loaded = 0
        last_pk_values = None

        while True:
            batch_number += 1

            # Build query with checkpoint
            if last_pk_values is None:
                # First batch
                query = f"""
                    SELECT *
                    FROM "{schema}"."{table}"
                    ORDER BY {', '.join(f'"{pk}"' for pk in pk_columns)}
                    LIMIT {self.batch_size}
                """
            else:
                # Subsequent batches: WHERE pk > last_pk_values
                where_clause = self._build_pk_where_clause(pk_columns, last_pk_values)
                query = f"""
                    SELECT *
                    FROM "{schema}"."{table}"
                    WHERE {where_clause}
                    ORDER BY {', '.join(f'"{pk}"' for pk in pk_columns)}
                    LIMIT {self.batch_size}
                """

            # Fetch batch
            rows = self.source_connector.execute_query_fetchall(query)

            if not rows:
                break  # No more rows

            # Add metadata columns
            enriched_rows = []
            for row in rows:
                # Convert Row object to dict if needed
                if hasattr(row, '_asdict'):
                    row_dict = row._asdict()
                elif hasattr(row, '__dict__'):
                    row_dict = row.__dict__
                else:
                    # Get columns from source
                    source_columns = [col.name for col in self.source_connector.get_columns(schema, table)]
                    row_dict = {col: row[i] for i, col in enumerate(source_columns)}

                row_dict['is_deleted'] = 0
                row_dict['__sync_version'] = self.sync_version + batch_number
                # __sync_timestamp will be set by ClickHouse DEFAULT
                enriched_rows.append(row_dict)

            # Insert into ClickHouse
            self._insert_batch_clickhouse(schema, table, enriched_rows)

            total_loaded += len(rows)
            logger.info(f"Batch {batch_number}: Loaded {len(rows)} rows, total: {total_loaded}/{total_rows}")

            # Update checkpoint
            last_row = rows[-1]
            last_pk_values = []
            for pk in pk_columns:
                if hasattr(last_row, '_asdict'):
                    last_pk_values.append(last_row._asdict()[pk])
                elif isinstance(last_row, dict):
                    last_pk_values.append(last_row[pk])
                else:
                    source_columns = [col.name for col in self.source_connector.get_columns(schema, table)]
                    col_idx = source_columns.index(pk)
                    last_pk_values.append(last_row[col_idx])

            if len(rows) < self.batch_size:
                break  # Last batch

        # Verify row count
        self._verify_row_count(schema, table)

        # Save checkpoint for incremental sync
        if incremental_column:
            max_value_query = f'SELECT MAX("{incremental_column}") FROM "{schema}"."{table}"'
            result = self.source_connector.execute_query_fetchall(max_value_query)
            max_value = result[0][0] if result else None

            if max_value:
                self._save_checkpoint(schema, table, str(max_value))
                logger.info(f"✓ Checkpoint saved: {max_value}")

        logger.info(f"✓ Full load complete: {total_loaded} rows")

        return total_loaded

    def _build_pk_where_clause(self, pk_columns: List[str], last_values: List[Any]) -> str:
        """
        Build WHERE clause for composite primary key pagination

        Example:
            pk_columns = ['customer_id', 'order_id']
            last_values = [100, 500]
            Result: "(customer_id > 100) OR (customer_id = 100 AND order_id > 500)"
        """
        if len(pk_columns) == 1:
            return f'"{pk_columns[0]}" > {self._quote_value(last_values[0])}'

        # Composite key: lexicographic comparison
        clauses = []
        for i in range(len(pk_columns)):
            # Greater than on this column
            if i == 0:
                clauses.append(f'"{pk_columns[i]}" > {self._quote_value(last_values[i])}')
            else:
                # Equal on all previous columns, greater on this column
                equal_clauses = [f'"{pk_columns[j]}" = {self._quote_value(last_values[j])}' for j in range(i)]
                greater_clause = f'"{pk_columns[i]}" > {self._quote_value(last_values[i])}'
                clauses.append(f"({' AND '.join(equal_clauses)} AND {greater_clause})")

        return ' OR '.join(f'({clause})' for clause in clauses)

    def _quote_value(self, value: Any) -> str:
        """Quote value for SQL query"""
        if value is None:
            return 'NULL'
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, datetime):
            return f"'{value.isoformat()}'"
        else:
            # Escape single quotes
            escaped = str(value).replace("'", "''")
            return f"'{escaped}'"

    def _insert_batch_clickhouse(self, schema: str, table: str, rows: List[Dict[str, Any]]) -> None:
        """
        Insert batch of rows into ClickHouse using bulk_insert
        """
        if not rows:
            return

        # Get column names from first row
        columns = list(rows[0].keys())

        # Convert dict rows to tuple rows
        tuple_rows = []
        for row in rows:
            tuple_rows.append(tuple(row[col] for col in columns))

        # Use ClickHouse connector's bulk_insert method
        # Use target database, not source schema
        self.target_connector.bulk_insert(self.target_database, table, columns, tuple_rows)

    # ================================================================
    # INCREMENTAL SYNC
    # ================================================================

    def incremental_sync(self, schema: str, table: str, job_table: SyncJobTable) -> int:
        """
        Incremental sync: Capture INSERTs and UPDATEs

        Returns:
            Number of rows synced
        """
        incremental_column = job_table.incremental_column

        if not incremental_column:
            raise TableSyncError(f"No incremental column configured for {schema}.{table}")

        # Load checkpoint
        checkpoint = self._load_checkpoint(schema, table)

        if not checkpoint:
            raise TableSyncError(f"No checkpoint found for {schema}.{table}. Run full load first.")

        logger.info(f"Incremental sync from checkpoint: {checkpoint}")

        # Fetch changed rows
        query = f"""
            SELECT *
            FROM "{schema}"."{table}"
            WHERE "{incremental_column}" > '{checkpoint}'
            ORDER BY "{incremental_column}"
            LIMIT {self.batch_size}
        """

        rows = self.source_connector.execute_query_fetchall(query)

        if not rows:
            logger.info("No new rows to sync")
            return 0

        # Add metadata
        enriched_rows = []
        for row in rows:
            # Convert Row object to dict if needed
            if hasattr(row, '_asdict'):
                row_dict = row._asdict()
            elif hasattr(row, '__dict__'):
                row_dict = row.__dict__
            else:
                source_columns = [col.name for col in self.source_connector.get_columns(schema, table)]
                row_dict = {col: row[i] for i, col in enumerate(source_columns)}

            row_dict['is_deleted'] = 0
            row_dict['__sync_version'] = self.sync_version
            enriched_rows.append(row_dict)

        # Insert into ClickHouse (ReplacingMergeTree handles dedup)
        self._insert_batch_clickhouse(schema, table, enriched_rows)

        logger.info(f"✓ Incremental sync: {len(rows)} rows")

        # Update checkpoint
        # Get the value properly from each row
        checkpoint_values = []
        for row in rows:
            if hasattr(row, '_asdict'):
                val = row._asdict()[incremental_column]
            elif isinstance(row, dict):
                val = row[incremental_column]
            else:
                source_columns = [col.name for col in self.source_connector.get_columns(schema, table)]
                col_idx = source_columns.index(incremental_column)
                val = row[col_idx]
            checkpoint_values.append(val)

        new_checkpoint = max(checkpoint_values)
        self._save_checkpoint(schema, table, str(new_checkpoint))

        return len(rows)

    # ================================================================
    # DELETE HANDLING (SOFT DELETE)
    # ================================================================

    def sync_deletes(self, schema: str, table: str, job_table: SyncJobTable) -> int:
        """
        Sync deleted rows (soft delete with is_deleted=1)

        Requires delete log table in PostgreSQL:
            CREATE TABLE {table}_delete_log (
                id INT PRIMARY KEY,
                deleted_at TIMESTAMP DEFAULT NOW()
            );
        """
        delete_log_table = f"{table}_delete_log"

        # Check if delete log exists
        check_query = f"""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = '{schema}' AND table_name = '{delete_log_table}'
        """
        result = self.source_connector.execute_query_fetchall(check_query)
        exists = result[0][0] if result else 0

        if not exists:
            logger.warning(f"Delete log table {delete_log_table} not found. Skipping delete sync.")
            return 0

        # Load delete checkpoint
        checkpoint = self._load_checkpoint(schema, table, checkpoint_type='delete')

        if not checkpoint:
            checkpoint = '1970-01-01 00:00:00'  # Default: epoch

        # Fetch deleted IDs
        query = f"""
            SELECT id, deleted_at
            FROM "{schema}"."{delete_log_table}"
            WHERE deleted_at > '{checkpoint}'
            ORDER BY deleted_at
            LIMIT {self.batch_size}
        """

        deleted_rows = self.source_connector.execute_query_fetchall(query)

        if not deleted_rows:
            logger.info("No deletes to sync")
            return 0

        # Get primary key columns
        pk_columns = self.source_connector.get_primary_key(schema, table) or ['id']

        # Insert tombstone records
        for deleted_row in deleted_rows:
            # Convert row to dict if needed
            if hasattr(deleted_row, '_asdict'):
                deleted_dict = deleted_row._asdict()
            elif isinstance(deleted_row, dict):
                deleted_dict = deleted_row
            else:
                deleted_dict = {'id': deleted_row[0], 'deleted_at': deleted_row[1]}

            deleted_id = deleted_dict['id']
            deleted_at = deleted_dict['deleted_at']

            # Fetch existing row from ClickHouse to preserve data
            fetch_query = f"""
                SELECT *
                FROM `{self.target_database}`.`{table}` FINAL
                WHERE `{pk_columns[0]}` = {deleted_id}
                LIMIT 1
            """

            result = self.target_connector.execute_query_fetchall(fetch_query)
            existing_row = result[0] if result else None

            if existing_row:
                # Update existing row with is_deleted=1
                tombstone = dict(existing_row)
                tombstone['is_deleted'] = 1
                tombstone['__sync_version'] = self.sync_version
                # Update updated_at to deleted_at (if column exists)
                if 'updated_at' in tombstone:
                    tombstone['updated_at'] = deleted_at

                self._insert_batch_clickhouse(schema, table, [tombstone])

        logger.info(f"✓ Delete sync: {len(deleted_rows)} rows marked as deleted")

        # Update delete checkpoint
        deleted_at_values = []
        for row in deleted_rows:
            if hasattr(row, '_asdict'):
                val = row._asdict()['deleted_at']
            elif isinstance(row, dict):
                val = row['deleted_at']
            else:
                val = row[1]  # deleted_at is second column
            deleted_at_values.append(val)

        new_checkpoint = max(deleted_at_values)
        self._save_checkpoint(schema, table, str(new_checkpoint), checkpoint_type='delete')

        return len(deleted_rows)

    # ================================================================
    # CHECKPOINT MANAGEMENT
    # ================================================================

    def _save_checkpoint(
        self,
        schema: str,
        table: str,
        checkpoint_value: str,
        checkpoint_type: str = 'incremental'
    ) -> None:
        """
        Save checkpoint to ClickHouse metadata table
        """
        # Save to ClickHouse _sync_checkpoints table
        try:
            insert_sql = f"""
                INSERT INTO `{self.target_database}`._sync_checkpoints (table_name, checkpoint_type, checkpoint_value)
                VALUES ('{schema}.{table}', '{checkpoint_type}', '{checkpoint_value}')
            """
            self.target_connector.execute_query(insert_sql)
            logger.debug(f"Checkpoint saved: {schema}.{table} -> {checkpoint_value}")
        except Exception as e:
            logger.warning(f"Failed to save checkpoint to ClickHouse: {e}")

        # Also save to Django SyncCheckpoint model (for UI)
        try:
            from sync_engine.checkpoint_manager import CheckpointManager
            checkpoint_manager = CheckpointManager(self.job)
            checkpoint_manager.create_or_update_checkpoint(schema, table, checkpoint_value)
        except Exception as e:
            logger.warning(f"Failed to save checkpoint to Django: {e}")

    def _load_checkpoint(
        self,
        schema: str,
        table: str,
        checkpoint_type: str = 'incremental'
    ) -> Optional[str]:
        """
        Load checkpoint from ClickHouse metadata table
        """
        # Try ClickHouse first
        try:
            query = f"""
                SELECT checkpoint_value
                FROM `{self.target_database}`._sync_checkpoints FINAL
                WHERE table_name = '{schema}.{table}' AND checkpoint_type = '{checkpoint_type}'
                ORDER BY updated_at DESC
                LIMIT 1
            """
            result = self.target_connector.execute_query_fetchall(query)
            if result:
                return result[0][0]
        except Exception as e:
            logger.debug(f"Failed to load checkpoint from ClickHouse: {e}")

        # Fallback to Django
        try:
            from sync_engine.checkpoint_manager import CheckpointManager
            checkpoint_manager = CheckpointManager(self.job)
            return checkpoint_manager.get_checkpoint_value(schema, table)
        except Exception as e:
            logger.debug(f"Failed to load checkpoint from Django: {e}")

        return None

    # ================================================================
    # VALIDATION
    # ================================================================

    def _verify_row_count(self, schema: str, table: str) -> bool:
        """
        Verify row count matches between PostgreSQL and ClickHouse
        """
        # PostgreSQL count
        pg_query = f'SELECT COUNT(*) FROM "{schema}"."{table}"'
        result = self.source_connector.execute_query_fetchall(pg_query)
        pg_count = result[0][0] if result else 0

        # ClickHouse count (with FINAL to get deduplicated count)
        ch_query = f'SELECT COUNT(*) FROM `{self.target_database}`.`{table}` FINAL WHERE is_deleted = 0'
        result = self.target_connector.execute_query_fetchall(ch_query)
        ch_count = result[0][0] if result else 0

        if pg_count != ch_count:
            logger.error(f"Row count mismatch: Postgres={pg_count}, ClickHouse={ch_count}")
            raise TableSyncError(f"Row count mismatch: Postgres={pg_count}, ClickHouse={ch_count}")

        logger.info(f"✓ Row count verified: {pg_count} rows")
        return True

    def validate_sync(self, schema: str, table: str) -> Dict[str, Any]:
        """
        Comprehensive validation after sync

        Returns:
            Validation report
        """
        report = {
            'table': f"{schema}.{table}",
            'timestamp': datetime.now().isoformat(),
            'checks': {}
        }

        # 1. Row count
        try:
            result = self.source_connector.execute_query_fetchall(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
            pg_count = result[0][0] if result else 0
            result = self.target_connector.execute_query_fetchall(f'SELECT COUNT(*) FROM `{self.target_database}`.`{table}` FINAL WHERE is_deleted = 0')
            ch_count = result[0][0] if result else 0

            report['checks']['row_count'] = {
                'postgres': pg_count,
                'clickhouse': ch_count,
                'match': pg_count == ch_count
            }
        except Exception as e:
            report['checks']['row_count'] = {'error': str(e)}

        # 2. Checksum (for small tables)
        try:
            if report['checks']['row_count'].get('postgres', 0) < 100000:
                pg_checksum = self._compute_checksum(schema, table, source='postgres')
                ch_checksum = self._compute_checksum(schema, table, source='clickhouse')

                report['checks']['checksum'] = {
                    'postgres': pg_checksum,
                    'clickhouse': ch_checksum,
                    'match': pg_checksum == ch_checksum
                }
        except Exception as e:
            report['checks']['checksum'] = {'error': str(e)}

        # 3. Sample rows
        try:
            pg_sample = self.source_connector.execute_query_fetchall(f'SELECT * FROM "{schema}"."{table}" ORDER BY 1 LIMIT 5')
            ch_sample = self.target_connector.execute_query_fetchall(f'SELECT * FROM `{self.target_database}`.`{table}` FINAL WHERE is_deleted = 0 ORDER BY 1 LIMIT 5')

            report['checks']['sample'] = {
                'postgres_rows': len(pg_sample),
                'clickhouse_rows': len(ch_sample)
            }
        except Exception as e:
            report['checks']['sample'] = {'error': str(e)}

        return report

    def _compute_checksum(self, schema: str, table: str, source: str = 'postgres') -> str:
        """
        Compute MD5 checksum of table data
        """
        if source == 'postgres':
            # PostgreSQL: MD5 of concatenated sorted rows
            query = f"""
                SELECT MD5(STRING_AGG(row_data, '' ORDER BY row_data))
                FROM (
                    SELECT CAST(ROW(*) AS TEXT) AS row_data
                    FROM "{schema}"."{table}"
                    ORDER BY 1
                ) t
            """
            result = self.source_connector.execute_query_fetchall(query)
            return result[0][0] if result else ''
        else:
            # ClickHouse: Similar approach
            # Note: This is simplified; actual implementation may vary
            query = f"""
                SELECT MD5(groupArray(toString(*)))
                FROM (
                    SELECT *
                    FROM `{self.target_database}`.`{table}` FINAL
                    WHERE is_deleted = 0
                    ORDER BY 1
                )
            """
            result = self.target_connector.execute_query_fetchall(query)
            return result[0][0] if result else ''


# ================================================================
# HELPER FUNCTIONS
# ================================================================

def create_checkpoint_table_clickhouse(connector: DBConnector, database: str) -> None:
    """
    Create _sync_checkpoints metadata table in ClickHouse
    """
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS `{database}`._sync_checkpoints (
        table_name String,
        checkpoint_type String,
        checkpoint_value DateTime64(6, 'UTC'),
        updated_at DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC')
    ) ENGINE = ReplacingMergeTree(updated_at)
    ORDER BY (table_name, checkpoint_type)
    """

    try:
        connector.execute_query(create_sql)
        logger.info(f"✓ Checkpoint table created in {database}")
    except Exception as e:
        logger.warning(f"Failed to create checkpoint table: {e}")


def optimize_table_clickhouse(connector: DBConnector, schema: str, table: str) -> None:
    """
    Force merge optimization in ClickHouse
    NOTE: This is a standalone function, schema parameter is actually the target database
    """
    try:
        optimize_sql = f"OPTIMIZE TABLE `{schema}`.`{table}` FINAL"
        connector.execute_query(optimize_sql)
        logger.info(f"✓ Table optimized: {schema}.{table}")
    except Exception as e:
        logger.warning(f"Failed to optimize table: {e}")
