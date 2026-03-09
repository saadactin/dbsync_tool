"""
Unit tests for APIConnection model - SAP B1 (sap_b1) type.
Covers creation, clean() validation, get_decrypted_sap_password, get_sap_connection_params, test_connection.
"""
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from connections.models import APIConnection
from core.exceptions import EncryptionError


class SAPConnectionModelTests(TestCase):
    """Test cases for APIConnection with api_type='sap_b1'"""

    def setUp(self):
        self.tenant = User.objects.create_user(
            username='tenant',
            password='testpass123',
            email='tenant@example.com'
        )
        self.creator = User.objects.create_user(
            username='creator',
            password='testpass123',
            email='creator@example.com'
        )
        self.sap_base_url = 'https://sap.example.com:50000/b1s/v2'
        self.sap_username = {'UserName': 'API_USER', 'CompanyDB': 'SBODEMO'}
        self.sap_password = 'sap_secret_123'
        self.sap_endpoints = [
            {'name': 'Journal Entry', 'endpoint': 'JournalEntries', 'id_field': 'JdtNum'},
            {'name': 'Items', 'endpoint': 'Items', 'id_field': 'ItemCode'},
        ]

    def test_sap_connection_creation(self):
        """Test creating APIConnection with SAP fields."""
        conn = APIConnection.objects.create(
            name='Test SAP Connection',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            sap_endpoints=self.sap_endpoints,
            tenant=self.tenant,
            created_by=self.creator
        )
        self.assertIsNotNone(conn.id)
        self.assertEqual(conn.name, 'Test SAP Connection')
        self.assertEqual(conn.api_type, 'sap_b1')
        self.assertEqual(conn.sap_base_url, self.sap_base_url)
        self.assertEqual(conn.sap_username, self.sap_username)
        self.assertEqual(conn.sap_endpoints, self.sap_endpoints)
        self.assertTrue(conn.is_active)
        conn.refresh_from_db()
        self.assertTrue(conn.sap_password.startswith('gAAAAAB'))
        self.assertNotEqual(conn.sap_password, self.sap_password)

    def test_sap_password_encryption_on_save(self):
        """Test that sap_password is encrypted on save."""
        conn = APIConnection.objects.create(
            name='SAP Encrypt Test',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        conn.refresh_from_db()
        self.assertTrue(conn.sap_password.startswith('gAAAAAB'))
        self.assertNotEqual(conn.sap_password, self.sap_password)

    def test_clean_sap_required_fields_missing_base_url(self):
        """When api_type is sap_b1, sap_base_url is required."""
        conn = APIConnection(
            name='SAP No URL',
            api_type='sap_b1',
            sap_base_url='',
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        with self.assertRaises(ValidationError) as ctx:
            conn.full_clean()
        self.assertIn('sap_base_url', ctx.exception.message_dict)

    def test_clean_sap_required_fields_missing_password(self):
        """When api_type is sap_b1, sap_password is required."""
        conn = APIConnection(
            name='SAP No Pass',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password='',
            tenant=self.tenant,
            created_by=self.creator
        )
        with self.assertRaises(ValidationError) as ctx:
            conn.full_clean()
        self.assertIn('sap_password', ctx.exception.message_dict)

    def test_clean_sap_username_required(self):
        """When api_type is sap_b1, sap_username (dict with UserName, CompanyDB) is required."""
        conn = APIConnection(
            name='SAP No Username',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=None,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        with self.assertRaises(ValidationError) as ctx:
            conn.full_clean()
        self.assertIn('sap_username', ctx.exception.message_dict)

    def test_clean_sap_username_must_be_dict(self):
        """sap_username must be a dict for sap_b1."""
        conn = APIConnection(
            name='SAP Bad Username',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username='not_a_dict',
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        with self.assertRaises(ValidationError) as ctx:
            conn.full_clean()
        self.assertIn('sap_username', ctx.exception.message_dict)

    def test_clean_sap_username_must_have_keys(self):
        """sap_username must contain UserName and CompanyDB."""
        conn = APIConnection(
            name='SAP Incomplete Username',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username={'UserName': 'U'},  # missing CompanyDB
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        with self.assertRaises(ValidationError) as ctx:
            conn.full_clean()
        self.assertIn('sap_username', ctx.exception.message_dict)

    def test_clean_sap_base_url_valid_url(self):
        """sap_base_url must be a valid URL for sap_b1."""
        conn = APIConnection(
            name='SAP Invalid URL',
            api_type='sap_b1',
            sap_base_url='not-a-url',
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        with self.assertRaises(ValidationError) as ctx:
            conn.full_clean()
        self.assertIn('sap_base_url', ctx.exception.message_dict)

    def test_clean_sap_valid_passes(self):
        """Valid SAP fields pass clean()."""
        conn = APIConnection(
            name='SAP Valid',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            sap_endpoints=[],
            tenant=self.tenant,
            created_by=self.creator
        )
        conn.full_clean()
        conn.save()
        self.assertIsNotNone(conn.id)

    def test_get_decrypted_sap_password(self):
        """get_decrypted_sap_password returns original password after save."""
        conn = APIConnection.objects.create(
            name='SAP Decrypt Test',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        decrypted = conn.get_decrypted_sap_password()
        self.assertEqual(decrypted, self.sap_password)

    def test_get_decrypted_sap_password_empty_raises(self):
        """get_decrypted_sap_password raises EncryptionError when password not set."""
        conn = APIConnection.objects.create(
            name='SAP No Pass Saved',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        APIConnection.objects.filter(pk=conn.pk).update(sap_password='')
        conn.refresh_from_db()
        with self.assertRaises(EncryptionError) as ctx:
            conn.get_decrypted_sap_password()
        self.assertIn('not set', str(ctx.exception).lower())

    def test_get_decrypted_sap_password_reset_required_raises(self):
        """get_decrypted_sap_password raises when sap_password is RESET_REQUIRED."""
        conn = APIConnection.objects.create(
            name='SAP Reset',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        APIConnection.objects.filter(pk=conn.pk).update(sap_password='RESET_REQUIRED')
        conn.refresh_from_db()
        with self.assertRaises(EncryptionError):
            conn.get_decrypted_sap_password()

    def test_get_sap_connection_params(self):
        """get_sap_connection_params returns base_url, username, password (decrypted)."""
        conn = APIConnection.objects.create(
            name='SAP Params Test',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        params = conn.get_sap_connection_params()
        self.assertEqual(params['base_url'], self.sap_base_url)
        self.assertEqual(params['username'], self.sap_username)
        self.assertEqual(params['password'], self.sap_password)

    @patch('connections.connectors.sap.SAPConnector')
    def test_test_connection_sap_success(self, mock_sap_connector_class):
        """test_connection for sap_b1 returns (True, message, modules) when authenticate and get_available_modules succeed."""
        mock_connector = MagicMock()
        mock_connector.authenticate.return_value = True
        mock_connector.get_available_modules.return_value = ['JournalEntries', 'Items']
        mock_sap_connector_class.return_value = mock_connector

        conn = APIConnection.objects.create(
            name='SAP Test Conn',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        success, message, modules = conn.test_connection()
        self.assertTrue(success)
        self.assertIn('endpoints', message.lower() or '')
        self.assertEqual(modules, ['JournalEntries', 'Items'])
        mock_connector.authenticate.assert_called_once()
        mock_connector.get_available_modules.assert_called_once()

    @patch('connections.connectors.sap.SAPConnector')
    def test_test_connection_sap_auth_fails(self, mock_sap_connector_class):
        """test_connection for sap_b1 returns (False, message, []) when authenticate returns False."""
        mock_connector = MagicMock()
        mock_connector.authenticate.return_value = False
        mock_sap_connector_class.return_value = mock_connector

        conn = APIConnection.objects.create(
            name='SAP Auth Fail',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        success, message, modules = conn.test_connection()
        self.assertFalse(success)
        self.assertEqual(modules, [])
        mock_connector.authenticate.assert_called_once()
        mock_connector.get_available_modules.assert_not_called()

    @patch('connections.connectors.sap.SAPConnector')
    def test_test_connection_sap_exception(self, mock_sap_connector_class):
        """test_connection for sap_b1 returns (False, str(e), []) when connector raises."""
        mock_sap_connector_class.side_effect = Exception('Network error')

        conn = APIConnection.objects.create(
            name='SAP Exception',
            api_type='sap_b1',
            sap_base_url=self.sap_base_url,
            sap_username=self.sap_username,
            sap_password=self.sap_password,
            tenant=self.tenant,
            created_by=self.creator
        )
        success, message, modules = conn.test_connection()
        self.assertFalse(success)
        self.assertIn('Network error', message)
        self.assertEqual(modules, [])
