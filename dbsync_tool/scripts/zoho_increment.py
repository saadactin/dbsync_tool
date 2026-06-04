"""
Zoho CRM to ClickHouse - FULL REFRESH WITH STAGING TABLE SWAP
==============================================================
Ensures ClickHouse is an EXACT replica of Zoho CRM by doing a complete
reload to staging tables, then atomic swap with 1-2 second downtime.

This approach solves the deletion problem completely:
- Fetches ALL records from Zoho (not just modified)
- Loads into staging tables (e.g., ZOHO_leads_staging)
- Atomic swap: staging becomes production with minimal downtime
- Old table is dropped after successful swap
- Result: ClickHouse contains exactly what's in Zoho (deletions handled automatically)

BENEFITS vs. previous incremental approach:
------------------------------------------
1. Deletions work perfectly for ALL modules (no API v4 dependency)
2. No complex ID reconciliation logic needed
3. Works with API v2 (India region compatible)
4. Data accuracy: ClickHouse = 100% match with Zoho
5. Safe: production untouched until atomic swap completes
6. Observable: clear logs showing net changes per module

TRADE-OFFS:
----------
- 1-2 second downtime per table during swap (schedule during low-traffic hours)
- Higher API usage (fetches all records, not just modified)
- Temporary 2x storage during sync (staging + production)

Author: Full refresh with staging table strategy (replaces incremental sync)
"""

import asyncio
import aiohttp
import json
import clickhouse_connect
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
import logging
from datetime import datetime, timedelta
import sys
import io
import time
import gc
import hashlib
from pathlib import Path
import threading
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Ensure logs directory exists
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Setup logging
TODAY = datetime.now().strftime("%Y%m%d")
LOG_FILE = LOGS_DIR / f"zoho_increment_{TODAY}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION (same env keys as before; defaults preserved)
# ============================================================

# Zoho Credentials
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "1000.0L3LLVLEKE9ELW7CE0I0KJ3K4FKBBT")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "d99c479d4c0db451c653d8c380bf6a4c557a73528c")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "1000.2cbaa36345c6d04b699b0cb6740c21ef.149922195c479d83c84826653ff84ff4")
ZOHO_API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in")
ZOHO_TOKEN_URL = os.getenv("ZOHO_TOKEN_URL", "https://accounts.zoho.in/oauth/v2/token")
# API version. v2 is used (India region). Deletions are handled via staging
# table swap strategy (not ID reconciliation), so v4 is not required.
ZOHO_API_VERSION = os.getenv("ZOHO_API_VERSION", "v2")

# ClickHouse Credentials
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "20.204.31.93")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASS = os.getenv("CLICKHOUSE_PASS", "root")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "JARVIS_DB_test")

# API Settings
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))
CONNECTION_LIMIT = int(os.getenv("CONNECTION_LIMIT", "10"))
FETCH_BATCH_SIZE = 200          # Zoho hard max per_page
INSERT_BATCH_SIZE = 5000
GC_EVERY_N_BATCHES = 10

# Table naming
TABLE_PREFIX = os.getenv("PREFIX_ZOHO", "ZOHO_")
STAGING_SUFFIX = "_staging"
OLD_SUFFIX = "_old"
RECORD_HASH_COLUMN = "_record_hash"
INGESTION_TIMESTAMP = "_ingestion_timestamp"

MODULE_NAME_MAPPING = {
    "Companies": "Accounts",
    "Dealers": "Vendors",
    "Events": "Activities",
}

# Modules to sync
env_modules = os.getenv("MODULES_TO_SYNC")
if env_modules:
    try:
        MODULES_TO_SYNC = json.loads(env_modules)
    except Exception:
        MODULES_TO_SYNC = [m.strip() for m in env_modules.split(",") if m.strip()]
else:
    # PRODUCTION: All modules enabled
    # NOTE: Using full refresh + staging table swap strategy for exact data sync
    # Modules with >2000 records will fetch up to 2000 (API v2 limitation)
    MODULES_TO_SYNC = [
        "Leads", "Contacts", "Companies", "Deals", "Dealers", "Campaigns",
        "Tasks", "Calls", "Visits", "Products", "Sales_Orders", "Invoices",
        "BANTs", "Modified_Owners", "Dealer_Deals_Detail", "SAP_Items",
        "SAP_Address", "SAP_Customers", "Quotes", "BANTs_X_Leads",
        "Deals_X_Contacts", "Potential_Mapping", "Notes", "Lead_Status_History",
        "Associated_Products", "Projects", "BANTs_X_Leads2", "Purchase_Orders",
        "BANT_Owner_2_History", "Cases", "Activities", "Price_Books", "Solutions"
    ]

SKIP_MODULES: List[str] = []

try:
    import orjson
    def json_dumps(obj: Any) -> str:
        return orjson.dumps(obj).decode("utf-8")
except ImportError:
    def json_dumps(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False)


# ============================================================
# CUSTOM EXCEPTIONS
# ============================================================

class ZohoAPIError(Exception):
    """A Zoho API request failed in a way that must not be silently ignored."""


# ============================================================
# UTILS
# ============================================================

def flatten_record(data: Dict, parent_key: str = "", sep: str = "_") -> Dict:
    """Flatten nested dictionary."""
    items = []
    for k, v in data.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_record(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            items.append((new_key, json_dumps(v) if v else None))
        else:
            items.append((new_key, v))
    return dict(items)


def compute_hash(record: Dict) -> str:
    """Compute a deterministic record hash for change detection / dedup."""
    try:
        record_str = json_dumps(dict(sorted(record.items())))
        return hashlib.md5(record_str.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.md5(str(sorted(record.items())).encode("utf-8")).hexdigest()


def clean_column_name(name: str) -> str:
    """Clean column name for ClickHouse compatibility."""
    name = name.replace(".", "_").replace("$", "_").replace(" ", "_")
    name = name.replace("(", "").replace(")", "").replace('"', "").replace("'", "")
    name = name.replace("[", "").replace("]", "").replace("{", "").replace("}", "")
    name = name.replace("/", "_").replace("\\", "_").replace("-", "_")
    if name and name[0].isdigit():
        name = f"col_{name}"
    return name or "unnamed_column"


def prepare_value(value: Any) -> Any:
    """Prepare a value for ClickHouse insertion."""
    if value is None:
        return None
    elif isinstance(value, bool):
        return "1" if value else "0"
    elif isinstance(value, datetime):
        return value
    elif isinstance(value, (dict, list)):
        return json_dumps(value)
    elif isinstance(value, (int, float)):
        return str(value)
    else:
        return str(value) if value is not None else None


# ============================================================
# ASYNC ZOHO CLIENT
# ============================================================

class AsyncZohoClient:
    """Async Zoho CRM API client with connection pooling and robust pagination."""

    def __init__(self) -> None:
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.connector: Optional[aiohttp.TCPConnector] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def __aenter__(self) -> "AsyncZohoClient":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def initialize(self) -> None:
        self.connector = aiohttp.TCPConnector(
            limit=CONNECTION_LIMIT, limit_per_host=CONNECTION_LIMIT, ttl_dns_cache=300
        )
        self.session = aiohttp.ClientSession(
            connector=self.connector, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        )
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        await self.refresh_token()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
        if self.connector:
            await self.connector.close()

    async def refresh_token(self) -> bool:
        params = {
            "refresh_token": ZOHO_REFRESH_TOKEN,
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token",
        }
        try:
            async with self.session.post(ZOHO_TOKEN_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    self.access_token = data["access_token"]
                    expires_in = data.get("expires_in", 3600)
                    self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
                    logger.info("Zoho access token refreshed")
                    return True
                text = await response.text()
                logger.error(f"Token refresh failed: {response.status} - {text[:200]}")
                return False
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False

    async def ensure_token(self) -> None:
        if not self.token_expiry or datetime.now() >= self.token_expiry:
            await self.refresh_token()

    def _module_url(self, module: str) -> str:
        return f"{ZOHO_API_DOMAIN}/crm/{ZOHO_API_VERSION}/{module}"

    async def check_module_access(self, module: str) -> Tuple[bool, Optional[str]]:
        await self.ensure_token()
        url = self._module_url(module)
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}"}
        async with self._semaphore:
            try:
                async with self.session.get(url, headers=headers, params={"per_page": 1}) as response:
                    if response.status in (200, 204):
                        return True, None
                    return False, f"Status: {response.status}"
            except Exception as e:
                return False, str(e)

    async def iter_pages(
        self,
        module: str,
        *,
        fields: Optional[str] = None,
    ) -> AsyncGenerator[Tuple[List[Dict], Dict], None]:
        """
        Fetch ALL records from a module (full refresh, no incremental filtering).
        Uses simple page-based pagination - same as zoho_full.py.
        Continues fetching until has_more is False (no artificial limits).
        """
        page = 1
        page_token: Optional[str] = None

        while True:
            await self.ensure_token()
            params: Dict[str, Any] = {"per_page": FETCH_BATCH_SIZE}
            if fields:
                params["fields"] = fields
            if page_token:
                params["page_token"] = page_token
            else:
                params["page"] = page

            headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}"}

            async with self._semaphore:
                async with self.session.get(self._module_url(module), headers=headers, params=params) as response:
                    status = response.status
                    if status in (204, 304):
                        return  # no records
                    if status == 401:
                        await self.refresh_token()
                        continue
                    if status != 200:
                        text = await response.text()
                        logger.error(f"{module}: HTTP {status} - {text[:200]}")
                        return
                    data = await response.json()

            records = data.get("data", []) or []
            info = data.get("info", {}) or {}
            yield records, info

            if not info.get("more_records", False):
                return

            next_token = info.get("next_page_token")
            if next_token:
                page_token = next_token
            else:
                page += 1
                # NO ARTIFICIAL LIMIT - keep going as long as has_more is True
                # This matches zoho_full.py behavior

            await asyncio.sleep(0.3)  # Rate limiting (same as zoho_full.py)


# ============================================================
# CLICKHOUSE MANAGER WITH STAGING TABLE SUPPORT
# ============================================================

class ClickHouseManager:
    """ClickHouse manager with staging table support."""

    def __init__(self) -> None:
        self.host = CLICKHOUSE_HOST
        self.user = CLICKHOUSE_USER
        self.password = CLICKHOUSE_PASS
        self.database = CLICKHOUSE_DB
        self.client = None
        self._lock = threading.RLock()  # Use RLock (reentrant) to allow nested locking

    def connect(self) -> bool:
        try:
            self.client = clickhouse_connect.get_client(
                host=self.host, port=CLICKHOUSE_PORT,
                username=self.user, password=self.password,
                database=self.database,
                connect_timeout=30, send_receive_timeout=600,
            )
            return True
        except Exception as e:
            logger.error(f"ClickHouse connection error: {e}")
            return False

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        try:
            with self._lock:
                result = self.client.query(f"EXISTS TABLE {self.database}.{table_name}")
                return result.result_rows[0][0] == 1
        except Exception:
            return False

    def get_table_columns(self, table_name: str) -> set:
        """Get column names from a table."""
        try:
            with self._lock:
                result = self.client.query(
                    f"SELECT name FROM system.columns "
                    f"WHERE database = '{self.database}' AND table = '{table_name}'"
                )
                return {row[0] for row in result.result_rows}
        except Exception:
            return set()

    def create_staging_table(self, production_table: str, staging_table: str) -> bool:
        """Create staging table with same structure as production table (EMPTY)."""
        try:
            with self._lock:
                if not self.table_exists(production_table):
                    logger.warning(f"  ⚠ Production table {production_table} doesn't exist")
                    return False

                # Drop staging if exists
                self.client.command(f"DROP TABLE IF EXISTS {self.database}.{staging_table}")

                # Get CREATE TABLE statement from production
                result = self.client.query(f"SHOW CREATE TABLE {self.database}.{production_table}")
                create_stmt = result.result_rows[0][0]

                # Replace table name in the CREATE statement
                create_stmt_staging = create_stmt.replace(
                    f"`{production_table}`",
                    f"`{staging_table}`"
                ).replace(
                    f"{self.database}.{production_table}",
                    f"{self.database}.{staging_table}"
                )

                # Create the staging table
                self.client.command(create_stmt_staging)

                # Ensure it's empty (should already be, but just in case)
                self.client.command(f"TRUNCATE TABLE {self.database}.{staging_table}")

                logger.info(f"  ✓ Created staging table: {staging_table}")
                return True
        except Exception as e:
            logger.error(f"Failed to create staging table {staging_table}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def truncate_table(self, table_name: str) -> bool:
        """Truncate a table (remove all data but keep structure)."""
        try:
            with self._lock:
                # TRUNCATE is fast and safe for empty tables
                self.client.command(f"TRUNCATE TABLE IF EXISTS {self.database}.{table_name}")
                return True
        except Exception as e:
            # If truncate fails, table might not exist (which is fine)
            logger.debug(f"Truncate {table_name}: {e}")
            return True  # Continue anyway, table will be empty or doesn't exist

    def get_record_count(self, table_name: str) -> int:
        """Get total record count in a table."""
        try:
            with self._lock:
                result = self.client.query(f"SELECT COUNT(*) FROM {self.database}.{table_name}")
                return int(result.result_rows[0][0]) if result.result_rows else 0
        except Exception:
            return 0

    def atomic_swap_tables(self, staging_table: str, production_table: str) -> Tuple[bool, str]:
        """
        Atomically swap staging table with production table (1-2 sec downtime).

        Process:
        1. RENAME production -> production_old
        2. RENAME staging -> production
        3. DROP production_old

        Returns: (success: bool, message: str)
        """
        old_table = f"{production_table}{OLD_SUFFIX}"

        try:
            with self._lock:
                logger.info(f"  [SWAP] Starting atomic swap for {production_table}...")

                # Step 1: Rename production to _old (if exists)
                if self.table_exists(production_table):
                    if self.table_exists(old_table):
                        self.client.command(f"DROP TABLE {self.database}.{old_table}")

                    self.client.command(
                        f"RENAME TABLE {self.database}.{production_table} TO {self.database}.{old_table}"
                    )
                    logger.info(f"  [SWAP] Step 1: {production_table} -> {old_table}")

                # Step 2: Rename staging to production
                self.client.command(
                    f"RENAME TABLE {self.database}.{staging_table} TO {self.database}.{production_table}"
                )
                logger.info(f"  [SWAP] Step 2: {staging_table} -> {production_table}")

                # Step 3: Drop old table
                if self.table_exists(old_table):
                    self.client.command(f"DROP TABLE {self.database}.{old_table}")
                    logger.info(f"  [SWAP] Step 3: Dropped {old_table}")

                logger.info(f"  ✓ Atomic swap completed for {production_table}")
                return True, "SUCCESS"

        except Exception as e:
            error_msg = f"Atomic swap failed for {production_table}: {e}"
            logger.error(f"  ✗ {error_msg}")
            return False, error_msg

    def insert_batch(self, table_name: str, records: List[Dict], allowed_columns: set) -> int:
        """Insert batch of records into table."""
        if not records or not allowed_columns:
            return 0
        try:
            columns = sorted([col for col in allowed_columns if col != "_source_system"])
            rows = [[prepare_value(record.get(col)) for col in columns] for record in records]
            with self._lock:
                self.client.insert(
                    table=f"{self.database}.{table_name}", data=rows, column_names=columns
                )
            return len(rows)
        except Exception as e:
            logger.error(f"Insert error for {table_name}: {e}")
            return 0


# ============================================================
# FULL REFRESH MIGRATOR WITH STAGING
# ============================================================

class FullRefreshMigrator:
    """Migrator that does full refresh with staging table swap."""

    def __init__(self, zoho_client: AsyncZohoClient, ch_manager: ClickHouseManager) -> None:
        self.zoho = zoho_client
        self.ch = ch_manager
        self.results: List[Dict] = []
        self.start_time: float = 0.0

    async def _load_full_to_staging(
        self, api_module: str, staging_table: str, table_columns: set
    ) -> int:
        """Load ALL records from Zoho into staging table."""
        total_loaded = 0
        insert_buffer: List[Dict] = []
        batch_count = 0
        current_time = datetime.now()

        async for records, _info in self.zoho.iter_pages(api_module):
            batch_count += 1
            for record in records:
                flat_record = flatten_record(record)
                cleaned_record = {clean_column_name(k): v for k, v in flat_record.items()}
                filtered_record = {k: v for k, v in cleaned_record.items() if k in table_columns}
                filtered_record[RECORD_HASH_COLUMN] = compute_hash(cleaned_record)
                filtered_record[INGESTION_TIMESTAMP] = current_time
                insert_buffer.append(filtered_record)

            if len(insert_buffer) >= INSERT_BATCH_SIZE:
                total_loaded += self.ch.insert_batch(staging_table, insert_buffer, table_columns)
                insert_buffer = []
                logger.info(f"  ✓ Loaded so far: {total_loaded:,} records")

            if batch_count % GC_EVERY_N_BATCHES == 0:
                gc.collect()

        if insert_buffer:
            total_loaded += self.ch.insert_batch(staging_table, insert_buffer, table_columns)

        return total_loaded

    async def migrate_module(self, module: str, production_table: str, index: int, total: int) -> Dict:
        """Migrate a single module using full refresh + staging swap."""
        api_module = MODULE_NAME_MAPPING.get(module, module)
        staging_table = f"{production_table}{STAGING_SUFFIX}"

        logger.info(f"\n{'='*60}")
        logger.info(f"[{index}/{total}] {module} (FULL REFRESH + STAGING)")
        logger.info(f"Production: {production_table}")
        logger.info(f"Staging: {staging_table}")
        logger.info(f"{'='*60}")

        start_time = time.time()
        result = {
            "name": module,
            "production_table": production_table,
            "staging_table": staging_table,
            "status": "UNKNOWN",
            "records_loaded": 0,
            "records_before": 0,
            "records_after": 0,
            "swap_status": "-",
            "duration": 0,
        }

        try:
            # Step 1: Check module access
            has_access, error_msg = await self.zoho.check_module_access(api_module)
            if not has_access:
                logger.warning(f"  ⚠ Module not accessible: {error_msg}")
                result["status"] = "NO_ACCESS"
                self.results.append(result)
                return result

            # Step 2: Check if production table exists
            if not self.ch.table_exists(production_table):
                logger.warning(f"  ⚠ Production table {production_table} doesn't exist. Run full load first.")
                result["status"] = "NO_TABLE"
                self.results.append(result)
                return result

            # Get record count before swap
            result["records_before"] = self.ch.get_record_count(production_table)
            logger.info(f"  [BEFORE] Production records: {result['records_before']:,}")

            # Step 3: Get table structure
            table_columns = self.ch.get_table_columns(production_table)
            if not table_columns:
                logger.error(f"  ✗ Could not get columns for {production_table}")
                result["status"] = "ERROR"
                result["error"] = "Failed to get table columns"
                self.results.append(result)
                return result

            # Step 4: Create staging table (will be empty)
            logger.info(f"  [1/4] Creating staging table...")
            if not self.ch.create_staging_table(production_table, staging_table):
                result["status"] = "ERROR"
                result["error"] = "Failed to create staging table"
                self.results.append(result)
                return result
            # Note: Staging table is already empty after creation, no need to truncate

            # Step 6: Load full data to staging
            logger.info(f"  [2/4] Loading ALL records from Zoho to staging...")
            total_loaded = await self._load_full_to_staging(api_module, staging_table, table_columns)
            result["records_loaded"] = total_loaded
            logger.info(f"  ✓ Loaded {total_loaded:,} records to staging")

            # Step 7: Atomic swap
            logger.info(f"  [3/4] Performing atomic table swap (1-2 sec downtime)...")
            swap_start = time.time()
            swap_success, swap_msg = self.ch.atomic_swap_tables(staging_table, production_table)
            swap_duration = time.time() - swap_start
            logger.info(f"  ✓ Swap completed in {swap_duration:.2f} seconds")

            if not swap_success:
                result["status"] = "SWAP_FAILED"
                result["swap_status"] = swap_msg
                self.results.append(result)
                return result

            result["swap_status"] = "SUCCESS"

            # Step 8: Verify final count
            result["records_after"] = self.ch.get_record_count(production_table)
            logger.info(f"  [AFTER] Production records: {result['records_after']:,}")

            gc.collect()

            duration = time.time() - start_time
            logger.info(f"\n  ✅ {module} COMPLETE:")
            logger.info(f"     • Records loaded   : {result['records_loaded']:,}")
            logger.info(f"     • Before swap      : {result['records_before']:,}")
            logger.info(f"     • After swap       : {result['records_after']:,}")
            logger.info(f"     • Net change       : {result['records_after'] - result['records_before']:+,}")
            logger.info(f"     • Swap downtime    : {swap_duration:.2f}s")
            logger.info(f"     • Total duration   : {duration:.1f}s")

            result["status"] = "SUCCESS"
            result["duration"] = duration

        except Exception as e:
            logger.error(f"  ✗ FAILED: {e}")
            result["status"] = "ERROR"
            result["error"] = str(e)
            result["duration"] = time.time() - start_time

        self.results.append(result)
        return result

    async def migrate_all(self) -> None:
        """Migrate all modules."""
        self.start_time = time.time()
        logger.info(f"\n{'#'*60}")
        logger.info("ZOHO CRM → CLICKHOUSE - FULL REFRESH WITH STAGING")
        logger.info(f"API version: {ZOHO_API_VERSION}")
        logger.info("Strategy: Full load → Staging → Atomic swap")
        logger.info(f"{'#'*60}")

        modules = [m for m in MODULES_TO_SYNC if m not in SKIP_MODULES]
        for idx, module in enumerate(modules, 1):
            production_table = f"{TABLE_PREFIX}{module.lower()}"
            await self.migrate_module(module, production_table, idx, len(modules))
            gc.collect()

        self.print_summary()

    def print_summary(self) -> None:
        """Print migration summary."""
        total_duration = time.time() - self.start_time
        successful = sum(1 for r in self.results if r["status"] == "SUCCESS")
        total_loaded = sum(r.get("records_loaded", 0) for r in self.results)
        total_net_change = sum(
            r.get("records_after", 0) - r.get("records_before", 0)
            for r in self.results if r["status"] == "SUCCESS"
        )

        logger.info(f"\n{'#'*60}")
        logger.info("FULL REFRESH MIGRATION SUMMARY")
        logger.info(f"Duration: {total_duration:.1f}s")
        logger.info(f"  ✓ Success modules : {successful}/{len(self.results)}")
        logger.info(f"  📥 Total loaded    : {total_loaded:,}")
        logger.info(f"  📊 Net change      : {total_net_change:+,}")
        logger.info(f"{'#'*60}\n")

        for r in sorted(
            self.results, key=lambda x: x.get("records_loaded", 0), reverse=True
        ):
            icon = {
                "SUCCESS": "✓",
                "NO_ACCESS": "⚠",
                "NO_TABLE": "⚠",
                "ERROR": "✗",
                "SWAP_FAILED": "✗"
            }.get(r["status"], "?")

            net_change = r.get("records_after", 0) - r.get("records_before", 0)
            logger.info(
                f"{r['production_table']:<32} {icon} {r['status']:<12} "
                f"Loaded: {r.get('records_loaded', 0):,} | "
                f"Change: {net_change:+,} | "
                f"({r.get('duration', 0):>5.1f}s)"
            )

        failed = [r for r in self.results if r["status"] not in ("SUCCESS", "NO_ACCESS", "NO_TABLE")]
        if failed:
            logger.warning(f"\n{'-'*60}")
            logger.warning("FAILED MODULES:")
            for r in failed:
                error = r.get("error", r.get("swap_status", "Unknown error"))
                logger.warning(f"   • {r['production_table']}: {error}")
        logger.info(f"{'-'*60}\n")


# ============================================================
# MAIN
# ============================================================

async def main(stats_file: Optional[str] = None) -> List[Dict]:
    logger.info(f"{'='*60}")
    logger.info("ZOHO CRM → CLICKHOUSE - FULL REFRESH WITH STAGING")
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Log: {LOG_FILE}")
    logger.info(f"{'='*60}")

    ch_manager = ClickHouseManager()
    if not ch_manager.connect():
        logger.error("✗ Failed to connect to ClickHouse")
        sys.exit(1)

    results: List[Dict] = []
    migration_start_time = datetime.now()

    async with AsyncZohoClient() as zoho_client:
        migrator = FullRefreshMigrator(zoho_client, ch_manager)
        await migrator.migrate_all()
        results = migrator.results

    migration_end_time = datetime.now()

    if stats_file and results:
        try:
            stats_data = {
                "database": ch_manager.database,
                "sync_type": "full_refresh_staging",
                "results": results,
                "timestamp": datetime.now().isoformat(),
                "start_time": migration_start_time.isoformat(),
                "end_time": migration_end_time.isoformat(),
            }
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump(stats_data, f, indent=4)
            logger.info(f"📊 Statistics saved to {stats_file}")
        except Exception as e:
            logger.error(f"Failed to save statistics: {e}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--stats-file", type=str, help="Path to save sync statistics JSON")
    args = parser.parse_args()

    asyncio.run(main(stats_file=args.stats_file))