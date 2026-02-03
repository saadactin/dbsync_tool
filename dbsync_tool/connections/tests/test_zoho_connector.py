"""
Tests for Zoho API connector
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from connections.models import APIConnection
from connections.connectors.zoho import ZohoConnector, ZohoAuthenticator
from connections.connectors.api_base import APIConnector
import requests


class ZohoAuthenticatorTests(TestCase):
    """Test cases for ZohoAuthenticator"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        self.api_connection = APIConnection.objects.create(
            name='Test Zoho Connection',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            tenant=self.user,
            created_by=self.user
        )
    
    @patch('connections.connectors.zoho.requests.post')
    def test_refresh_access_token_success(self, mock_post):
        """Test successful token refresh"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'access_token': 'new_access_token',
            'expires_in': 3600
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        authenticator = ZohoAuthenticator(self.api_connection)
        token = authenticator._refresh_access_token()
        
        self.assertEqual(token, 'new_access_token')
        self.assertIsNotNone(authenticator.token_expiry)
        mock_post.assert_called_once()
    
    @patch('connections.connectors.zoho.requests.post')
    def test_refresh_access_token_failure(self, mock_post):
        """Test token refresh failure"""
        mock_post.side_effect = requests.exceptions.RequestException("Connection error")
        
        authenticator = ZohoAuthenticator(self.api_connection)
        
        with self.assertRaises(Exception):
            authenticator._refresh_access_token()
    
    @patch('connections.connectors.zoho.requests.post')
    def test_get_access_token_cached(self, mock_post):
        """Test that cached token is returned if valid"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'access_token': 'cached_token',
            'expires_in': 3600
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        authenticator = ZohoAuthenticator(self.api_connection)
        
        # First call should refresh
        token1 = authenticator.get_access_token()
        self.assertEqual(token1, 'cached_token')
        
        # Second call should use cached token
        token2 = authenticator.get_access_token()
        self.assertEqual(token2, 'cached_token')
        
        # Should only call API once
        self.assertEqual(mock_post.call_count, 1)


class ZohoConnectorTests(TestCase):
    """Test cases for ZohoConnector"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        self.api_connection = APIConnection.objects.create(
            name='Test Zoho Connection',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            tenant=self.user,
            created_by=self.user
        )
    
    def test_init_valid(self):
        """Test connector initialization with valid connection"""
        connector = ZohoConnector(self.api_connection)
        self.assertIsInstance(connector, APIConnector)
        self.assertEqual(connector.api_connection, self.api_connection)
    
    def test_init_invalid_type(self):
        """Test connector initialization with invalid API type"""
        self.api_connection.api_type = 'invalid_type'
        self.api_connection.save()
        
        with self.assertRaises(ValueError):
            ZohoConnector(self.api_connection)
    
    def test_init_invalid_instance(self):
        """Test connector initialization with invalid instance"""
        with self.assertRaises(ValueError):
            ZohoConnector("not_an_api_connection")
    
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_authenticate_success(self, mock_get_token):
        """Test successful authentication"""
        mock_get_token.return_value = 'valid_token'
        
        connector = ZohoConnector(self.api_connection)
        result = connector.authenticate()
        
        self.assertTrue(result)
    
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_authenticate_failure(self, mock_get_token):
        """Test authentication failure"""
        mock_get_token.side_effect = Exception("Auth failed")
        
        connector = ZohoConnector(self.api_connection)
        result = connector.authenticate()
        
        self.assertFalse(result)
    
    @patch('connections.connectors.zoho.requests.get')
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_get_available_modules_success(self, mock_get_token, mock_get):
        """Test successful module fetching"""
        mock_get_token.return_value = 'valid_token'
        
        mock_response = Mock()
        mock_response.json.return_value = {
            'modules': [
                {'api_name': 'Leads'},
                {'api_name': 'Contacts'},
                {'api_name': 'Accounts'}
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        connector = ZohoConnector(self.api_connection)
        modules = connector.get_available_modules()
        
        self.assertEqual(len(modules), 3)
        self.assertIn('Leads', modules)
        self.assertIn('Contacts', modules)
        self.assertIn('Accounts', modules)
    
    @patch('connections.connectors.zoho.requests.get')
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_get_available_modules_failure(self, mock_get_token, mock_get):
        """Test module fetching failure"""
        mock_get_token.return_value = 'valid_token'
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        
        connector = ZohoConnector(self.api_connection)
        
        with self.assertRaises(Exception):
            connector.get_available_modules()
    
    @patch('connections.connectors.zoho.ZohoConnector._fetch_page')
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_fetch_records_success(self, mock_get_token, mock_fetch_page):
        """Test successful record fetching"""
        mock_get_token.return_value = 'valid_token'
        
        # Mock pagination: first page has more, second page doesn't
        mock_fetch_page.side_effect = [
            ([{'id': '1', 'name': 'Record 1'}], True),
            ([{'id': '2', 'name': 'Record 2'}], False)
        ]
        
        connector = ZohoConnector(self.api_connection)
        records = connector.fetch_records('Leads')
        
        self.assertEqual(len(records), 2)
        self.assertEqual(mock_fetch_page.call_count, 2)
    
    @patch('connections.connectors.zoho.ZohoConnector._fetch_modified_page')
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_fetch_incremental_records_success(self, mock_get_token, mock_fetch_modified):
        """Test successful incremental record fetching"""
        from datetime import datetime, timedelta
        
        mock_get_token.return_value = 'valid_token'
        
        since = datetime.now() - timedelta(days=1)
        
        # Mock pagination
        mock_fetch_modified.side_effect = [
            ([{'id': '1', 'Modified_Time': '2024-01-01T10:00:00+05:30'}], True),
            ([{'id': '2', 'Modified_Time': '2024-01-01T11:00:00+05:30'}], False)
        ]
        
        connector = ZohoConnector(self.api_connection)
        records = connector.fetch_incremental_records('Leads', since)
        
        self.assertEqual(len(records), 2)
        self.assertEqual(mock_fetch_modified.call_count, 2)
    
    @patch('connections.connectors.zoho.requests.get')
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_fetch_page_success(self, mock_get_token, mock_get):
        """Test successful page fetching"""
        mock_get_token.return_value = 'valid_token'
        
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [{'id': '1'}],
            'info': {'more_records': True}
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        connector = ZohoConnector(self.api_connection)
        records, has_more = connector._fetch_page('Leads', {'page': 1, 'per_page': 200})
        
        self.assertEqual(len(records), 1)
        self.assertTrue(has_more)
    
    @patch('connections.connectors.zoho.requests.get')
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_fetch_page_no_content(self, mock_get_token, mock_get):
        """Test page fetching with no content"""
        mock_get_token.return_value = 'valid_token'
        
        mock_response = Mock()
        mock_response.status_code = 204
        mock_get.return_value = mock_response
        
        connector = ZohoConnector(self.api_connection)
        records, has_more = connector._fetch_page('Leads', {'page': 1})
        
        self.assertEqual(len(records), 0)
        self.assertFalse(has_more)
    
    @patch('connections.connectors.zoho.requests.get')
    @patch('connections.connectors.zoho.ZohoAuthenticator.get_access_token')
    def test_fetch_page_404(self, mock_get_token, mock_get):
        """Test page fetching with 404 error"""
        mock_get_token.return_value = 'valid_token'
        
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        connector = ZohoConnector(self.api_connection)
        records, has_more = connector._fetch_page('InvalidModule', {'page': 1})
        
        self.assertEqual(len(records), 0)
        self.assertFalse(has_more)
