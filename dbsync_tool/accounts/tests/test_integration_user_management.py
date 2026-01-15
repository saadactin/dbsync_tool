"""
Integration tests for user management feature
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.management import call_command


class UserManagementIntegrationTest(TestCase):
    """
    Integration tests for complete user management flow
    """
    
    def setUp(self):
        self.client = Client()
        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )
    
    def test_complete_user_lifecycle(self):
        """
        Test: Complete user lifecycle (Create → Edit → Delete)
        Given: Admin user exists
        When: Admin creates user, edits user, deletes user
        Then: All operations succeed
        """
        self.client.login(username='admin', password='adminpass123')
        
        # 1. Create user
        data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
            'is_active': True,
        }
        response = self.client.post(reverse('accounts:user_create'), data)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='testuser')
        self.assertTrue(user.is_active)
        
        # 2. Edit user
        edit_data = {
            'username': 'testuser',
            'email': 'updated@example.com',
            'is_active': True,
        }
        response = self.client.post(
            reverse('accounts:user_edit', args=[user.id]),
            edit_data
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.email, 'updated@example.com')
        
        # 3. Delete user (soft delete)
        response = self.client.post(
            reverse('accounts:user_delete', args=[user.id])
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.is_active)  # Soft delete
    
    def test_admin_setup_and_user_creation_flow(self):
        """
        Test: Admin setup → Create users → Manage users
        Given: No users exist
        When: Admin creates multiple users, views list, edits, deletes
        Then: All operations succeed
        """
        self.client.login(username='admin', password='adminpass123')
        
        # Create multiple users
        users = []
        for i in range(3):
            data = {
                'username': f'user{i}',
                'email': f'user{i}@example.com',
                'password1': 'TestPassword123!',
                'password2': 'TestPassword123!',
            }
            response = self.client.post(reverse('accounts:user_create'), data)
            self.assertEqual(response.status_code, 302)
            users.append(User.objects.get(username=f'user{i}'))
        
        # View user list
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.context['users']), 3)
        
        # Edit a user
        edit_data = {
            'username': 'user0',
            'email': 'updated@example.com',
        }
        response = self.client.post(
            reverse('accounts:user_edit', args=[users[0].id]),
            edit_data
        )
        self.assertEqual(response.status_code, 302)
        
        # Delete a user
        response = self.client.post(
            reverse('accounts:user_delete', args=[users[1].id])
        )
        self.assertEqual(response.status_code, 302)
        users[1].refresh_from_db()
        self.assertFalse(users[1].is_active)
    
    def test_multi_user_data_isolation(self):
        """
        Test: Multiple users, each sees only their data
        Given: Two users created
        When: Each user creates connections/jobs
        Then: Users cannot see each other's data
        """
        from connections.models import DatabaseConnection
        from sync_jobs.models import SyncJob
        
        self.client.login(username='admin', password='adminpass123')
        
        # Create two users
        user_a = User.objects.create_user(
            username='usera',
            password='pass123'
        )
        user_b = User.objects.create_user(
            username='userb',
            password='pass123'
        )
        
        # Create connection for user A
        conn_a = DatabaseConnection.objects.create(
            name='User A Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='pass',
            database_name='test',
            created_by=user_a
        )
        
        # Create connection for user B
        conn_b = DatabaseConnection.objects.create(
            name='User B Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='pass',
            database_name='test',
            created_by=user_b
        )
        
        # Login as user A
        self.client.logout()
        self.client.login(username='usera', password='pass123')
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User A Connection')
        self.assertNotContains(response, 'User B Connection')
        
        # Login as user B
        self.client.logout()
        self.client.login(username='userb', password='pass123')
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User B Connection')
        self.assertNotContains(response, 'User A Connection')
    
    def test_regular_user_cannot_escalate_permissions(self):
        """
        Test: Regular user cannot grant themselves admin
        Given: Regular user exists
        When: Regular user tries to access user management
        Then: Access denied (403)
        """
        regular_user = User.objects.create_user(
            username='regular',
            password='pass123'
        )
        
        self.client.login(username='regular', password='pass123')
        
        # Try to access user management
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 403)
        
        # Verify user is still not admin
        regular_user.refresh_from_db()
        self.assertFalse(regular_user.is_staff)
        self.assertFalse(regular_user.is_superuser)

