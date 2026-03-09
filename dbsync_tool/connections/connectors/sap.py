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
        Fetches available entity sets from $metadata and returns only curated endpoints
        that exist on this server; if $metadata fails, returns full SAP_DOCUMENT_TYPES.
        """
        server_entity_sets = self._fetch_entity_sets_from_metadata()
        if server_entity_sets is not None:
            server_set = set(server_entity_sets)
            filtered = [e for e in SAP_DOCUMENT_TYPES if e["endpoint"] in server_set]
            if filtered:
                return filtered
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
