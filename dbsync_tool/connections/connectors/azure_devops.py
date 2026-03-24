"""
Azure DevOps REST API connector.
Uses Azure AD Service Principal (client credentials) for authentication and
fetches projects from the Azure DevOps organization.
"""
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

import requests
import msal

from connections.connectors.api_base import APIConnector
from connections.models import APIConnection
from core.exceptions import EncryptionError

logger = logging.getLogger(__name__)

# Azure DevOps scope for client credentials (same as devops_Full_sync.py)
AZURE_DEVOPS_SCOPE = ["499b84ac-1321-427f-aa17-267ca6975798/.default"]
API_VERSION = "7.1"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 100


class AzureDevOpsConnector(APIConnector):
    """
    Azure DevOps connector.
    Authenticates via MSAL (client credentials) and fetches projects from the organization.
    """

    def __init__(self, api_connection: APIConnection):
        if not isinstance(api_connection, APIConnection):
            raise ValueError("api_connection must be an APIConnection instance")
        if api_connection.api_type != "azure_devops":
            raise ValueError(f"Unsupported API type: {api_connection.api_type}")
        self.api_connection = api_connection
        self._token: Optional[str] = None
        self._authenticated = False

    def authenticate(self) -> bool:
        """
        Acquire an OAuth2 access token from Azure AD using Service Principal credentials.
        """
        try:
            params = self.api_connection.get_connection_params()
        except EncryptionError as e:
            logger.error("Failed to get Azure DevOps credentials: %s", e)
            return False

        tenant_id = (params.get("tenant_id") or "").strip()
        client_id = (params.get("client_id") or "").strip()
        client_secret = params.get("client_secret") or ""

        if not tenant_id or not client_id or not client_secret:
            logger.error("Azure DevOps credentials incomplete (tenant_id, client_id, client_secret required)")
            return False

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        try:
            app = msal.ConfidentialClientApplication(
                client_id,
                authority=authority,
                client_credential=client_secret,
            )
            result = app.acquire_token_for_client(scopes=AZURE_DEVOPS_SCOPE)
        except Exception as e:
            logger.error("MSAL acquire_token_for_client failed: %s", e)
            return False

        if result and "access_token" in result:
            self._token = result["access_token"]
            self._authenticated = True
            return True

        error = result.get("error", "unknown") if result else "unknown"
        error_desc = result.get("error_description", "No description") if result else "No description"
        logger.error("Azure AD token failed: %s - %s", error, error_desc)
        return False

    def _ensure_authenticated(self) -> None:
        """Ensure we have a token; call authenticate() if not yet authenticated."""
        if not self._authenticated or not self._token:
            if not self.authenticate():
                raise RuntimeError("Azure DevOps authentication failed")

    def _get_organization(self) -> str:
        """Get organization name from connection params."""
        params = self.api_connection.get_connection_params()
        org = (params.get("organization") or "").strip()
        if not org:
            raise ValueError("Azure DevOps organization is not set")
        return org

    def get_projects(self) -> List[Dict[str, str]]:
        """
        Fetch all well-formed projects from the Azure DevOps organization.
        Returns list of dicts with "name" and "id" keys.
        """
        self._ensure_authenticated()
        organization = self._get_organization()

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        all_projects: List[Dict[str, str]] = []
        skip = 0

        while True:
            url = (
                f"https://dev.azure.com/{organization}/_apis/projects"
                f"?api-version={API_VERSION}&$skip={skip}&$top={PAGE_SIZE}"
            )
            try:
                resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            except requests.exceptions.RequestException as e:
                logger.error("Azure DevOps projects request failed: %s", e)
                raise

            if resp.status_code == 401:
                logger.error("Azure DevOps projects returned 401 Unauthorized")
                raise RuntimeError("Unauthorized: token may be invalid or expired")
            if resp.status_code == 403:
                logger.error("Azure DevOps projects returned 403 Forbidden")
                raise RuntimeError("Forbidden: insufficient permissions to list projects")
            if resp.status_code != 200:
                logger.error("Azure DevOps projects returned %s: %s", resp.status_code, resp.text[:200])
                raise RuntimeError(f"Azure DevOps API error: {resp.status_code}")

            try:
                data = resp.json()
            except ValueError as e:
                logger.error("Invalid JSON from Azure DevOps: %s", e)
                raise

            projects = data.get("value") or []
            if not projects:
                break

            for project in projects:
                name = (project.get("name") or "").strip()
                state = (project.get("state") or "").lower()
                if state == "wellformed" and name:
                    all_projects.append({
                        "name": name,
                        "id": project.get("id", ""),
                    })

            if len(projects) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

        return all_projects

    def get_available_modules(self) -> List[str]:
        """
        Return list of project names (for compatibility with APIConnector and selected_modules).
        """
        projects = self.get_projects()
        return [p["name"] for p in projects]

    def fetch_records(
        self,
        module: str,
        params: Optional[Dict] = None,
    ) -> List[Dict]:
        """Not implemented for Day 1; sync execution is out of scope."""
        raise NotImplementedError("Azure DevOps fetch_records is not implemented in this connector")

    def fetch_incremental_records(
        self,
        module: str,
        since: datetime,
    ) -> List[Dict]:
        """Not implemented for Day 1; sync execution is out of scope."""
        raise NotImplementedError("Azure DevOps fetch_incremental_records is not implemented in this connector")
