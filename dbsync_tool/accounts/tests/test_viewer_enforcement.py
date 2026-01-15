"""
Tests for Viewer role enforcement
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connections.models import DatabaseConnection
from accounts.models import UserProfile, Role


class ViewerEnforcementTest(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create Admin
        self.admin = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=self.admin,
            role=Role.ADMIN,
            tenant=self.admin
        )
        
        # Create Viewer
        self.viewer = User.objects.create_user(
            username='viewer',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.viewer,
            role=Role.VIEWER,
            tenant=self.admin
        )
        
        # Create connection
        self.connection = DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='pass',
            database_name='testdb',
            created_by=self.admin,
            tenant=self.admin
        )
    
    def test_viewer_cannot_create_connection(self):
        """Test that Viewer cannot create connection"""
        self.client.login(username='viewer', password='testpass123')
        
        response = self.client.post(
            reverse('connections:create'),
            {
                'name': 'New Connection',
                'db_type': 'postgres',
                'host': 'localhost',
                'port': 5432,
                'username': 'user',
                'password': 'pass',
                'database_name': 'newdb',
            }
        )
        
        # Should be blocked (403 Permission Denied)
        self.assertEqual(response.status_code, 403)
        
        # Connection should not be created
        self.assertFalse(
            DatabaseConnection.objects.filter(name='New Connection').exists()
        )
    
    def test_viewer_cannot_update_connection(self):
        """Test that Viewer cannot update connection"""
        self.client.login(username='viewer', password='testpass123')
        
        response = self.client.post(
            reverse('connections:update', args=[self.connection.id]),
            {
                'name': 'Updated Connection',
                'db_type': 'postgres',
                'host': 'localhost',
                'port': 5432,
                'username': 'user',
                'password': 'pass',
                'database_name': 'testdb',
            }
        )
        
        # Should be blocked (403)
        self.assertEqual(response.status_code, 403)
        
        # Connection should not be updated
        self.connection.refresh_from_db()
        self.assertNotEqual(self.connection.name, 'Updated Connection')
    
    def test_viewer_cannot_delete_connection(self):
        """Test that Viewer cannot delete connection"""
        self.client.login(username='viewer', password='testpass123')
        
        connection_id = self.connection.id
        response = self.client.post(
            reverse('connections:delete', args=[self.connection.id])
        )
        
        # Should be blocked (403)
        self.assertEqual(response.status_code, 403)
        
        # Connection should still exist
        self.assertTrue(
            DatabaseConnection.objects.filter(id=connection_id).exists()
        )
    
    def test_viewer_can_view_connection(self):
        """Test that Viewer can view connection (GET request)"""
        self.client.login(username='viewer', password='testpass123')
        
        response = self.client.get(
            reverse('connections:detail', args=[self.connection.id])
        )
        
        # Should be allowed (200)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Connection')
    
    def test_viewer_can_list_connections(self):
        """Test that Viewer can list connections"""
        self.client.login(username='viewer', password='testpass123')
        
        response = self.client.get(reverse('connections:list'))
        
        # Should be allowed (200)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Connection')

