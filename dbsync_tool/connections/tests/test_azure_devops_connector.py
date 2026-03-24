"""
Tests for Azure DevOps connector.
"""
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User

from connections.models import APIConnection
from connections.connectors.azure_devops import AzureDevOpsConnector
from core.exceptions import EncryptionError


def _make_mock_connection(
    api_type='azure_devops',
    organization='MyOrg',
    tenant_id='tenant-123',
    client_id='client-456',
    client_secret='secret-789',
):
    """Create a mock APIConnection with get_connection_params returning Azure params."""
    conn = Mock(spec=APIConnection)
    conn.api_type = api_type
    conn.get_connection_params.return_value = {
        'tenant_id': tenant_id,
        'client_id': client_id,
        'client_secret': client_secret,
        'organization': organization,
    }
    return conn


class AzureDevOpsConnectorInitTests(TestCase):
    """Test AzureDevOpsConnector __init__."""

    def test_init_requires_apiconnection(self):
        """Passing None or non-APIConnection raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            AzureDevOpsConnector(None)
        self.assertIn('APIConnection', str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            AzureDevOpsConnector('not-a-connection')
        self.assertIn('APIConnection', str(cm.exception))

    def test_init_requires_azure_devops_type(self):
        """Passing APIConnection with api_type other than azure_devops raises ValueError."""
        conn = _make_mock_connection(api_type='zoho_crm')
        with self.assertRaises(ValueError) as cm:
            AzureDevOpsConnector(conn)
        self.assertIn('Unsupported API type', str(cm.exception))

    def test_init_accepts_azure_devops(self):
        """Passing valid mock with api_type azure_devops does not raise."""
        conn = _make_mock_connection()
        c = AzureDevOpsConnector(conn)
        self.assertEqual(c.api_connection, conn)


class AzureDevOpsConnectorAuthenticateTests(TestCase):
    """Test AzureDevOpsConnector.authenticate() with mocked MSAL."""

    @patch('connections.connectors.azure_devops.msal.ConfidentialClientApplication')
    def test_authenticate_success(self, mock_msal_class):
        """When MSAL returns access_token, authenticate() returns True."""
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {'access_token': 'tok123'}
        mock_msal_class.return_value = mock_app
        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        result = connector.authenticate()
        self.assertTrue(result)
        self.assertTrue(connector._authenticated)
        self.assertEqual(connector._token, 'tok123')

    @patch('connections.connectors.azure_devops.msal.ConfidentialClientApplication')
    def test_authenticate_failure_no_token(self, mock_msal_class):
        """When MSAL result has no access_token, authenticate() returns False."""
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            'error': 'invalid_client',
            'error_description': 'Bad secret',
        }
        mock_msal_class.return_value = mock_app
        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        result = connector.authenticate()
        self.assertFalse(result)
        self.assertFalse(connector._authenticated)

    def test_authenticate_handles_encryption_error(self):
        """When get_connection_params raises EncryptionError, authenticate() returns False."""
        conn = _make_mock_connection()
        conn.get_connection_params.side_effect = EncryptionError('Decryption failed')
        connector = AzureDevOpsConnector(conn)
        result = connector.authenticate()
        self.assertFalse(result)


class AzureDevOpsConnectorGetProjectsTests(TestCase):
    """Test AzureDevOpsConnector.get_projects() and get_available_modules() with mocked requests."""

    @patch('connections.connectors.azure_devops.requests.get')
    def test_get_projects_returns_wellformed_only(self, mock_get):
        """Only projects with state 'wellformed' and non-empty name are returned."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'value': [
                {'name': 'P1', 'id': 'id1', 'state': 'wellformed'},
                {'name': '', 'id': 'id2', 'state': 'wellformed'},
                {'name': 'P3', 'id': 'id3', 'state': 'deleted'},
            ]
        }
        mock_get.return_value = mock_response

        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        connector._authenticated = True
        connector._token = 'fake-token'

        projects = connector.get_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['name'], 'P1')
        self.assertEqual(projects[0]['id'], 'id1')

    @patch('connections.connectors.azure_devops.requests.get')
    def test_get_projects_pagination(self, mock_get):
        """Pagination is used until fewer than PAGE_SIZE items returned."""
        def side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get('url', '')
            if '$skip=0' in url:
                return Mock(status_code=200, json=lambda: {'value': [{'name': 'A', 'id': '1', 'state': 'wellformed'}] * 100})
            if '$skip=100' in url:
                return Mock(status_code=200, json=lambda: {'value': [{'name': 'B', 'id': '2', 'state': 'wellformed'}]})
            return Mock(status_code=200, json=lambda: {'value': []})

        mock_get.side_effect = side_effect
        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        connector._authenticated = True
        connector._token = 'fake-token'

        projects = connector.get_projects()
        self.assertEqual(len(projects), 101)
        self.assertEqual(projects[0]['name'], 'A')
        self.assertEqual(projects[100]['name'], 'B')

    @patch('connections.connectors.azure_devops.requests.get')
    def test_get_projects_unauthorized(self, mock_get):
        """When API returns 401, get_projects raises RuntimeError."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        connector._authenticated = True
        connector._token = 'fake-token'

        with self.assertRaises(RuntimeError) as cm:
            connector.get_projects()
        self.assertIn('Unauthorized', str(cm.exception))

    def test_get_available_modules_returns_project_names(self):
        """get_available_modules returns list of project names from get_projects."""
        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        connector._authenticated = True
        connector._token = 'fake-token'
        with patch.object(connector, 'get_projects', return_value=[
            {'name': 'ProjA', 'id': '1'},
            {'name': 'ProjB', 'id': '2'},
        ]):
            modules = connector.get_available_modules()
        self.assertEqual(modules, ['ProjA', 'ProjB'])

    def test_fetch_records_not_implemented(self):
        """fetch_records raises NotImplementedError."""
        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        with self.assertRaises(NotImplementedError):
            connector.fetch_records('ProjA')

    def test_fetch_incremental_records_not_implemented(self):
        """fetch_incremental_records raises NotImplementedError."""
        from datetime import datetime
        conn = _make_mock_connection()
        connector = AzureDevOpsConnector(conn)
        with self.assertRaises(NotImplementedError):
            connector.fetch_incremental_records('ProjA', datetime.now())
