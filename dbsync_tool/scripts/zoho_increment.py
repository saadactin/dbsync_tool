"""
Zoho API to ClickHouse Incremental Data Pipeline
Author: Auto-generated
Description: Incremental sync - only fetch new/updated records from Zoho and upsert into ClickHouse
Version: 1.1 (Fixed - includes automatic deduplication)
"""

import requests
import clickhouse_connect
import pandas as pd
import numpy as np
import json
import time
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from pathlib import Path

# Fix Unicode encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Create logs directory if it doesn't exist
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Configure logging with UTF-8 encoding - daily log files in logs folder
log_filename = LOGS_DIR / f"sync_{datetime.now().strftime('%Y-%m-%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class Config:
    """Configuration for Zoho and ClickHouse"""
    
    # Zoho Credentials
    ZOHO_CLIENT_ID = "1000.0L3LLVLEKE9ELW7CE0I0KJ3K4FKBBT"
    ZOHO_CLIENT_SECRET = "d99c479d4c0db451c653d8c380bf6a4c557a73528c"
    ZOHO_REFRESH_TOKEN = "1000.2cbaa36345c6d04b699b0cb6740c21ef.149922195c479d83c84826653ff84ff4"
    ZOHO_API_DOMAIN = "https://www.zohoapis.in"
    
    # ClickHouse Credentials
    CLICKHOUSE_HOST = "74.225.251.123"
    CLICKHOUSE_PORT = 8123
    CLICKHOUSE_USERNAME = "default"
    CLICKHOUSE_PASSWORD = "root"
    CLICKHOUSE_DATABASE = "testnew5"
    
    # API Settings
    ZOHO_TOKEN_URL = "https://accounts.zoho.in/oauth/v2/token"
    BATCH_SIZE = 1000
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 30
    
    # Incremental sync settings
    SYNC_STATE_TABLE = "zoho_sync_state"
    LOOKBACK_HOURS = 24  # Default lookback period if no last sync found
    
    # Auto-optimize settings
    AUTO_OPTIMIZE_TABLES = True  # Automatically deduplicate after sync
    OPTIMIZE_THRESHOLD = 100  # Only optimize if more than 100 records were updated
    
    # Zoho CRM Modules to sync
    MODULES_TO_SYNC = [
        "Leads",
        "Contacts",
        "Companies",
        "Deals",
        "Dealers",
        "Campaigns",
        "Tasks",
        "Calls",
        "Visits",
        "Products",
        "Sales_Orders",
        "Invoices",
        "BANTs",
        "Modified_Owners",
        "Dealer_Deals_Detail",
        "SAP_Items",
        "SAP_Address",
        "SAP_Customers",
        "Quotes",
        "BANTs_X_Leads",
        "Deals_X_Contacts",
        "Potential_Mapping",
        "Notes",
        "Lead_Status_History",
        "Associated_Products",
        "Projects",
        "BANTs_X_Leads2",
        "Purchase_Orders",
        "BANT_Owner_2_History",
        "Cases",
        "Activities",
        "Price_Books",
        "Solutions"
    ]
    
    # Mapping from display names to API names
    MODULE_NAME_MAPPING = {
        "Companies": "Accounts",
        "Dealers": "Vendors",
        "Events": "Activities",
    }
    
    # Table name prefix
    TABLE_PREFIX = "zoho_"


class ZohoAuthenticator:
    """Handles Zoho OAuth authentication"""
    
    def __init__(self, config: Config):
        self.config = config
        self.access_token = None
        self.token_expiry = None
    
    def get_access_token(self) -> str:
        """Get valid access token, refresh if needed"""
        if self.access_token and self._is_token_valid():
            return self.access_token
        
        return self._refresh_access_token()
    
    def _is_token_valid(self) -> bool:
        """Check if current token is still valid"""
        if not self.token_expiry:
            return False
        return datetime.now() < self.token_expiry
    
    def _refresh_access_token(self) -> str:
        """Refresh access token using refresh token"""
        logger.info("Refreshing Zoho access token...")
        
        params = {
            'refresh_token': self.config.ZOHO_REFRESH_TOKEN,
            'client_id': self.config.ZOHO_CLIENT_ID,
            'client_secret': self.config.ZOHO_CLIENT_SECRET,
            'grant_type': 'refresh_token'
        }
        
        try:
            response = requests.post(
                self.config.ZOHO_TOKEN_URL,
                params=params,
                timeout=self.config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            self.access_token = data['access_token']
            expires_in = data.get('expires_in', 3600)
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
            
            logger.info("[OK] Access token refreshed successfully")
            return self.access_token
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to refresh access token: {e}")
            raise


class SyncStateManager:
    """Manages sync state tracking in ClickHouse"""
    
    def __init__(self, db_handler, config: Config):
        self.db_handler = db_handler
        self.config = config
        self._ensure_state_table_exists()
    
    def _ensure_state_table_exists(self):
        """Create sync state table if it doesn't exist"""
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {self.config.CLICKHOUSE_DATABASE}.{self.config.SYNC_STATE_TABLE}
        (
            module_name String,
            last_sync_time DateTime,
            last_modified_time DateTime,
            records_synced Int64,
            sync_status String,
            error_message String
        )
        ENGINE = ReplacingMergeTree(last_sync_time)
        ORDER BY (module_name)
        """
        
        try:
            self.db_handler.client.command(create_query)
            logger.info(f"[OK] Sync state table ready: {self.config.SYNC_STATE_TABLE}")
        except Exception as e:
            logger.error(f"[ERROR] Failed to create sync state table: {e}")
            raise
    
    def get_last_sync_time(self, module: str) -> Optional[datetime]:
        """Get last successful sync time for a module"""
        query = f"""
        SELECT max(last_modified_time) as last_time
        FROM {self.config.CLICKHOUSE_DATABASE}.{self.config.SYNC_STATE_TABLE}
        FINAL
        WHERE module_name = '{module}' AND sync_status = 'success'
        """
        
        try:
            result = self.db_handler.client.query(query)
            if result.result_rows and result.result_rows[0][0]:
                last_time = result.result_rows[0][0]
                logger.info(f"  Last sync for {module}: {last_time}")
                return last_time
            else:
                # No previous sync found, use lookback period
                lookback_time = datetime.now() - timedelta(hours=self.config.LOOKBACK_HOURS)
                logger.info(f"  No previous sync for {module}, using lookback: {lookback_time}")
                return lookback_time
        except Exception as e:
            logger.warning(f"  Could not get last sync time for {module}: {e}")
            return datetime.now() - timedelta(hours=self.config.LOOKBACK_HOURS)
    
    def update_sync_state(self, module: str, last_modified_time: datetime, 
                         records_synced: int, status: str = 'success', 
                         error_message: str = ''):
        """Update sync state for a module"""
        data = {
            'module_name': [module],
            'last_sync_time': [datetime.now()],
            'last_modified_time': [last_modified_time],
            'records_synced': [records_synced],
            'sync_status': [status],
            'error_message': [error_message]
        }
        
        df = pd.DataFrame(data)
        
        try:
            self.db_handler.client.insert_df(self.config.SYNC_STATE_TABLE, df)
            logger.info(f"  [OK] Updated sync state for {module}")
        except Exception as e:
            logger.error(f"  [ERROR] Failed to update sync state for {module}: {e}")


class ZohoIncrementalExtractor:
    """Extracts incremental data from Zoho API"""
    
    def __init__(self, authenticator: ZohoAuthenticator, config: Config):
        self.authenticator = authenticator
        self.config = config
    
    def check_module_access(self, module: str) -> bool:
        """Check if we have access to a specific module"""
        url = f"{self.config.ZOHO_API_DOMAIN}/crm/v2/{module}"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
        try:
            response = requests.get(
                url, 
                headers=headers, 
                params={'per_page': 1},
                timeout=self.config.REQUEST_TIMEOUT
            )
            
            if response.status_code in [200, 204]:
                return True
            else:
                logger.warning(f"Module {module} not accessible - Status: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error checking module {module} access: {e}")
            return False
    
    def fetch_modified_records(self, module: str, since_time: datetime) -> Tuple[List[Dict], datetime]:
        """Fetch records modified since a specific time"""
        all_records = []
        page = 1
        per_page = 200
        max_modified_time = since_time
        
        # Format time for Zoho API (ISO 8601)
        since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S') + '+05:30'  # India timezone
        
        logger.info(f"  Fetching records modified since: {since_str}")
        
        while True:
            params = {
                'page': page,
                'per_page': per_page,
                'sort_by': 'Modified_Time',
                'sort_order': 'asc',
                'fields': 'Modified_Time'  # Always include Modified_Time
            }
            
            # Use search API with Modified_Time criteria
            records, has_more = self._fetch_modified_page(module, since_str, params)
            
            if not records:
                break
            
            # Track the latest modified time
            for record in records:
                if 'Modified_Time' in record:
                    try:
                        record_time = pd.to_datetime(record['Modified_Time'])
                        if record_time > max_modified_time:
                            max_modified_time = record_time
                    except:
                        pass
            
            all_records.extend(records)
            logger.info(f"    Page {page}: +{len(records)} records (Total: {len(all_records)})")
            
            if not has_more:
                break
            
            page += 1
            time.sleep(0.5)  # Rate limiting
        
        return all_records, max_modified_time
    
    def _fetch_modified_page(self, module: str, since_time: str, params: Dict) -> Tuple[List[Dict], bool]:
        """Fetch a single page of modified data"""
        # Use the search API with modified time filter
        url = f"{self.config.ZOHO_API_DOMAIN}/crm/v2/{module}/search"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
        # Add search criteria for modified time
        params['criteria'] = f"(Modified_Time:greater_equal:{since_time})"
        
        for attempt in range(self.config.MAX_RETRIES):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.config.REQUEST_TIMEOUT
                )
                
                if response.status_code == 204:  # No content
                    return [], False
                
                if response.status_code == 400:
                    # Search might not be supported, fall back to regular fetch
                    logger.info(f"    Search API not available for {module}, fetching all records")
                    return self._fetch_all_and_filter(module, since_time, params)
                    
                response.raise_for_status()
                
                data = response.json()
                records = data.get('data', [])
                has_more = data.get('info', {}).get('more_records', False)
                
                return records, has_more
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"    Attempt {attempt + 1} failed: {e}")
                if attempt < self.config.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                else:
                    # Fall back to fetching all records
                    return self._fetch_all_and_filter(module, since_time, params)
        
        return [], False
    
    def _fetch_all_and_filter(self, module: str, since_time: str, params: Dict) -> Tuple[List[Dict], bool]:
        """Fallback: fetch all records and filter by modified time"""
        url = f"{self.config.ZOHO_API_DOMAIN}/crm/v2/{module}"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
        # Remove search criteria
        fetch_params = {k: v for k, v in params.items() if k != 'criteria'}
        
        try:
            response = requests.get(
                url,
                headers=headers,
                params=fetch_params,
                timeout=self.config.REQUEST_TIMEOUT
            )
            
            if response.status_code == 204:
                return [], False
                
            response.raise_for_status()
            
            data = response.json()
            all_records = data.get('data', [])
            has_more = data.get('info', {}).get('more_records', False)
            
            # Filter by modified time
            since_dt = pd.to_datetime(since_time)
            filtered_records = []
            
            for record in all_records:
                if 'Modified_Time' in record:
                    try:
                        record_time = pd.to_datetime(record['Modified_Time'])
                        if record_time >= since_dt:
                            filtered_records.append(record)
                    except:
                        # Include if we can't parse time
                        filtered_records.append(record)
                else:
                    # Include if no Modified_Time field
                    filtered_records.append(record)
            
            return filtered_records, has_more
            
        except Exception as e:
            logger.error(f"    Error fetching records: {e}")
            return [], False


class DataTransformer:
    """Transforms and flattens JSON data"""
    
    @staticmethod
    def flatten_json(data: List[Dict]) -> pd.DataFrame:
        """Flatten nested JSON to pandas DataFrame"""
        if not data:
            return pd.DataFrame()
        
        df = pd.json_normalize(data, sep='_')
        
        # Convert complex objects to JSON strings
        for col in df.columns:
            if df[col].dtype == 'object':
                try:
                    if any(isinstance(x, (dict, list)) for x in df[col].dropna()):
                        df[col] = df[col].apply(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)
                except:
                    pass
        
        # Clean column names
        df.columns = [DataTransformer._clean_column_name(col) for col in df.columns]
        
        # Add/update ingestion timestamp
        df['_ingestion_timestamp'] = datetime.now()
        
        return df
    
    @staticmethod
    def prepare_for_clickhouse(df: pd.DataFrame) -> pd.DataFrame:
        """Prepare DataFrame for ClickHouse insertion"""
        df = df.copy()
        
        # Replace NaN and None
        for col in df.columns:
            dtype = df[col].dtype
            
            if dtype in ['float64', 'float32']:
                df[col] = df[col].fillna(0.0)
            elif dtype in ['int64', 'int32']:
                df[col] = df[col].fillna(0)
            elif dtype == 'object':
                df[col] = df[col].fillna('')
            elif dtype == 'bool':
                df[col] = df[col].fillna(False)
            elif 'datetime' in str(dtype):
                df[col] = df[col].fillna(pd.Timestamp('1970-01-01'))
        
        # Convert remaining problematic types
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str)
        
        return df
    
    @staticmethod
    def _clean_column_name(name: str) -> str:
        """Clean column name for ClickHouse compatibility"""
        name = name.replace('.', '_').replace('$', '_').replace(' ', '_')
        name = name.replace('(', '').replace(')', '').replace('"', '').replace("'", '')
        return name


class ClickHouseHandler:
    """Handles ClickHouse database operations"""
    
    def __init__(self, config: Config):
        self.config = config
        self.client = None
        self._connect()
    
    def _connect(self):
        """Establish connection to ClickHouse"""
        try:
            self.client = clickhouse_connect.get_client(
                host=self.config.CLICKHOUSE_HOST,
                port=self.config.CLICKHOUSE_PORT,
                username=self.config.CLICKHOUSE_USERNAME,
                password=self.config.CLICKHOUSE_PASSWORD,
                database=self.config.CLICKHOUSE_DATABASE
            )
            logger.info("[OK] Connected to ClickHouse successfully")
        except Exception as e:
            logger.error(f"[ERROR] Failed to connect to ClickHouse: {e}")
            raise
    
    def table_exists(self, table_name: str) -> bool:
        """Check if table exists"""
        query = f"EXISTS TABLE {self.config.CLICKHOUSE_DATABASE}.{table_name}"
        result = self.client.command(query)
        return result == 1
    
    def get_table_columns(self, table_name: str) -> List[str]:
        """Get list of column names from existing table"""
        query = f"DESCRIBE TABLE {self.config.CLICKHOUSE_DATABASE}.{table_name}"
        result = self.client.query(query)
        columns = [row[0] for row in result.result_rows]
        return columns
    
    def add_missing_columns(self, table_name: str, df: pd.DataFrame):
        """Add any missing columns to the existing table"""
        existing_columns = set(self.get_table_columns(table_name))
        new_columns = set(df.columns) - existing_columns
        
        if new_columns:
            logger.info(f"  Adding {len(new_columns)} new columns to {table_name}")
            for col in new_columns:
                dtype = df[col].dtype
                ch_type = self._map_dtype_to_clickhouse(dtype)
                
                alter_query = f"""
                ALTER TABLE {self.config.CLICKHOUSE_DATABASE}.{table_name}
                ADD COLUMN IF NOT EXISTS `{col}` {ch_type}
                """
                
                try:
                    self.client.command(alter_query)
                    logger.info(f"    Added column: {col} ({ch_type})")
                except Exception as e:
                    logger.warning(f"    Could not add column {col}: {e}")
    
    def optimize_table(self, table_name: str):
        """Force merge to deduplicate records in ReplacingMergeTree"""
        try:
            logger.info(f"  Deduplicating {table_name}...")
            start_time = time.time()
            
            self.client.command(f'OPTIMIZE TABLE {self.config.CLICKHOUSE_DATABASE}.{table_name} FINAL')
            
            elapsed = time.time() - start_time
            logger.info(f"  [OK] Deduplicated {table_name} in {elapsed:.2f}s")
        except Exception as e:
            logger.warning(f"  Could not optimize {table_name}: {e}")
    
    def upsert_dataframe(self, table_name: str, df: pd.DataFrame) -> Tuple[int, int]:
        """
        Upsert DataFrame into ClickHouse table
        Returns: (rows_inserted, rows_updated)
        """
        if df.empty:
            return 0, 0
        
        # Ensure table has all necessary columns
        if self.table_exists(table_name):
            self.add_missing_columns(table_name, df)
            
            # Get existing IDs to determine inserts vs updates
            existing_ids = self._get_existing_ids(table_name, df)
            
            # Split into inserts and updates
            df_insert = df[~df['id'].isin(existing_ids)]
            df_update = df[df['id'].isin(existing_ids)]
            
            rows_inserted = len(df_insert)
            rows_updated = len(df_update)
            
            # Insert new records
            if not df_insert.empty:
                self._insert_records(table_name, df_insert)
            
            # Update existing records (in ClickHouse, we just insert again and use ReplacingMergeTree)
            if not df_update.empty:
                self._insert_records(table_name, df_update)
            
            return rows_inserted, rows_updated
        else:
            # Table doesn't exist, create and insert all
            self._create_table_from_dataframe(table_name, df)
            self._insert_records(table_name, df)
            return len(df), 0
    
    def _get_existing_ids(self, table_name: str, df: pd.DataFrame) -> set:
        """Get set of existing IDs from ClickHouse table"""
        if 'id' not in df.columns:
            return set()
        
        ids = df['id'].tolist()
        if not ids:
            return set()
        
        # Create comma-separated list of IDs for query
        ids_str = ','.join([f"'{str(id_val)}'" for id_val in ids])
        
        query = f"""
        SELECT DISTINCT id 
        FROM {self.config.CLICKHOUSE_DATABASE}.{table_name}
        WHERE id IN ({ids_str})
        """
        
        try:
            result = self.client.query(query)
            existing = {row[0] for row in result.result_rows}
            return existing
        except Exception as e:
            logger.warning(f"  Could not check existing IDs: {e}")
            return set()
    
    def _insert_records(self, table_name: str, df: pd.DataFrame):
        """Insert records into ClickHouse"""
        if df.empty:
            return
        
        try:
            self.client.insert_df(table_name, df)
        except Exception as e:
            logger.error(f"  [ERROR] Failed to insert records: {e}")
            raise
    
    def _create_table_from_dataframe(self, table_name: str, df: pd.DataFrame):
        """Create table based on DataFrame schema using ReplacingMergeTree"""
        columns = []
        for col, dtype in df.dtypes.items():
            ch_type = self._map_dtype_to_clickhouse(dtype)
            columns.append(f"`{col}` {ch_type}")
        
        columns_str = ',\n    '.join(columns)
        
        # Use id as primary key if available
        primary_key = 'id' if 'id' in df.columns else df.columns[0]
        
        # Use ReplacingMergeTree for automatic deduplication based on ORDER BY key
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {self.config.CLICKHOUSE_DATABASE}.{table_name}
        (
            {columns_str}
        )
        ENGINE = ReplacingMergeTree(_ingestion_timestamp)
        ORDER BY ({primary_key})
        """
        
        try:
            self.client.command(create_query)
            logger.info(f"[OK] Table {table_name} created with ReplacingMergeTree engine")
        except Exception as e:
            logger.error(f"[ERROR] Failed to create table: {e}")
            raise
    
    def get_row_count(self, table_name: str) -> int:
        """Get current row count in table"""
        try:
            query = f"SELECT count() FROM {self.config.CLICKHOUSE_DATABASE}.{table_name}"
            result = self.client.command(query)
            return result
        except:
            return 0
    
    @staticmethod
    def _map_dtype_to_clickhouse(dtype) -> str:
        """Map pandas dtype to ClickHouse type"""
        dtype_str = str(dtype)
        
        if 'int' in dtype_str:
            return 'Int64'
        elif 'float' in dtype_str:
            return 'Float64'
        elif 'bool' in dtype_str:
            return 'UInt8'
        elif 'datetime' in dtype_str:
            return 'DateTime'
        else:
            return 'String'


class IncrementalSyncPipeline:
    """Main incremental sync pipeline orchestrator"""
    
    def __init__(self, config: Config):
        self.config = config
        self.authenticator = ZohoAuthenticator(config)
        self.db_handler = ClickHouseHandler(config)
        self.state_manager = SyncStateManager(self.db_handler, config)
        self.extractor = ZohoIncrementalExtractor(self.authenticator, config)
        self.transformer = DataTransformer()
        self.sync_summary = defaultdict(lambda: {
            'status': 'pending',
            'records_fetched': 0,
            'rows_inserted': 0,
            'rows_updated': 0,
            'total_rows': 0,
            'time': 0,
            'error': ''
        })
        self.tables_to_optimize = []
    
    def run_incremental_sync_single_module(self, module: str, table_name: str):
        """Run incremental sync for a single module"""
        logger.info(f"\n{'='*80}")
        logger.info(f"INCREMENTAL SYNC: {module}")
        logger.info(f"TABLE: {table_name}")
        logger.info(f"{'='*80}")
        
        start_time = time.time()
        
        # Map display name to API name if needed
        api_module_name = self.config.MODULE_NAME_MAPPING.get(module, module)
        if api_module_name != module:
            logger.info(f"Using API name: {api_module_name} (display name: {module})")
        
        try:
            # Check module access
            if not self.extractor.check_module_access(api_module_name):
                logger.warning(f"[SKIP] Module {module} not accessible")
                self.sync_summary[module].update({
                    'status': 'skipped',
                    'error': 'module_not_accessible',
                    'time': time.time() - start_time
                })
                return
            
            # Get last sync time
            last_sync_time = self.state_manager.get_last_sync_time(module)
            
            # Fetch modified records
            logger.info(f"[1/3] Fetching modified records from {module}...")
            raw_data, max_modified_time = self.extractor.fetch_modified_records(
                api_module_name, 
                last_sync_time
            )
            
            if not raw_data:
                logger.info(f"[OK] No new or updated records found in {module}")
                self.sync_summary[module].update({
                    'status': 'success',
                    'records_fetched': 0,
                    'time': time.time() - start_time
                })
                
                # Update sync state even if no records
                self.state_manager.update_sync_state(
                    module, 
                    max_modified_time, 
                    0, 
                    'success'
                )
                return
            
            logger.info(f"[OK] Fetched {len(raw_data)} modified records")
            
            # Transform data
            logger.info(f"[2/3] Transforming data...")
            df = self.transformer.flatten_json(raw_data)
            df = self.transformer.prepare_for_clickhouse(df)
            logger.info(f"[OK] Prepared {len(df)} rows x {len(df.columns)} columns")
            
            # Upsert into ClickHouse
            logger.info(f"[3/3] Upserting into {table_name}...")
            rows_inserted, rows_updated = self.db_handler.upsert_dataframe(table_name, df)
            
            # Track tables that need optimization
            if self.config.AUTO_OPTIMIZE_TABLES and (rows_inserted + rows_updated) >= self.config.OPTIMIZE_THRESHOLD:
                self.tables_to_optimize.append(table_name)
            
            total_rows = self.db_handler.get_row_count(table_name)
            elapsed = time.time() - start_time
            
            logger.info(f"[OK] Upsert complete:")
            logger.info(f"  - New records inserted: {rows_inserted}")
            logger.info(f"  - Existing records updated: {rows_updated}")
            logger.info(f"  - Total rows in table: {total_rows}")
            logger.info(f"  - Time elapsed: {elapsed:.2f}s")
            
            # Update sync summary
            self.sync_summary[module].update({
                'status': 'success',
                'records_fetched': len(raw_data),
                'rows_inserted': rows_inserted,
                'rows_updated': rows_updated,
                'total_rows': total_rows,
                'time': elapsed
            })
            
            # Update sync state
            self.state_manager.update_sync_state(
                module,
                max_modified_time,
                len(raw_data),
                'success'
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[ERROR] Failed to sync {module}: {e}")
            
            self.sync_summary[module].update({
                'status': 'failed',
                'error': str(e),
                'time': elapsed
            })
            
            # Update sync state with error
            self.state_manager.update_sync_state(
                module,
                datetime.now(),
                0,
                'failed',
                str(e)
            )
    
    def optimize_tables(self):
        """Optimize (deduplicate) all tables that had updates"""
        if not self.tables_to_optimize:
            logger.info("\n[INFO] No tables need optimization")
            return
        
        logger.info(f"\n{'='*80}")
        logger.info(f"DEDUPLICATING TABLES ({len(self.tables_to_optimize)} tables)")
        logger.info(f"{'='*80}")
        
        for idx, table in enumerate(self.tables_to_optimize, 1):
            logger.info(f"[{idx}/{len(self.tables_to_optimize)}] {table}")
            self.db_handler.optimize_table(table)
        
        logger.info(f"[OK] Deduplication complete for {len(self.tables_to_optimize)} tables")
    
    def run_all_modules(self, modules: List[str] = None):
        """Run incremental sync for all modules"""
        if modules is None:
            modules = self.config.MODULES_TO_SYNC
        
        overall_start = time.time()
        
        logger.info("\n" + "="*80)
        logger.info("ZOHO CRM -> CLICKHOUSE INCREMENTAL SYNC")
        logger.info("="*80)
        logger.info(f"Sync started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Modules to sync: {len(modules)}")
        logger.info(f"Target database: {self.config.CLICKHOUSE_DATABASE}")
        logger.info(f"Auto-optimize: {self.config.AUTO_OPTIMIZE_TABLES}")
        logger.info("="*80)
        
        for idx, module in enumerate(modules, 1):
            table_name = f"{self.config.TABLE_PREFIX}{module.lower()}"
            logger.info(f"\n[{idx}/{len(modules)}] Processing {module}...")
            
            self.run_incremental_sync_single_module(module, table_name)
        
        # Optimize tables after all syncs
        if self.config.AUTO_OPTIMIZE_TABLES:
            self.optimize_tables()
        
        overall_elapsed = time.time() - overall_start
        
        # Generate detailed summary
        self._generate_detailed_summary(overall_elapsed)
    
    def _generate_detailed_summary(self, total_time: float):
        """Generate and log detailed sync summary"""
        logger.info("\n" + "="*80)
        logger.info("INCREMENTAL SYNC SUMMARY")
        logger.info("="*80)
        logger.info(f"Sync completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Total time: {total_time:.2f}s ({total_time/60:.2f} minutes)")
        logger.info("="*80)
        
        # Calculate totals
        total_fetched = sum(s['records_fetched'] for s in self.sync_summary.values())
        total_inserted = sum(s['rows_inserted'] for s in self.sync_summary.values())
        total_updated = sum(s['rows_updated'] for s in self.sync_summary.values())
        
        success_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'success')
        failed_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'failed')
        skipped_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'skipped')
        
        logger.info(f"\nOVERALL STATISTICS:")
        logger.info(f"  Successful syncs: {success_count}")
        logger.info(f"  Failed syncs: {failed_count}")
        logger.info(f"  Skipped syncs: {skipped_count}")
        logger.info(f"  Total records fetched: {total_fetched:,}")
        logger.info(f"  Total new records inserted: {total_inserted:,}")
        logger.info(f"  Total existing records updated: {total_updated:,}")
        logger.info(f"  Total changes: {total_inserted + total_updated:,}")
        logger.info(f"  Tables deduplicated: {len(self.tables_to_optimize)}")
        
        logger.info("\n" + "-"*80)
        logger.info("DETAILED MODULE BREAKDOWN:")
        logger.info("-"*80)
        logger.info(f"{'Module':<30} {'Status':<12} {'Fetched':<10} {'Inserted':<10} {'Updated':<10} {'Total Rows':<12} {'Time (s)':<10}")
        logger.info("-"*80)
        
        for module, summary in sorted(self.sync_summary.items()):
            status_icon = {
                'success': '[OK]',
                'failed': '[ERROR]',
                'skipped': '[SKIP]'
            }.get(summary['status'], '[?]')
            
            logger.info(
                f"{module:<30} "
                f"{status_icon:<12} "
                f"{summary['records_fetched']:<10,} "
                f"{summary['rows_inserted']:<10,} "
                f"{summary['rows_updated']:<10,} "
                f"{summary['total_rows']:<12,} "
                f"{summary['time']:<10.2f}"
            )
            
            if summary['error']:
                logger.info(f"  └─ Error: {summary['error']}")
        
        logger.info("="*80)
        
        # Write detailed summary to separate file
        self._write_summary_report(total_time)
    
    def _write_summary_report(self, total_time: float):
        """Write detailed summary report to the main log file (consolidated)"""
        try:
            # Append report to the main log file
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write("\n" + "="*80 + "\n")
                f.write("ZOHO CRM TO CLICKHOUSE - INCREMENTAL SYNC REPORT\n")
                f.write("="*80 + "\n\n")
                
                f.write(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total Sync Duration: {total_time:.2f} seconds ({total_time/60:.2f} minutes)\n")
                f.write(f"Database: {self.config.CLICKHOUSE_DATABASE}\n")
                f.write(f"ClickHouse Host: {self.config.CLICKHOUSE_HOST}\n")
                f.write(f"Auto-Optimize: {self.config.AUTO_OPTIMIZE_TABLES}\n")
                f.write(f"Tables Deduplicated: {len(self.tables_to_optimize)}\n\n")
                
                # Summary statistics
                total_fetched = sum(s['records_fetched'] for s in self.sync_summary.values())
                total_inserted = sum(s['rows_inserted'] for s in self.sync_summary.values())
                total_updated = sum(s['rows_updated'] for s in self.sync_summary.values())
                success_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'success')
                failed_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'failed')
                skipped_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'skipped')
                
                f.write("SUMMARY STATISTICS\n")
                f.write("-"*80 + "\n")
                f.write(f"Total Modules Processed: {len(self.sync_summary)}\n")
                f.write(f"  ✓ Successful: {success_count}\n")
                f.write(f"  ✗ Failed: {failed_count}\n")
                f.write(f"  ⊘ Skipped: {skipped_count}\n\n")
                
                f.write(f"Total Records Fetched from Zoho: {total_fetched:,}\n")
                f.write(f"Total New Records Inserted: {total_inserted:,}\n")
                f.write(f"Total Existing Records Updated: {total_updated:,}\n")
                f.write(f"Total Database Changes: {total_inserted + total_updated:,}\n\n")
                
                # Detailed breakdown
                f.write("\n" + "="*80 + "\n")
                f.write("DETAILED MODULE BREAKDOWN\n")
                f.write("="*80 + "\n\n")
                
                for module, summary in sorted(self.sync_summary.items()):
                    table_name = f"{self.config.TABLE_PREFIX}{module.lower()}"
                    
                    f.write(f"Module: {module}\n")
                    f.write(f"Table: {table_name}\n")
                    f.write(f"Status: {summary['status'].upper()}\n")
                    f.write(f"Duration: {summary['time']:.2f} seconds\n")
                    
                    if summary['status'] == 'success':
                        f.write(f"Records Fetched: {summary['records_fetched']:,}\n")
                        f.write(f"New Records Inserted: {summary['rows_inserted']:,}\n")
                        f.write(f"Existing Records Updated: {summary['rows_updated']:,}\n")
                        f.write(f"Total Rows in Table: {summary['total_rows']:,}\n")
                    elif summary['status'] == 'failed':
                        f.write(f"Error: {summary['error']}\n")
                    elif summary['status'] == 'skipped':
                        f.write(f"Reason: {summary['error']}\n")
                    
                    f.write("\n" + "-"*80 + "\n\n")
                
                f.write("\nEND OF REPORT\n")
                f.write("="*80 + "\n")
            
            logger.info(f"\n[OK] Detailed sync report appended to log file: {log_filename}")
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to write summary report: {e}")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Zoho API to ClickHouse Incremental Sync Pipeline - Syncs only new/updated records'
    )
    parser.add_argument('--module', help='Sync specific module only (e.g., Leads)')
    parser.add_argument('--table', help='ClickHouse table name (for single module)')
    parser.add_argument('--batch-size', type=int, help='Batch size for inserts (default: 1000)')
    parser.add_argument('--lookback-hours', type=int, help='Lookback period in hours if no previous sync found (default: 24)')
    parser.add_argument('--no-optimize', action='store_true', help='Disable automatic table optimization/deduplication')
    
    args = parser.parse_args()
    
    config = Config()
    
    if args.batch_size:
        config.BATCH_SIZE = args.batch_size
    
    if args.lookback_hours:
        config.LOOKBACK_HOURS = args.lookback_hours
    
    if args.no_optimize:
        config.AUTO_OPTIMIZE_TABLES = False
    
    pipeline = IncrementalSyncPipeline(config)
    
    try:
        logger.info("="*80)
        logger.info("INCREMENTAL SYNC PIPELINE STARTED (v1.1 - With Auto-Deduplication)")
        logger.info("="*80)
        logger.info("This pipeline will:")
        logger.info("  1. Fetch only NEW or UPDATED records from Zoho CRM")
        logger.info("  2. INSERT new records into ClickHouse")
        logger.info("  3. UPDATE existing records in ClickHouse")
        logger.info("  4. DEDUPLICATE tables automatically after sync")
        logger.info("  5. Generate detailed log report after completion")
        logger.info("="*80 + "\n")
        
        if args.module:
            # Sync single module
            table_name = args.table or f"{config.TABLE_PREFIX}{args.module.lower()}"
            pipeline.run_incremental_sync_single_module(args.module, table_name)
            
            # Optimize if needed
            if config.AUTO_OPTIMIZE_TABLES:
                pipeline.optimize_tables()
            
            # Generate summary for single module
            pipeline._generate_detailed_summary(
                pipeline.sync_summary[args.module]['time']
            )
        else:
            # Sync all modules
            pipeline.run_all_modules()
        
        logger.info("\n[OK] Incremental sync completed successfully!")
        
    except Exception as e:
        logger.error(f"\n[ERROR] Pipeline execution failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()
