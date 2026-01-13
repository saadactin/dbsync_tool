"""
Tests for connection views
"""
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
        self.connection = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="testuser",
            password="testpass",
            database_name="testdb",
            created_by=self.user
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
            created_by=self.other_user
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
            created_by=self.other_user
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
            created_by=self.other_user
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
            created_by=self.other_user
        )
        response = self.client.post(reverse('connections:delete', args=[other_conn.id]))
        self.assertEqual(response.status_code, 404)

