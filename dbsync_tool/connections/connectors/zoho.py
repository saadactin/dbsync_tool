"""
Zoho CRM API connector implementation
"""
import requests
import time
import logging
import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from connections.connectors.api_base import APIConnector
from connections.models import APIConnection
from core.exceptions import EncryptionError

logger = logging.getLogger(__name__)


class ZohoAuthenticator:
    """Handles Zoho OAuth authentication and token management"""
    
    def __init__(self, api_connection: APIConnection):
        """
        Initialize Zoho authenticator with API connection
        
        Args:
            api_connection: APIConnection model instance
        """
        self.api_connection = api_connection
        self.access_token = None
        self.token_expiry = None
        self._config = self._get_config()
    
    def _get_config(self) -> Dict:
        """Get configuration from API connection"""
        try:
            return {
                'client_id': self.api_connection.client_id,
                'client_secret': self.api_connection.get_decrypted_client_secret(),
                'refresh_token': self.api_connection.get_decrypted_refresh_token(),
                'api_domain': self.api_connection.api_domain,
                'token_url': self.api_connection.token_url,
                'request_timeout': 30,
            }
        except EncryptionError as e:
            logger.error(f"Failed to decrypt credentials: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get configuration: {e}")
            raise
    
    def get_access_token(self) -> str:
        """
        Get valid access token, refresh if needed
        
        Returns:
            str: Valid access token
            
        Raises:
            Exception: If token refresh fails
        """
        if self.access_token and self._is_token_valid():
            return self.access_token
        
        return self._refresh_access_token()
    
    def _is_token_valid(self) -> bool:
        """Check if current token is still valid"""
        if not self.token_expiry:
            return False
        return datetime.now() < self.token_expiry
    
    def _refresh_access_token(self) -> str:
        """
        Refresh access token using refresh token
        
        Returns:
            str: New access token
            
        Raises:
            Exception: If token refresh fails
        """
        logger.info("Refreshing Zoho access token...")
        
        params = {
            'refresh_token': self._config['refresh_token'],
            'client_id': self._config['client_id'],
            'client_secret': self._config['client_secret'],
            'grant_type': 'refresh_token'
        }
        
        try:
            response = requests.post(
                self._config['token_url'],
                params=params,
                timeout=self._config['request_timeout']
            )
            response.raise_for_status()
            
            data = response.json()
            self.access_token = data['access_token']
            expires_in = data.get('expires_in', 3600)
            # Set expiry 5 minutes before actual expiry for safety
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
            
            logger.info("Access token refreshed successfully")
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to refresh access token: {e}"
            logger.error(error_msg)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_msg = f"{error_msg} - {error_data}"
                except:
                    error_msg = f"{error_msg} - Response: {e.response.text[:200]}"
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error refreshing access token: {e}"
            logger.error(error_msg)
            raise Exception(error_msg)


class ZohoConnector(APIConnector):
    """
    Zoho CRM API connector implementation
    """
    
    def __init__(self, api_connection: APIConnection):
        """
        Initialize Zoho connector with API connection
        
        Args:
            api_connection: APIConnection model instance
        """
        if not isinstance(api_connection, APIConnection):
            raise ValueError("api_connection must be an APIConnection instance")
        
        if api_connection.api_type != 'zoho_crm':
            raise ValueError(f"Unsupported API type: {api_connection.api_type}")
        
        self.api_connection = api_connection
        self.authenticator = ZohoAuthenticator(api_connection)
        self.max_retries = 3
        self.request_timeout = 30
        self.rate_limit_delay = 0.5  # 0.5 seconds between requests
    
    def authenticate(self) -> bool:
        """
        Authenticate with Zoho API
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            token = self.authenticator.get_access_token()
            return bool(token)
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def get_available_modules(self) -> List[str]:
        """
        Get list of available modules from Zoho CRM
        
        Returns:
            List[str]: List of available module names
            
        Raises:
            Exception: If module discovery fails
        """
        url = f"{self.api_connection.api_domain}/crm/v2/settings/modules"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
        try:
            response = requests.get(
                url, 
                headers=headers, 
                timeout=self.request_timeout
            )
            response.raise_for_status()
            
            data = response.json()
            modules = [module['api_name'] for module in data.get('modules', [])]
            logger.info(f"Found {len(modules)} available modules in Zoho CRM")
            return modules
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to fetch modules: {e}"
            logger.error(error_msg)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_msg = f"{error_msg} - {error_data}"
                except:
                    error_msg = f"{error_msg} - Response: {e.response.text[:200]}"
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error fetching modules: {e}"
            logger.error(error_msg)
            raise Exception(error_msg)
    
    def fetch_records(
        self, 
        module: str, 
        params: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Fetch all records from a module with pagination (full sync)
        
        Args:
            module: Module name to fetch records from
            params: Optional parameters for filtering, pagination, etc.
            
        Returns:
            List[Dict]: List of all record dictionaries
            
        Raises:
            Exception: If record fetching fails
        """
        all_records = []
        page = 1
        per_page = 200
        
        if params is None:
            params = {}
        
        while True:
            fetch_params = params.copy()
            fetch_params.update({
                'page': page,
                'per_page': per_page
            })
            
            records, has_more = self._fetch_page(module, fetch_params)
            
            if not records:
                break
            
            all_records.extend(records)
            logger.info(f"Page {page}: Fetched {len(records)} records (Total: {len(all_records)})")
            
            if not has_more:
                break
            
            page += 1
            time.sleep(self.rate_limit_delay)  # Rate limiting
        
        logger.info(f"Total records fetched from {module}: {len(all_records)}")
        return all_records
    
    def fetch_incremental_records(
        self, 
        module: str, 
        since: datetime
    ) -> List[Dict]:
        """
        Fetch records modified since a specific timestamp (incremental sync)
        
        Args:
            module: Module name to fetch records from
            since: Datetime object representing the earliest modification time
            
        Returns:
            List[Dict]: List of record dictionaries modified since 'since' timestamp
            
        Raises:
            Exception: If incremental record fetching fails
        """
        all_records = []
        page = 1
        per_page = 200
        max_modified_time = since
        
        # Format time for Zoho API (ISO 8601 with timezone)
        # Zoho expects timezone offset, defaulting to +05:30 (India) if not specified
        since_str = since.strftime('%Y-%m-%dT%H:%M:%S') + '+05:30'
        
        logger.info(f"Fetching records from {module} modified since: {since_str}")
        
        while True:
            params = {
                'page': page,
                'per_page': per_page,
                'sort_by': 'Modified_Time',
                'sort_order': 'asc',
            }
            
            # Try to use search API with Modified_Time criteria
            records, has_more = self._fetch_modified_page(module, since_str, params)
            
            if not records:
                break
            
            # Track the latest modified time
            for record in records:
                if 'Modified_Time' in record:
                    try:
                        record_time = pd.to_datetime(record['Modified_Time'])
                        if pd.notna(record_time) and record_time > max_modified_time:
                            max_modified_time = record_time.to_pydatetime()
                    except:
                        pass
            
            all_records.extend(records)
            logger.info(f"Page {page}: Fetched {len(records)} modified records (Total: {len(all_records)})")
            
            if not has_more:
                break
            
            page += 1
            time.sleep(self.rate_limit_delay)  # Rate limiting
        
        logger.info(f"Total modified records fetched from {module}: {len(all_records)}")
        return all_records
    
    def _fetch_page(self, module: str, params: Dict) -> Tuple[List[Dict], bool]:
        """
        Fetch a single page of data
        
        Args:
            module: Module name
            params: Query parameters
            
        Returns:
            Tuple[List[Dict], bool]: (records, has_more)
        """
        url = f"{self.api_connection.api_domain}/crm/v2/{module}"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.request_timeout
                )
                
                if response.status_code == 204:  # No content
                    return [], False
                
                response.raise_for_status()
                
                data = response.json()
                records = data.get('data', [])
                has_more = data.get('info', {}).get('more_records', False)
                
                return records, has_more
                
            except requests.exceptions.RequestException as e:
                if hasattr(e, 'response') and e.response is not None:
                    if e.response.status_code == 404:  # Module not found
                        logger.warning(f"Module {module} not accessible (404)")
                        return [], False
                
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    error_msg = f"Failed to fetch page after {self.max_retries} attempts: {e}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
        
        return [], False
    
    def _fetch_modified_page(
        self, 
        module: str, 
        since_time: str, 
        params: Dict
    ) -> Tuple[List[Dict], bool]:
        """
        Fetch a single page of modified data using search API
        
        Args:
            module: Module name
            since_time: ISO formatted time string
            params: Query parameters
            
        Returns:
            Tuple[List[Dict], bool]: (records, has_more)
        """
        # Try search API first
        url = f"{self.api_connection.api_domain}/crm/v2/{module}/search"
        headers = {
            'Authorization': f'Zoho-oauthtoken {self.authenticator.get_access_token()}'
        }
        
        # Add search criteria for modified time
        search_params = params.copy()
        search_params['criteria'] = f"(Modified_Time:greater_equal:{since_time})"
        
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=search_params,
                    timeout=self.request_timeout
                )
                
                if response.status_code == 204:  # No content
                    return [], False
                
                if response.status_code == 400:
                    # Search might not be supported, fall back to regular fetch and filter
                    logger.info(f"Search API not available for {module}, fetching all records and filtering")
                    return self._fetch_all_and_filter(module, since_time, params)
                
                response.raise_for_status()
                
                data = response.json()
                records = data.get('data', [])
                has_more = data.get('info', {}).get('more_records', False)
                
                return records, has_more
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    # Fall back to fetching all records and filtering
                    logger.info(f"Search API failed, falling back to fetch all and filter")
                    return self._fetch_all_and_filter(module, since_time, params)
        
        return [], False
    
    def _fetch_all_and_filter(
        self, 
        module: str, 
        since_time: str, 
        params: Dict
    ) -> Tuple[List[Dict], bool]:
        """
        Fallback: fetch all records and filter by modified time
        
        Args:
            module: Module name
            since_time: ISO formatted time string
            params: Query parameters
            
        Returns:
            Tuple[List[Dict], bool]: (filtered_records, has_more)
        """
        url = f"{self.api_connection.api_domain}/crm/v2/{module}"
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
                timeout=self.request_timeout
            )
            
            if response.status_code == 204:
                return [], False
            
            response.raise_for_status()
            
            data = response.json()
            all_records = data.get('data', [])
            has_more = data.get('info', {}).get('more_records', False)
            
            # Filter by modified time
            try:
                since_dt = pd.to_datetime(since_time)
                if pd.isna(since_dt):
                    # If parsing fails, return all records
                    logger.warning(f"Could not parse since_time {since_time}, returning all records")
                    return all_records, has_more
                since_dt = since_dt.to_pydatetime()
            except:
                # If parsing fails, return all records
                logger.warning(f"Could not parse since_time {since_time}, returning all records")
                return all_records, has_more
            
            filtered_records = []
            for record in all_records:
                if 'Modified_Time' in record:
                    try:
                        record_time = pd.to_datetime(record['Modified_Time'])
                        if pd.notna(record_time):
                            record_time = record_time.to_pydatetime()
                            if record_time >= since_dt:
                                filtered_records.append(record)
                        else:
                            # Include if we can't parse time
                            filtered_records.append(record)
                    except:
                        # Include if we can't parse time
                        filtered_records.append(record)
                else:
                    # Include if no Modified_Time field
                    filtered_records.append(record)
            
            return filtered_records, has_more
            
        except Exception as e:
            logger.error(f"Error fetching and filtering records: {e}")
            return [], False
