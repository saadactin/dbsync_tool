"""
SAP Business One Service Layer API connector implementation.
Uses session-based authentication (POST /Login) and OData-style pagination ($top, $skip).
Includes retry with exponential backoff for transient errors (5xx, timeout).
Can discover available entity sets from $metadata and merge with curated list.
"""
import logging
import time
import xml.etree.ElementTree as ET
import requests
from typing import List, Dict, Optional, Any
from datetime import datetime

from connections.connectors.api_base import APIConnector
from connections.models import APIConnection
from core.constants import SAP_DOCUMENT_TYPES
from core.exceptions import EncryptionError

logger = logging.getLogger(__name__)

DEFAULT_TOP = 1000
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2


def _is_retryable_status(code: int) -> bool:
    """Return True for 5xx and 429 (rate limit)."""
    return code >= 500 or code == 429


def _request_with_retry(
    method: str,
    url: str,
    session: requests.Session,
    timeout: int = REQUEST_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    """
    Perform request with retry on transient errors (5xx, timeout, connection error).
    Uses exponential backoff; logs retries. Uses session.get/post so tests can mock them.
    """
    last_exc = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            if method.upper() == "POST":
                resp = session.post(url, timeout=timeout, **kwargs)
            else:
                resp = session.get(url, timeout=timeout, **kwargs)
            if resp.ok or not _is_retryable_status(resp.status_code):
                return resp
            last_exc = Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.exceptions.RequestException as e:
            last_exc = e
        if attempt < RETRY_ATTEMPTS - 1:
            delay = RETRY_BACKOFF_BASE ** attempt
            logger.warning(
                "SAP request failed (attempt %d/%d), retrying in %ds: %s",
                attempt + 1,
                RETRY_ATTEMPTS,
                delay,
                last_exc,
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc
    return resp


class SAPConnector(APIConnector):
    """
    SAP Business One Service Layer connector.
    Authenticates via POST /Login and uses session cookies for subsequent requests.
    """

    def __init__(self, api_connection: APIConnection):
        if not isinstance(api_connection, APIConnection):
            raise ValueError("api_connection must be an APIConnection instance")
        if api_connection.api_type != "sap_b1":
            raise ValueError(f"Unsupported API type: {api_connection.api_type}")
        self.api_connection = api_connection
        self.session = requests.Session()
        self._base_url: Optional[str] = None
        self._authenticated = False

    def _get_base_url(self) -> str:
        """Normalize and return base URL (no trailing slash)."""
        if self._base_url is not None:
            return self._base_url
        url = (self.api_connection.sap_base_url or "").strip().rstrip("/")
        if not url:
            raise ValueError("SAP base URL is not set")
        self._base_url = url
        return self._base_url

    def _get_credentials(self) -> Dict:
        """Get login payload from connection (raises EncryptionError on decryption failure)."""
        try:
            params = self.api_connection.get_sap_connection_params()
        except EncryptionError as e:
            logger.error("Failed to get SAP credentials: %s", e)
            raise
        base_url = params.get("base_url", "").strip().rstrip("/")
        if not base_url:
            raise ValueError("SAP base URL is not set")
        self._base_url = base_url
        username = params.get("username") or {}
        password = params.get("password") or ""
        if not isinstance(username, dict) or "UserName" not in username or "CompanyDB" not in username:
            raise ValueError("SAP username must contain UserName and CompanyDB")
        return {
            "CompanyDB": username.get("CompanyDB", ""),
            "UserName": username.get("UserName", ""),
            "Password": password,
        }

    def authenticate(self) -> bool:
        """
        Log in to SAP B1 Service Layer. On success, session holds cookies for later requests.
        """
        try:
            creds = self._get_credentials()
        except (EncryptionError, ValueError) as e:
            logger.error("SAP auth config error: %s", e)
            return False
        login_url = f"{self._get_base_url()}/Login"
        try:
            response = _request_with_retry(
                "POST",
                login_url,
                self.session,
                timeout=REQUEST_TIMEOUT,
                json=creds,
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.RequestException as e:
            logger.error("SAP login request failed: %s", e)
            return False
        if not response.ok:
            try:
                body = response.json()
                msg = body.get("error", {}).get("message", {}).get("value") or response.text[:200]
            except Exception:
                msg = response.text[:200]
            logger.error("SAP login failed (%s): %s", response.status_code, msg)
            return False
        self._authenticated = True
        logger.info("SAP login successful")
        return True

    def _ensure_authenticated(self) -> None:
        if not self._authenticated and not self.authenticate():
            raise Exception("SAP authentication failed")

    def _fetch_entity_sets_from_metadata(self) -> Optional[List[str]]:
        """
        Fetch available entity set names from SAP B1 Service Layer $metadata (OData EDMX).
        Returns list of entity set names, or None if request/parse fails (caller can fall back to static list).
        """
        self._ensure_authenticated()
        base_url = self._get_base_url()
        url = f"{base_url}/$metadata"
        try:
            resp = _request_with_retry(
                "GET",
                url,
                self.session,
                timeout=REQUEST_TIMEOUT,
                headers={"Accept": "application/xml"},
            )
        except requests.exceptions.RequestException as e:
            logger.warning("SAP $metadata request failed: %s", e)
            return None
        if not resp.ok:
            logger.warning("SAP $metadata returned %s", resp.status_code)
            return None
        try:
            raw = resp.text if isinstance(resp.text, str) else (resp.content or b"").decode("utf-8", errors="replace")
            root = ET.fromstring(raw)
        except (ET.ParseError, TypeError, ValueError) as e:
            logger.warning("SAP $metadata parse error: %s", e)
            return None
        # EDMX: {http://schemas.microsoft.com/ado/2007/06/edmx}Edmx -> DataServices -> Schema -> EntityContainer -> EntitySet
        names: List[str] = []
        for elem in root.iter():
            if elem.tag.endswith("EntitySet") and elem.get("Name"):
                names.append(elem.get("Name"))
        if not names:
            logger.warning("SAP $metadata contained no EntitySet elements")
            return None
        logger.info("SAP $metadata: found %d entity sets", len(names))
        return names

    def get_available_endpoints(self) -> List[Dict[str, str]]:
        """
        Return list of endpoint dicts (name, endpoint, id_field) for the UI.
        We return the full SAP_DOCUMENT_TYPES list now to allow all requested tables
        to be visible, as some SAP servers have unreliable $metadata or custom names.
        Sync-time retry/skip logic handles any missing endpoints.
        """
        return list(SAP_DOCUMENT_TYPES)

    def get_available_modules(self) -> List[str]:
        """
        Return list of SAP endpoint names (e.g. JournalEntries, Items).
        Uses get_available_endpoints() so server $metadata is used when possible.
        """
        return [e["endpoint"] for e in self.get_available_endpoints()]

    def fetch_records(
        self,
        module: str,
        params: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Fetch all records from an SAP endpoint using OData-style $top and $skip.
        """
        self._ensure_authenticated()
        params = params or {}
        top = params.get("$top", DEFAULT_TOP)
        base_url = self._get_base_url()
        url = f"{base_url}/{module}"
        all_records: List[Dict] = []
        skip = 0
        while True:
            try:
                resp = _request_with_retry(
                    "GET",
                    url,
                    self.session,
                    timeout=REQUEST_TIMEOUT,
                    params={"$top": top, "$skip": skip},
                )
            except requests.exceptions.RequestException as e:
                logger.error("SAP fetch_records request failed: %s", e)
                raise
            if resp.status_code == 401:
                self._authenticated = False
                self._ensure_authenticated()
                continue
            if not resp.ok:
                try:
                    err = resp.json()
                    msg = err.get("error", {}).get("message", {}).get("value") or resp.text[:200]
                except Exception:
                    msg = resp.text[:200]
                raise Exception(f"SAP fetch failed ({resp.status_code}): {msg}")
            try:
                data = resp.json()
            except Exception as e:
                raise Exception(f"Invalid JSON from SAP: {e}")
            value = data.get("value")
            if not value or not isinstance(value, list):
                break
            all_records.extend(value)
            logger.info("SAP %s: fetched %d (skip=%d, total=%d)", module, len(value), skip, len(all_records))
            if len(value) < top:
                break
            skip += top
        logger.info("SAP %s total records: %d", module, len(all_records))
        return all_records

    def fetch_incremental_records(
        self,
        module: str,
        since: datetime,
    ) -> List[Dict]:
        """
        SAP B1 does not expose a global Modified_Time filter; return full fetch.
        Day 4 sync layer will use hash-based change detection.
        """
        return self.fetch_records(module, {})

    def logout(self) -> None:
        """Clear session via Logout endpoint and close session."""
        if not self._base_url:
            return
        try:
            self.session.post(
                f"{self._base_url}/Logout",
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as e:
            logger.warning("SAP logout request failed: %s", e)
        finally:
            self.session.close()
            self._authenticated = False


import asyncio
import aiohttp

class AsyncSAPConnector:
    """
    High-performance asynchronous SAP B1 Service Layer connector.
    Supports parallel page fetching using aiohttp and semaphores.
    """
    def __init__(self, api_connection: APIConnection):
        self.api_connection = api_connection
        self.session = None
        self.connector = None
        self._semaphore = None
        self._base_url = None
        self._authenticated = False
        self._filter_unsupported_endpoints = set()

    def _get_base_url(self) -> str:
        if self._base_url is not None:
            return self._base_url
        url = (self.api_connection.sap_base_url or "").strip().rstrip("/")
        if not url:
            raise ValueError("SAP base URL is not set")
        self._base_url = url
        return self._base_url

    async def login(self) -> bool:
        """Async login to SAP B1."""
        try:
            from asgiref.sync import sync_to_async
            params = await sync_to_async(self.api_connection.get_sap_connection_params)()
            username = params.get("username") or {}
            password = params.get("password") or ""
            
            # Connection settings from user template
            connection_limit = 30
            max_concurrent = 25
            
            self.connector = aiohttp.TCPConnector(limit=connection_limit, ssl=False)
            self.session = aiohttp.ClientSession(
                connector=self.connector, 
                timeout=aiohttp.ClientTimeout(total=300)
            )
            self._semaphore = asyncio.Semaphore(max_concurrent)
            
            login_url = f"{self._get_base_url()}/Login"
            payload = {**username, "Password": password}
            
            async with self.session.post(login_url, json=payload, ssl=False) as resp:
                if resp.status == 200:
                    self._authenticated = True
                    logger.info("Async SAP login successful")
                    return True
                else:
                    logger.error(f"Async SAP login failed: {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"Async SAP login exception: {e}")
            return False

    async def logout(self):
        try:
            if self.session and self._authenticated:
                await self.session.post(f"{self._get_base_url()}/Logout", ssl=False)
        except: pass
        if self.session: await self.session.close()
        if self.connector: await self.connector.close()
        self._authenticated = False

    async def fetch_page(self, endpoint: str, skip: int, page_size: int = 500, filter_query: str = None) -> List[Dict]:
        """Fetch a single page of records."""
        async with self._semaphore:
            try:
                params = {"$top": page_size, "$skip": skip}
                if filter_query: 
                    params["$filter"] = filter_query
                
                headers = {"Prefer": f"odata.maxpagesize={page_size}"}
                url = f"{self._get_base_url()}/{endpoint}"
                
                async with self.session.get(url, params=params, headers=headers, ssl=False) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("value", [])
                    elif response.status == 400 and filter_query:
                        # Log once per endpoint; caller will transparently
                        # fallback to unfiltered reads.
                        if endpoint not in self._filter_unsupported_endpoints:
                            logger.warning(
                                "Filter failed for %s (HTTP 400). Falling back to unfiltered fetch.",
                                endpoint,
                            )
                            self._filter_unsupported_endpoints.add(endpoint)
                        return None
                    return []
            except Exception as e:
                logger.error(f"Async Fetch error at skip={skip}: {e}")
                return []

    async def fetch_pages_parallel(self, endpoint: str, start_skip: int, num_pages: int, page_size: int = 500, filter_query: str = None) -> List[Dict]:
        """Fetch multiple pages in parallel."""
        tasks = [
            self.fetch_page(endpoint, start_skip + (i * page_size), page_size, filter_query) 
            for i in range(num_pages)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        all_records = []
        for result in results:
            if result is None: return None
            if isinstance(result, list): 
                all_records.extend(result)
        return all_records

    async def stream_all_records(self, endpoint: str, page_size: int = 500, parallel_workers: int = 10, batch_size: int = 5000, filter_query: str = None):
        """Generator that yields batches of records fetched in parallel."""
        skip, total_fetched, buffer, empty_batches = 0, 0, [], 0
        prefetched_records = None

        # Probe filtered mode once to avoid repeated HTTP 400 spam from
        # parallel page workers for endpoints that don't support $filter.
        if filter_query:
            prefetched_records = await self.fetch_page(endpoint, 0, page_size, filter_query)
            if prefetched_records is None:
                filter_query = None

        while empty_batches < 3:
            if prefetched_records is not None:
                records = prefetched_records
                prefetched_records = None
            else:
                records = await self.fetch_pages_parallel(
                    endpoint, skip, parallel_workers, page_size, filter_query
                )
            if records is None: break
            if not records:
                empty_batches += 1
                skip += parallel_workers * page_size
                continue
            empty_batches = 0
            total_fetched += len(records)
            buffer.extend(records)
            
            if len(buffer) >= batch_size:
                yield buffer[:batch_size]
                buffer = buffer[batch_size:]
            
            skip += len(records)
            await asyncio.sleep(0.1)
        
        if buffer: 
            yield buffer
        logger.info(f"Async stream complete for {endpoint}. Total: {total_fetched}")
