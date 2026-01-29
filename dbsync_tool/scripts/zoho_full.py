"""
Zoho API to ClickHouse Data Pipeline - Multi-Module Version
Author: Auto-generated
Description: Extract data from ALL Zoho modules, flatten JSON, and store in ClickHouse
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
from typing import Dict, List, Any, Optional

# Fix Unicode encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Configure logging with UTF-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('zoho_to_clickhouse.log', encoding='utf-8'),
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
    CLICKHOUSE_DATABASE = "JARVIS_DB_BP"
    
    # API Settings
    ZOHO_TOKEN_URL = "https://accounts.zoho.in/oauth/v2/token"
    BATCH_SIZE = 1000  # Number of records per batch insert
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 30
    
    # Zoho CRM Modules to sync - UPDATED WITH YOUR COMPLETE LIST
    # Note: Using correct API names. Some display names map to different API names:
    # - "Companies" (display) → "Accounts" (API)
    # - "Dealers" (display) → "Vendors" (API)
    # - "Events" (display) → "Activities" (API)
    MODULES_TO_SYNC = [
        "Leads",
        "Contacts",
        "Companies",  # Display name, API name is "Accounts"
        "Deals",
        "Dealers",  # Display name, API name is "Vendors"
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
        "Projects",  # May not exist - will create empty table if not found
        "BANTs_X_Leads2",
        "Purchase_Orders",  # May not exist - will create empty table if not found
        "BANT_Owner_2_History",
        "Cases",
        "Activities",  # Replaced "Events" - this is the correct module name in your CRM
        "Price_Books",
        "Solutions"
    ]
    
    # Mapping from display names to API names
    MODULE_NAME_MAPPING = {
        "Companies": "Accounts",  # Display name → API name
        "Dealers": "Vendors",    # Display name → API name
        "Events": "Activities",   # Display name → API name (already updated in list)
        # All other modules use the same name for display and API
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


class ZohoDataExtractor:
    """Extracts data from Zoho API"""
    
    def __init__(self, authenticator: ZohoAuthenticator, config: Config):
        self.authenticator = authenticator
        self.config = config
    
    def get_available_modules(self) -> List[str]:
        """Get list of available modules from Zoho CRM"""
        url = f"{self.config.ZOHO_API_DOMAIN}/crm/v2/settings/modules"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=self.config.REQUEST_TIMEOUT)
            response.raise_for_status()
            
            data = response.json()
            modules = [module['api_name'] for module in data.get('modules', [])]
            logger.info(f"[OK] Found {len(modules)} available modules in Zoho CRM")
            return modules
            
        except Exception as e:
            logger.warning(f"Could not fetch module list: {e}. Using default list.")
            return self.config.MODULES_TO_SYNC
    
    def check_module_access(self, module: str) -> bool:
        """Check if we have access to a specific module with detailed error reporting"""
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
            
            # 200 = Success, 204 = No content but accessible
            if response.status_code in [200, 204]:
                return True
            else:
                # Log detailed error information
                try:
                    error_data = response.json()
                    error_code = error_data.get('code', 'N/A')
                    error_message = error_data.get('message', 'N/A')
                    logger.warning(
                        f"Module {module} access denied - "
                        f"Status: {response.status_code}, "
                        f"Code: {error_code}, "
                        f"Message: {error_message}"
                    )
                except:
                    logger.warning(
                        f"Module {module} access denied - "
                        f"Status: {response.status_code}, "
                        f"Response: {response.text[:200]}"
                    )
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error checking module {module} access: {e}")
            return False
    
    def fetch_all_records(self, module: str, params: Optional[Dict] = None) -> List[Dict]:
        """Fetch all records from a module with pagination"""
        all_records = []
        page = 1
        per_page = 200
        
        if params is None:
            params = {}
        
        while True:
            params.update({
                'page': page,
                'per_page': per_page
            })
            
            records, has_more = self._fetch_page(module, params)
            
            if not records:
                break
                
            all_records.extend(records)
            logger.info(f"  Page {page}: +{len(records)} records (Total: {len(all_records)})")
            
            if not has_more:
                break
            
            page += 1
            time.sleep(0.5)  # Rate limiting
        
        return all_records
    
    def _fetch_page(self, module: str, params: Dict) -> tuple:
        """Fetch a single page of data"""
        url = f"{self.config.ZOHO_API_DOMAIN}/crm/v2/{module}"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
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
                    
                response.raise_for_status()
                
                data = response.json()
                records = data.get('data', [])
                has_more = data.get('info', {}).get('more_records', False)
                
                return records, has_more
                
            except requests.exceptions.RequestException as e:
                if response.status_code == 404:  # Module not found
                    logger.warning(f"Module {module} not accessible")
                    return [], False
                    
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < self.config.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                else:
                    return [], False
        
        return [], False


class DataTransformer:
    """Transforms and flattens JSON data"""
    
    @staticmethod
    def flatten_json(data: List[Dict]) -> pd.DataFrame:
        """Flatten nested JSON to pandas DataFrame"""
        if not data:
            return pd.DataFrame()
        
        # Use pandas json_normalize for flattening
        df = pd.json_normalize(data, sep='_')
        
        # Convert complex objects to JSON strings
        for col in df.columns:
            if df[col].dtype == 'object':
                try:
                    # Check if column contains dict or list
                    if any(isinstance(x, (dict, list)) for x in df[col].dropna()):
                        df[col] = df[col].apply(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)
                except:
                    pass
        
        # Clean column names for ClickHouse
        df.columns = [DataTransformer._clean_column_name(col) for col in df.columns]
        
        # Add ingestion timestamp
        df['_ingestion_timestamp'] = datetime.now()
        
        return df
    
    @staticmethod
    def prepare_for_clickhouse(df: pd.DataFrame) -> pd.DataFrame:
        """Prepare DataFrame for ClickHouse insertion"""
        df = df.copy()
        
        # Replace NaN and None with appropriate defaults
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
        
        # Convert any remaining problematic types
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
    
    def create_table_from_dataframe(self, table_name: str, df: pd.DataFrame, replace: bool = False):
        """Create table based on DataFrame schema"""
        if self.table_exists(table_name):
            if replace:
                logger.info(f"Dropping existing table {table_name}")
                self.client.command(f"DROP TABLE {self.config.CLICKHOUSE_DATABASE}.{table_name}")
            else:
                logger.info(f"Table {table_name} already exists")
                return
        
        columns = []
        for col, dtype in df.dtypes.items():
            ch_type = self._map_dtype_to_clickhouse(dtype)
            columns.append(f"`{col}` {ch_type}")
        
        columns_str = ',\n    '.join(columns)
        
        # Determine primary key
        primary_key = 'id' if 'id' in df.columns else df.columns[0]
        
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
            logger.info(f"[OK] Table {table_name} created successfully")
        except Exception as e:
            logger.error(f"[ERROR] Failed to create table: {e}")
            raise
    
    def create_empty_table(self, table_name: str):
        """Create an empty table with basic schema when module is not available or has no data"""
        if self.table_exists(table_name):
            logger.info(f"Table {table_name} already exists")
            return
        
        # Create table with basic schema (id and ingestion timestamp)
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {self.config.CLICKHOUSE_DATABASE}.{table_name}
        (
            `id` String,
            `_ingestion_timestamp` DateTime DEFAULT now()
        )
        ENGINE = ReplacingMergeTree(_ingestion_timestamp)
        ORDER BY (id)
        """
        
        try:
            self.client.command(create_query)
            logger.info(f"[OK] Empty table {table_name} created successfully (no data available)")
        except Exception as e:
            logger.error(f"[ERROR] Failed to create empty table: {e}")
            raise
    
    def table_exists(self, table_name: str) -> bool:
        """Check if table exists"""
        query = f"EXISTS TABLE {self.config.CLICKHOUSE_DATABASE}.{table_name}"
        result = self.client.command(query)
        return result == 1
    
    def get_row_count(self, table_name: str) -> int:
        """Get current row count in table"""
        try:
            query = f"SELECT count() FROM {self.config.CLICKHOUSE_DATABASE}.{table_name}"
            result = self.client.command(query)
            return result
        except:
            return 0
    
    def insert_dataframe_batch(self, table_name: str, df: pd.DataFrame, batch_num: int, total_batches: int):
        """Insert DataFrame into ClickHouse table with progress logging"""
        if df.empty:
            return
        
        try:
            start_time = time.time()
            self.client.insert_df(table_name, df)
            elapsed = time.time() - start_time
            
            total_count = self.get_row_count(table_name)
            logger.info(f"  Batch {batch_num}/{total_batches}: +{len(df)} rows in {elapsed:.2f}s (Total: {total_count})")
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to insert batch {batch_num}: {e}")
            raise
    
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


class ZohoToClickHousePipeline:
    """Main pipeline orchestrator"""
    
    def __init__(self, config: Config):
        self.config = config
        self.authenticator = ZohoAuthenticator(config)
        self.extractor = ZohoDataExtractor(self.authenticator, config)
        self.transformer = DataTransformer()
        self.db_handler = ClickHouseHandler(config)
        self.sync_summary = {}
    
    def run_single_module(self, module: str, table_name: str):
        """Run pipeline for a single module"""
        logger.info(f"\n{'='*80}")
        logger.info(f"MODULE: {module}")
        logger.info(f"TABLE: {table_name}")
        logger.info(f"{'='*80}")
        
        start_time = time.time()
        
        # Map display name to API name if needed
        api_module_name = self.config.MODULE_NAME_MAPPING.get(module, module)
        if api_module_name != module:
            logger.info(f"Using API name: {api_module_name} (display name: {module})")
        
        try:
            # Check access using API name
            if not self.extractor.check_module_access(api_module_name):
                logger.warning(f"[INFO] Module {module} (API: {api_module_name}) not accessible or not found")
                logger.info(f"Creating empty table for {table_name}...")
                self.db_handler.create_empty_table(table_name)
                elapsed = time.time() - start_time
                self.sync_summary[module] = {
                    'status': 'empty_table',
                    'records': 0,
                    'reason': 'module_not_available',
                    'time': elapsed
                }
                logger.info(f"[OK] Empty table created for {module} in {elapsed:.2f}s")
                return
            
            # Extract data using API name
            logger.info(f"[1/4] Extracting {module} (API: {api_module_name})...")
            raw_data = self.extractor.fetch_all_records(api_module_name)
            
            if not raw_data:
                logger.warning(f"[INFO] No data found in {module} (API: {api_module_name})")
                logger.info(f"Creating empty table for {table_name}...")
                self.db_handler.create_empty_table(table_name)
                elapsed = time.time() - start_time
                self.sync_summary[module] = {
                    'status': 'empty_table',
                    'records': 0,
                    'reason': 'no_data',
                    'time': elapsed
                }
                logger.info(f"[OK] Empty table created for {module} in {elapsed:.2f}s")
                return
            
            logger.info(f"[OK] Extracted {len(raw_data)} records from {module}")
            
            # Transform data
            logger.info(f"[2/4] Transforming {module}...")
            df = self.transformer.flatten_json(raw_data)
            df = self.transformer.prepare_for_clickhouse(df)
            logger.info(f"[OK] Prepared {len(df)} rows x {len(df.columns)} columns")
            
            # Create table
            logger.info(f"[3/4] Creating table {table_name}...")
            self.db_handler.create_table_from_dataframe(table_name, df)
            
            # Insert in batches
            logger.info(f"[4/4] Inserting into {table_name}...")
            total_rows = len(df)
            batch_size = self.config.BATCH_SIZE
            total_batches = (total_rows + batch_size - 1) // batch_size
            
            for i in range(0, total_rows, batch_size):
                batch_num = (i // batch_size) + 1
                batch_df = df.iloc[i:i + batch_size]
                
                self.db_handler.insert_dataframe_batch(
                    table_name, 
                    batch_df, 
                    batch_num, 
                    total_batches
                )
                
                if batch_num < total_batches:
                    time.sleep(0.1)
            
            elapsed = time.time() - start_time
            final_count = self.db_handler.get_row_count(table_name)
            
            logger.info(f"[OK] {module} completed in {elapsed:.2f}s - {final_count} rows in {table_name}")
            
            self.sync_summary[module] = {
                'status': 'success',
                'records': final_count,
                'columns': len(df.columns),
                'time': elapsed
            }
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to sync {module}: {e}")
            # Try to create empty table even on error
            try:
                logger.info(f"Attempting to create empty table for {table_name}...")
                self.db_handler.create_empty_table(table_name)
                self.sync_summary[module] = {
                    'status': 'empty_table',
                    'records': 0,
                    'reason': f'error_creating_empty_table: {str(e)}',
                    'time': time.time() - start_time
                }
            except:
                self.sync_summary[module] = {'status': 'failed', 'error': str(e)}
    
    def run_all_modules(self, modules: List[str] = None):
        """Run pipeline for all specified modules"""
        if modules is None:
            modules = self.config.MODULES_TO_SYNC
        
        logger.info("\n" + "="*80)
        logger.info("ZOHO CRM -> CLICKHOUSE MULTI-MODULE SYNC")
        logger.info("="*80)
        logger.info(f"Modules to sync: {len(modules)}")
        logger.info(f"Batch size: {self.config.BATCH_SIZE}")
        logger.info(f"Target database: {self.config.CLICKHOUSE_DATABASE}")
        logger.info("="*80)
        
        for idx, module in enumerate(modules, 1):
            table_name = f"{self.config.TABLE_PREFIX}{module.lower()}"
            logger.info(f"\n[{idx}/{len(modules)}] Processing {module}...")
            
            self.run_single_module(module, table_name)
        
        # Print summary
        self._print_summary()
    
    def _print_summary(self):
        """Print sync summary"""
        logger.info("\n" + "="*80)
        logger.info("SYNC SUMMARY")
        logger.info("="*80)
        
        success_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'success')
        failed_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'failed')
        skipped_count = sum(1 for s in self.sync_summary.values() if s['status'] == 'skipped')
        total_records = sum(s.get('records', 0) for s in self.sync_summary.values() if s['status'] == 'success')
        
        logger.info(f"[OK] Successful: {success_count}")
        logger.info(f"[ERROR] Failed: {failed_count}")
        logger.info(f"[SKIP] Skipped: {skipped_count}")
        logger.info(f"Total records synced: {total_records:,}")
        logger.info("-" * 80)
        
        for module, summary in self.sync_summary.items():
            if summary['status'] == 'success':
                logger.info(f"[OK] {module:25} -> {summary['records']:,} records in {summary['time']:.1f}s")
            elif summary['status'] == 'empty_table':
                logger.info(f"[EMPTY] {module:25} -> Empty table created (0 records) - {summary.get('reason', 'no_data')}")
            elif summary['status'] == 'failed':
                logger.info(f"[ERROR] {module:25} -> Error: {summary.get('error', 'Unknown')}")
            else:
                logger.info(f"[SKIP] {module:25} -> {summary.get('reason', 'skipped')}")
        
        logger.info("="*80)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Zoho API to ClickHouse Multi-Module Pipeline')
    parser.add_argument('--module', help='Sync specific module only (e.g., Leads)')
    parser.add_argument('--table', help='ClickHouse table name (for single module)')
    parser.add_argument('--batch-size', type=int, help='Batch size for inserts (default: 1000)')
    parser.add_argument('--all', action='store_true', help='Sync all available modules')
    parser.add_argument('--list-modules', action='store_true', help='List available modules and exit')
    
    args = parser.parse_args()
    
    config = Config()
    
    if args.batch_size:
        config.BATCH_SIZE = args.batch_size
    
    pipeline = ZohoToClickHousePipeline(config)
    
    try:
        if args.list_modules:
            # List available modules
            modules = pipeline.extractor.get_available_modules()
            print("\nAvailable Zoho CRM Modules:")
            print("-" * 40)
            for module in sorted(modules):
                print(f"  - {module}")
            print()
            return
        
        if args.module:
            # Sync single module
            table_name = args.table or f"{config.TABLE_PREFIX}{args.module.lower()}"
            pipeline.run_single_module(args.module, table_name)
        else:
            # Sync all modules
            pipeline.run_all_modules()
            
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()