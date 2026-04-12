"""
Tests for connection views
"""
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connections.models import DatabaseConnection
from connections.forms import DatabaseConnectionForm


class ConnectionViewTests(TestCase):
    """Test cases for connection views"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )

        # RBAC/Tenant setup: for Admin users, `tenant` is self (see TenantService rules)
        from accounts.models import UserProfile, Role
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN, 'tenant': None}
        )
        UserProfile.objects.update_or_create(
            user=self.other_user,
            defaults={'role': Role.ADMIN, 'tenant': None}
        )

        self.connection = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="testuser",
            password="testpass",
            database_name="testdb",
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
    
    def test_list_view_requires_login(self):
        """Test that list view requires authentication"""
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_list_view_authenticated(self):
        """Test list view when authenticated"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.connection, response.context['connections'])
    
    def test_list_view_shows_only_user_connections(self):
        """Test that users only see their own connections"""
        # Create connection for other user
        other_conn = DatabaseConnection.objects.create(
            name="Other DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="other",
            password="pass",
            database_name="otherdb",
            created_by=self.other_user,
            tenant=self.other_user,
            is_active=True
        )
        
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('connections:list'))
        connections = response.context['connections']
        
        self.assertIn(self.connection, connections)
        self.assertNotIn(other_conn, connections)
    
    def test_create_view_get(self):
        """Test create view GET request"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('connections:create'))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], DatabaseConnectionForm)
    
    def test_create_view_post_valid(self):
        """Test create view POST with valid data"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('connections:create'), {
            'name': 'New Connection',
            'db_type': 'postgres',
            'host': 'localhost',
            'port': 5432,
            'username': 'user',
            'password': 'pass',
            'database_name': 'newdb',
            'is_active': True
        })
        self.assertEqual(response.status_code, 302)  # Redirect after success
        self.assertTrue(DatabaseConnection.objects.filter(name='New Connection').exists())
    
    def test_detail_view_permissions(self):
        """Test that users can only view their own connections"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('connections:detail', args=[self.connection.id]))
        self.assertEqual(response.status_code, 200)
        
        # Try to access other user's connection
        other_conn = DatabaseConnection.objects.create(
            name="Other DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="other",
            password="pass",
            database_name="otherdb",
            created_by=self.other_user,
            tenant=self.other_user,
            is_active=True
        )
        response = self.client.get(reverse('connections:detail', args=[other_conn.id]))
        self.assertEqual(response.status_code, 404)
    
    def test_update_view_permissions(self):
        """Test that users can only update their own connections"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('connections:update', args=[self.connection.id]))
        self.assertEqual(response.status_code, 200)
        
        # Try to update other user's connection
        other_conn = DatabaseConnection.objects.create(
            name="Other DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="other",
            password="pass",
            database_name="otherdb",
            created_by=self.other_user,
            tenant=self.other_user,
            is_active=True
        )
        response = self.client.get(reverse('connections:update', args=[other_conn.id]))
        self.assertEqual(response.status_code, 404)
    
    def test_delete_view_permissions(self):
        """Test that users can only delete their own connections"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('connections:delete', args=[self.connection.id]))
        self.assertEqual(response.status_code, 200)
        
        # Try to delete other user's connection
        other_conn = DatabaseConnection.objects.create(
            name="Other DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="other",
            password="pass",
            database_name="otherdb",
            created_by=self.other_user,
            tenant=self.other_user,
            is_active=True
        )
        response = self.client.post(reverse('connections:delete', args=[other_conn.id]))
        self.assertEqual(response.status_code, 404)


class ConnectionTestAndListDatabasesViewTests(TestCase):
    """Tests for test-and-list-databases endpoint (create form test connection)."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        from accounts.models import UserProfile, Role
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN, 'tenant': None}
        )
        self.url = reverse('connections:test_and_list_databases')

    def _post(self, data):
        self.client.login(username='testuser', password='testpass123')
        return self.client.post(
            self.url,
            data=json.dumps(data),
            content_type='application/json',
        )

    def test_oracle_adw_requires_service_name(self):
        """Oracle ADW without service name (database_name) must return 400."""
        resp = self._post({
            'db_type': 'oracle_adw',
            'host': 'adb.ap-mumbai-1.oraclecloud.com',
            'port': 1522,
            'username': 'admin',
            'password': 'secret',
        })
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.content)
        self.assertFalse(body.get('success', True))
        self.assertIn('Service name', body.get('message', ''))

    def test_oracle_adw_test_connection_receives_service_name(self):
        """Oracle ADW test uses database_name (service name) when building connector."""
        with patch('connections.views.get_connector') as mock_get_connector:
            mock_conn = MagicMock()
            mock_conn.list_databases.return_value = ['ge3cf99f4b998df_ktestadw_high.adb.oraclecloud.com']
            mock_get_connector.return_value = mock_conn

            resp = self._post({
                'db_type': 'oracle_adw',
                'host': 'adb.ap-mumbai-1.oraclecloud.com',
                'port': 1522,
                'username': 'admin',
                'password': 'KOEL$$adw1234',
                'database_name': 'ge3cf99f4b998df_ktestadw_high.adb.oraclecloud.com',
            })
            self.assertEqual(resp.status_code, 200)
            mock_get_connector.assert_called_once()
            call_kw = mock_get_connector.call_args[1]
            self.assertEqual(call_kw.get('database_name'), 'ge3cf99f4b998df_ktestadw_high.adb.oraclecloud.com')
            self.assertEqual(call_kw.get('db_type'), 'oracle_adw')
            body = json.loads(resp.content)
            self.assertTrue(body.get('success'))
            self.assertIn('ge3cf99f4b998df_ktestadw_high.adb.oraclecloud.com', body.get('databases', []))

    def test_mongodb_test_and_list_databases_success(self):
        """MongoDB test endpoint should return databases list via connector.list_databases()."""
        with patch('connections.views.get_connector') as mock_get_connector:
            mock_conn = MagicMock()
            mock_conn.list_databases.return_value = ['appdb', 'analytics']
            mock_get_connector.return_value = mock_conn

            resp = self._post({
                'db_type': 'mongodb',
                'host': 'localhost',
                'port': 27017,
                'username': 'admin',
                'password': 'secret',
                # database_name is optional for the test-and-list endpoint
                'database_name': '',
            })
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.content)
            self.assertTrue(body.get('success'))
            self.assertEqual(body.get('databases'), ['appdb', 'analytics'])
            mock_get_connector.assert_called_once()
            call_kw = mock_get_connector.call_args[1]
            self.assertEqual(call_kw.get('username'), 'admin')
            self.assertEqual(call_kw.get('password'), 'secret')

    def test_mongodb_localhost_empty_credentials_defaults_root(self):
        """Local MongoDB may omit credentials; server applies root/root default like the form."""
        with patch('connections.views.get_connector') as mock_get_connector:
            mock_conn = MagicMock()
            mock_conn.list_databases.return_value = ['appdb']
            mock_get_connector.return_value = mock_conn

            resp = self._post({
                'db_type': 'mongodb',
                'host': 'localhost',
                'port': 27017,
                'username': '',
                'password': '',
            })
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.content)
            self.assertTrue(body.get('success'))
            mock_get_connector.assert_called_once()
            call_kw = mock_get_connector.call_args[1]
            self.assertEqual(call_kw.get('username'), 'root')
            self.assertEqual(call_kw.get('password'), 'root')

    def test_mongodb_remote_requires_credentials(self):
        """Non-local MongoDB still requires explicit credentials in the test endpoint."""
        resp = self._post({
            'db_type': 'mongodb',
            'host': 'mongo.example.com',
            'port': 27017,
            'username': '',
            'password': '',
        })
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.content)
        self.assertFalse(body.get('success', True))
        self.assertIn('Username', body.get('message', ''))

