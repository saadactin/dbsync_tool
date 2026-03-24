"""
Ultra-optimized SAP Business One to ClickHouse sync executor.
Features:
- Async parallel page fetching
- Redis-based hash caching for change detection
- Streaming batch inserts
- ReplacingMergeTree support for upserts
"""
import asyncio
import logging
import time
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from django.utils import timezone

from connections.connectors.sap import AsyncSAPConnector
from connections.connectors.sap_utils import flatten_dict, compute_record_hash
from core.constants import SAP_DOCUMENT_TYPES
from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog

logger = logging.getLogger(__name__)

# Try to import Redis
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

class HashCache:
    """Redis-based hash cache with fallback to memory"""
    def __init__(self, table_name: str, job_id: int):
        self.table_name = table_name
        self.job_id = job_id
        self.redis_client = None
        self.memory_cache = {}
        self.use_redis = False
        if REDIS_AVAILABLE:
            try:
                # In a real app, these would come from settings
                self.redis_client = redis.Redis(
                    host='localhost', port=6379, db=0,
                    decode_responses=True, socket_timeout=5
                )
                self.redis_client.ping()
                self.use_redis = True
            except: 
                self.use_redis = False
    
    def get_key(self, record_id: str) -> str:
        return f"sap_hash:{self.job_id}:{self.table_name}:{record_id}"
    
    def set_batch(self, records: Dict[str, str]):
        if self.use_redis and records:
            try:
                pipeline = self.redis_client.pipeline()
                for record_id, hash_value in records.items():
                    pipeline.set(self.get_key(record_id), hash_value, ex=86400*30)
                pipeline.execute()
                return
            except: pass
        self.memory_cache.update(records)
    
    def get_hash(self, record_id: str) -> Optional[str]:
        if self.use_redis:
            try: return self.redis_client.get(self.get_key(record_id))
            except: pass
        return self.memory_cache.get(record_id)

from asgiref.sync import sync_to_async

class OptimizedSAPSyncExecutor:
    def __init__(
        self,
        job: SyncJob,
        execution: SyncExecution,
        api_connection,
        target_connector,
    ):
        self.job = job
        self.execution = execution
        self.api_connection = api_connection
        self.target_connector = target_connector
        self.async_sap = AsyncSAPConnector(api_connection)
        
        # UI/Config values
        self.batch_size = 5000
        self.parallel_workers = 10
        self.lookback_days = 2 # Default for incremental

    async def execute(self):
        """Main entry point for async execution."""
        try:
            if not await self.async_sap.login():
                raise Exception("Failed to login to SAP via Async connector")
            
            endpoints = await sync_to_async(self._get_endpoints_from_job)()
            for idx, endpoint_name in enumerate(endpoints, 1):
                await self._sync_endpoint(endpoint_name, idx, len(endpoints))
                
        finally:
            await self.async_sap.logout()

    def _get_endpoints_from_job(self) -> List[str]:
        job_tables = self.job.tables.filter(is_enabled=True)
        return [jt.table_name for jt in job_tables if jt.table_name]

    def _get_doc_type(self, endpoint_name: str) -> Dict:
        for dt in SAP_DOCUMENT_TYPES:
            if dt["endpoint"] == endpoint_name:
                return dt
        return {"name": endpoint_name, "endpoint": endpoint_name, "id_field": "DocEntry"}

    def _normalize_column_name(self, name: str) -> str:
        normalized = name.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")
        normalized = normalized.replace("(", "").replace(")", "").replace("[", "").replace("]", "")
        if normalized and normalized[0].isdigit(): normalized = "col_" + normalized
        return normalized

    async def _sync_endpoint(self, endpoint_name: str, index: int, total: int):
        doc_type = self._get_doc_type(endpoint_name)
        id_field = doc_type["id_field"]
        inc_field = doc_type.get("incremental_field", "UpdateDate")
        
        # Use target_table if defined, else fallback to simple normalization
        raw_table = doc_type.get("target_table") or endpoint_name.lower().replace(' ', '_')
        table_name = f"SAP_{raw_table}"
        
        logger.info(f"[{index}/{total}] Syncing {endpoint_name} to {table_name}...")
        
        # Create log entry once
        log = await sync_to_async(SyncExecutionLog.objects.create)(
            execution=self.execution,
            schema_name="api",
            table_name=endpoint_name,
            status="running",
            started_at=timezone.now(),
        )
        
        # Retry logic state
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            start_time = time.time()
            total_upserted = 0
            
            try:
                # Update status for retry
                if retry_count > 0:
                    log.status = "retrying"
                    log.error_message = f"Previous attempt failed. Retrying ({retry_count}/{max_retries})..."
                    await sync_to_async(log.save)()

                filter_query = None
                if self.job.sync_type == "incremental":
                    date_limit = (datetime.now() - timedelta(days=self.lookback_days)).strftime('%Y-%m-%d')
                    filter_query = f"{inc_field} ge '{date_limit}'"
                    logger.info(f"  → Incremental filter: {filter_query}")

                hash_cache = HashCache(table_name, self.job.id)
                target_schema = self.target_connector.database_name
                current_time = datetime.now()
                normalized_id = self._normalize_column_name(id_field)

                async for batch in self.async_sap.stream_all_records(
                    endpoint_name, 
                    batch_size=self.batch_size, 
                    parallel_workers=self.parallel_workers,
                    filter_query=filter_query
                ):
                    processed_records, batch_hashes = [], {}
                    
                    # We need to flatten and transform
                    for record in batch:
                        flat_record = flatten_dict(record)
                        val_pk = flat_record.get(id_field)
                        if val_pk is None or val_pk == "None":
                            val_pk = flat_record.get("DocEntry") or flat_record.get("AbsoluteEntry") or flat_record.get("LineNum") or "0"
                        
                        record_id = str(val_pk)

                        # Normalize keys
                        normalized_record = {self._normalize_column_name(k): v for k, v in flat_record.items()}
                        
                        # Ensure PK is NEVER null for ClickHouse
                        if normalized_record.get(normalized_id) is None:
                            normalized_record[normalized_id] = record_id
                        
                        # Change detection
                        record_hash = compute_record_hash(normalized_record)
                        if self.job.sync_type == "full" or record_hash != hash_cache.get_hash(record_id):
                            normalized_record["_record_hash"] = record_hash
                            normalized_record["_last_modified"] = current_time
                            processed_records.append(normalized_record)
                            batch_hashes[record_id] = record_hash
                    
                    if processed_records:
                        # Ensure table exists using the first batch
                        if total_upserted == 0:
                            # Logic to determine actual version column based on data availability
                            actual_inc_field = inc_field
                            normalized_inc_actual = self._normalize_column_name(inc_field)
                            if normalized_inc_actual not in processed_records[0]:
                                logger.warning(f"  ! {inc_field} not found in {endpoint_name} data. Falling back to _last_modified.")
                                actual_inc_field = "_last_modified"
                                normalized_inc_actual = "_last_modified"
                            
                            self._ensure_table_exists(processed_records[0], target_schema, table_name, id_field, actual_inc_field)
                        
                        # Insert batch
                        inserted = self._insert_batch(target_schema, table_name, processed_records, normalized_inc_actual)
                        total_upserted += inserted
                        hash_cache.set_batch(batch_hashes)
                        
                        log.rows_inserted = total_upserted
                        await sync_to_async(log.save)()

                log.status = "completed"
                log.completed_at = timezone.now()
                await sync_to_async(log.save)()
                logger.info(f"  ✓ {endpoint_name} completed: {total_upserted} rows in {time.time() - start_time:.1f}s")
                return # Success!

            except Exception as e:
                retry_count += 1
                logger.error(f"  ✗ Error syncing {endpoint_name} (Attempt {retry_count}/{max_retries}): {e}")
                log.status = "failed"
                log.error_message = f"Attempt {retry_count} failed: {str(e)}"
                log.completed_at = timezone.now()
                await sync_to_async(log.save)()
                
                if retry_count < max_retries:
                    wait_time = retry_count * 5
                    logger.info(f"  ⏳ Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"  ‼ Maximum retries reached for {endpoint_name}. Skipping to next module.")

    def _get_column_type(self, col_name: str, value: Any, is_version: bool = False) -> str:
        """Simple type inference for SAP to ClickHouse."""
        # Version columns MUST be Date/DateTime or Int
        if is_version:
            if "Date" in col_name or "Time" in col_name or col_name == "_last_modified":
                return "DateTime"
            return "Int64"
        
        # ID Column should be String for flexibility
        
        # General Dates
        if "Date" in col_name or "Time" in col_name:
            return "Nullable(DateTime)"
        
        # Numbers
        if isinstance(value, (int, float)):
            return "Nullable(Float64)"
        
        return "Nullable(String)"

    def _ensure_table_exists(self, sample_data: Dict, schema: str, table: str, id_field: str, inc_field: str):
        """Create ClickHouse table with ReplacingMergeTree."""
        normalized_id = self._normalize_column_name(id_field)
        normalized_version = self._normalize_column_name(inc_field)

        if self.target_connector.table_exists(schema, table):
            # Verify if the existing table has the required PK and Version columns
            try:
                # Simple check for column existence
                self.target_connector.execute_query(f"SELECT `{normalized_id}`, `{normalized_version}` FROM `{schema}`.`{table}` LIMIT 0")
                return
            except Exception as e:
                logger.warning(f"Table {table} schema mismatch or missing columns ({normalized_id}/{normalized_version}). Recreating. Error: {e}")
                self.target_connector.execute_query(f"DROP TABLE IF EXISTS `{schema}`.`{table}`")
        
        # Build columns
        column_defs = []
        for key, value in sample_data.items():
            col_name = self._normalize_column_name(key)
            is_pk = (col_name == normalized_id)
            is_ver = (col_name == normalized_version)
            
            if is_pk:
                column_defs.append(f"`{col_name}` String")
            else:
                col_type = self._get_column_type(col_name, value, is_version=is_ver)
                column_defs.append(f"`{col_name}` {col_type}")
        
        # Add internal columns if not there
        if "_last_modified" not in sample_data:
            column_defs.append("`_last_modified` DateTime DEFAULT now()")
        if "_record_hash" not in sample_data:
            column_defs.append("`_record_hash` Nullable(String)")

        create_query = f"""
            CREATE TABLE IF NOT EXISTS `{schema}`.`{table}` (
                {', '.join(column_defs)}
            ) ENGINE = ReplacingMergeTree(`{normalized_version}`)
            ORDER BY (`{normalized_id}`)
        """
        self.target_connector.execute_query(create_query)
        logger.info(f"Created optimized ClickHouse table {schema}.{table} with version={normalized_version}")

    def _parse_sap_date(self, val: Any) -> Optional[datetime]:
        """Convert various SAP date formats to Python datetime."""
        if not val or val == "None": return None
        if isinstance(val, datetime): return val
        
        s = str(val).strip()
        if not s: return None
        
        try:
            # Try ISO format (2024-03-17T00:00:00Z)
            if 'T' in s:
                return datetime.fromisoformat(s.replace('Z', ''))
            # Try YYYY-MM-DD
            if len(s) == 10 and s[4] == '-' and s[7] == '-':
                return datetime.strptime(s, "%Y-%m-%d")
            # Try YYYYMMDD
            if len(s) == 8 and s.isdigit():
                return datetime.strptime(s, "%Y%m%d")
        except: pass
        return None

    def _insert_batch(self, schema: str, table: str, records: List[Dict], normalized_version: str) -> int:
        """Standardize records and insert (synchronous)."""
        if not records: return 0
        
        columns = list(records[0].keys())
        rows = []
        date_cols = {c for c in columns if "Date" in c or "Time" in c or c == "_last_modified"}
        
        for rec in records:
            row = []
            for col in columns:
                val = rec.get(col)
                if val is None:
                    # Version column MUST NOT be null
                    if col == normalized_version:
                        row.append(rec.get("_last_modified") or datetime.now())
                    else:
                        row.append(None)
                elif col in date_cols:
                    dt = self._parse_sap_date(val)
                    if dt is None:
                        # Fallback for version column
                        if col == normalized_version:
                            row.append(rec.get("_last_modified") or datetime.now())
                        else:
                            row.append(None)
                    else:
                        row.append(dt)
                elif isinstance(val, (dict, list)):
                    row.append(json.dumps(val))
                else:
                    row.append(val)
            rows.append(tuple(row))
            
        try:
            self.target_connector.bulk_insert(
                schema=schema,
                table=table,
                columns=columns,
                rows=rows
            )
            return len(rows)
        except Exception as e:
            logger.error(f"Bulk insert failed for {table}: {e}")
            raise
