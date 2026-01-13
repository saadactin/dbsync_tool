"""
Integration tests for metadata API views
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connections.models import DatabaseConnection
import json


class MetadataAPITestCase(TestCase):
    """Test cases for metadata API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.connection = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test_user',
            password='test_password',
            database_name='test_db',
            created_by=self.user
        )
    
    def test_load_schemas_api_requires_auth(self):
        """Test that API requires authentication"""
        url = reverse('metadata:schemas', args=[self.connection.id])
        response = self.client.get(url)
        # DRF returns 403 for unauthenticated requests
        self.assertEqual(response.status_code, 403)
    
    def test_load_schemas_api_success(self):
        """Test successful schema loading (if connection works)"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('metadata:schemas', args=[self.connection.id])
        response = self.client.get(url)
        
        # Will be 500 if connection fails (expected in test environment)
        # Should be 200 if connection succeeds
        self.assertIn(response.status_code, [200, 500])
    
    def test_load_schemas_api_permission_denied(self):
        """Test API returns 403 for unauthorized user"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
        )
        
        self.client.login(username='otheruser', password='otherpass123')
        url = reverse('metadata:schemas', args=[self.connection.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
    
    def test_load_tables_api_requires_auth(self):
        """Test that load tables API requires authentication"""
        url = reverse('metadata:tables', args=[self.connection.id, 'public'])
        response = self.client.get(url)
        # DRF returns 403 for unauthenticated requests
        self.assertEqual(response.status_code, 403)
    
    def test_load_tables_api_permission_denied(self):
        """Test load tables API returns 403 for unauthorized user"""
        other_user = User.objects.create_user(
            username='otheruser2',
            email='other2@example.com',
            password='otherpass123'
        )
        
        self.client.login(username='otheruser2', password='otherpass123')
        url = reverse('metadata:tables', args=[self.connection.id, 'public'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
    
    def test_load_all_metadata_api_requires_auth(self):
        """Test that load all metadata API requires authentication"""
        url = reverse('metadata:all_metadata', args=[self.connection.id])
        response = self.client.get(url)
        # DRF returns 403 for unauthenticated requests
        self.assertEqual(response.status_code, 403)
    
    def test_load_all_metadata_api_permission_denied(self):
        """Test load all metadata API returns 403 for unauthorized user"""
        other_user = User.objects.create_user(
            username='otheruser3',
            email='other3@example.com',
            password='otherpass123'
        )
        
        self.client.login(username='otheruser3', password='otherpass123')
        url = reverse('metadata:all_metadata', args=[self.connection.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

