"""
Unit tests for SAP Business One connector (SAPConnector).
Uses mocked requests.Session to avoid real HTTP calls.
"""
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User

from connections.models import APIConnection
from connections.connectors.sap import SAPConnector
from connections.connectors.api_base import APIConnector
from core.constants import SAP_DOCUMENT_TYPES


class SAPConnectorTests(TestCase):
    """Test cases for SAPConnector"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.api_connection = APIConnection.objects.create(
            name='Test SAP Connection',
            api_type='sap_b1',
            sap_base_url='https://sap.example.com:50000/b1s/v2',
            sap_username={'UserName': 'API_USER', 'CompanyDB': 'SBODEMO'},
            sap_password='sap_secret_123',
            sap_endpoints=[{'endpoint': 'JournalEntries', 'id_field': 'JdtNum'}],
            tenant=self.user,
            created_by=self.user
        )

    def test_init_valid(self):
        """Constructor with valid APIConnection (sap_b1) succeeds."""
        connector = SAPConnector(self.api_connection)
        self.assertIsInstance(connector, APIConnector)
        self.assertEqual(connector.api_connection, self.api_connection)
        self.assertIsNotNone(connector.session)

    def test_init_not_apiconnection_raises(self):
        """Constructor with non-APIConnection raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            SAPConnector(Mock())
        self.assertIn('APIConnection', str(ctx.exception))

    def test_init_wrong_api_type_raises(self):
        """Constructor with api_type != sap_b1 raises ValueError."""
        self.api_connection.api_type = 'zoho_crm'
        with self.assertRaises(ValueError) as ctx:
            SAPConnector(self.api_connection)
        self.assertIn('Unsupported API type', str(ctx.exception))

    @patch('connections.connectors.sap.requests.Session')
    @patch.object(SAPConnector, '_get_credentials')
    def test_authenticate_success(self, mock_get_credentials, mock_session_class):
        """authenticate returns True when Login returns 200."""
        mock_get_credentials.return_value = {
            'CompanyDB': 'SBODEMO',
            'UserName': 'API_USER',
            'Password': 'secret',
        }
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session
        connector = SAPConnector(self.api_connection)
        connector._base_url = 'https://sap.example.com:50000/b1s/v2'
        result = connector.authenticate()
        self.assertTrue(result)
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        self.assertIn('/Login', call_args[0][0])
        self.assertEqual(call_args[1]['json']['CompanyDB'], 'SBODEMO')
        self.assertEqual(call_args[1]['json']['UserName'], 'API_USER')
        self.assertEqual(call_args[1]['json']['Password'], 'secret')

    @patch('connections.connectors.sap.requests.Session')
    @patch.object(SAPConnector, '_get_credentials')
    def test_authenticate_failure_401(self, mock_get_credentials, mock_session_class):
        """authenticate returns False when Login returns 401."""
        mock_get_credentials.return_value = {
            'CompanyDB': 'SBODEMO',
            'UserName': 'API_USER',
            'Password': 'secret',
        }
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = 'Unauthorized'
        mock_response.json.side_effect = Exception()
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session
        connector = SAPConnector(self.api_connection)
        connector._base_url = 'https://sap.example.com:50000/b1s/v2'
        result = connector.authenticate()
        self.assertFalse(result)

    @patch('connections.connectors.sap.requests.Session')
    @patch.object(SAPConnector, '_get_credentials')
    def test_authenticate_request_exception(self, mock_get_credentials, mock_session_class):
        """authenticate returns False when request raises."""
        import requests
        mock_get_credentials.return_value = {
            'CompanyDB': 'SBODEMO',
            'UserName': 'API_USER',
            'Password': 'secret',
        }
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.exceptions.RequestException('Network error')
        mock_session_class.return_value = mock_session
        connector = SAPConnector(self.api_connection)
        connector._base_url = 'https://sap.example.com:50000/b1s/v2'
        result = connector.authenticate()
        self.assertFalse(result)

    @patch('connections.connectors.sap.requests.Session')
    def test_get_available_modules_returns_endpoint_names(self, mock_session_class):
        """get_available_modules returns list of endpoint names from SAP_DOCUMENT_TYPES."""
        mock_session_class.return_value = MagicMock()
        with patch.object(SAPConnector, '_ensure_authenticated'):
            connector = SAPConnector(self.api_connection)
            connector._authenticated = True
            modules = connector.get_available_modules()
        expected = [e['endpoint'] for e in SAP_DOCUMENT_TYPES]
        self.assertEqual(modules, expected)

    @patch('connections.connectors.sap.requests.Session')
    @patch.object(SAPConnector, '_ensure_authenticated')
    def test_fetch_records_single_page(self, mock_ensure, mock_session_class):
        """fetch_records returns records from single page (value list)."""
        mock_ensure.return_value = None
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'value': [
                {'JdtNum': 1, 'RefDate': '2024-01-01'},
                {'JdtNum': 2, 'RefDate': '2024-01-02'},
            ]
        }
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        connector = SAPConnector(self.api_connection)
        connector._base_url = 'https://sap.example.com:50000/b1s/v2'
        connector._authenticated = True
        records = connector.fetch_records('JournalEntries')
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['JdtNum'], 1)
        mock_session.get.assert_called_once()
        call_kwargs = mock_session.get.call_args[1]
        self.assertEqual(call_kwargs['params']['$top'], 1000)
        self.assertEqual(call_kwargs['params']['$skip'], 0)

    @patch('connections.connectors.sap.requests.Session')
    @patch.object(SAPConnector, '_ensure_authenticated')
    def test_fetch_records_pagination(self, mock_ensure, mock_session_class):
        """fetch_records combines multiple pages."""
        mock_ensure.return_value = None
        first = Mock()
        first.ok = True
        first.json.return_value = {'value': [{'JdtNum': i} for i in range(1000)]}
        second = Mock()
        second.ok = True
        second.json.return_value = {'value': [{'JdtNum': 1000}]}
        mock_session = MagicMock()
        mock_session.get.side_effect = [first, second]
        mock_session_class.return_value = mock_session
        connector = SAPConnector(self.api_connection)
        connector._base_url = 'https://sap.example.com:50000/b1s/v2'
        connector._authenticated = True
        records = connector.fetch_records('JournalEntries')
        self.assertEqual(len(records), 1001)
        self.assertEqual(mock_session.get.call_count, 2)
        self.assertEqual(mock_session.get.call_args_list[1][1]['params']['$skip'], 1000)

    @patch('connections.connectors.sap.requests.Session')
    @patch.object(SAPConnector, '_ensure_authenticated')
    def test_fetch_records_empty_value_breaks_loop(self, mock_ensure, mock_session_class):
        """fetch_records stops when value is empty or missing."""
        mock_ensure.return_value = None
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {'value': []}
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        connector = SAPConnector(self.api_connection)
        connector._base_url = 'https://sap.example.com:50000/b1s/v2'
        connector._authenticated = True
        records = connector.fetch_records('JournalEntries')
        self.assertEqual(records, [])

    @patch('connections.connectors.sap.requests.Session')
    def test_fetch_incremental_records_returns_list(self, mock_session_class):
        """fetch_incremental_records returns list (delegates to fetch_records)."""
        from datetime import datetime
        mock_session_class.return_value = MagicMock()
        with patch.object(SAPConnector, 'fetch_records', return_value=[{'id': 1}]):
            connector = SAPConnector(self.api_connection)
            result = connector.fetch_incremental_records('JournalEntries', datetime(2024, 1, 1))
        self.assertEqual(result, [{'id': 1}])

    @patch('connections.connectors.sap.requests.Session')
    def test_logout_calls_post_logout(self, mock_session_class):
        """logout calls POST .../Logout and closes session."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        connector = SAPConnector(self.api_connection)
        connector._base_url = 'https://sap.example.com:50000/b1s/v2'
        connector.logout()
        mock_session.post.assert_called_once()
        self.assertIn('/Logout', mock_session.post.call_args[0][0])
        mock_session.close.assert_called_once()
