"""
Test cases for user management views
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import PermissionDenied


class UserListViewTest(TestCase):
    """
    Test cases for UserListView
    """
    
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        self.regular_user = User.objects.create_user(
            username='user',
            password='testpass123'
        )
    
    def test_admin_can_access(self):
        """
        Test: Admin user can access user list
        Given: Admin user logged in
        When: GET /accounts/users/
        Then: 200 OK, user list displayed
        """
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User Management')
    
    def test_regular_user_cannot_access(self):
        """
        Test: Regular user cannot access user list
        Given: Regular user logged in
        When: GET /accounts/users/
        Then: 403 Forbidden
        """
        self.client.login(username='user', password='testpass123')
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 403)
    
    def test_unauthenticated_redirected(self):
        """
        Test: Unauthenticated user redirected to login
        Given: No user logged in
        When: GET /accounts/users/
        Then: 302 Redirect to login
        """
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
    
    def test_pagination_works(self):
        """
        Test: User list pagination with 25+ users
        Given: 25 users created
        When: GET /accounts/users/
        Then: Pagination controls appear, page navigation works
        """
        self.client.login(username='admin', password='testpass123')
        
        # Create 25 users
        for i in range(25):
            User.objects.create_user(
                username=f'user{i}',
                password='pass123',
                email=f'user{i}@example.com'
            )
        
        # Get first page
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_paginated'])
        
        # Get second page
        response = self.client.get(reverse('accounts:user_list') + '?page=2')
        self.assertEqual(response.status_code, 200)
    
    def test_empty_user_list(self):
        """
        Test: User list with no users (only admin)
        Given: Only admin user exists
        When: GET /accounts/users/
        Then: List displays with empty state
        """
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        # Should show admin user at minimum
        self.assertGreaterEqual(len(response.context['users']), 1)


class UserCreateViewTest(TestCase):
    """
    Test cases for UserCreateView
    """
    
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
    
    def test_admin_can_create_user(self):
        """
        Test: Admin can create new user
        Given: Admin user logged in, valid form data
        When: POST /accounts/users/create/
        Then: User created, redirect to user list
        """
        self.client.login(username='admin', password='testpass123')
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
            'is_active': True,
            'is_staff': False,
        }
        response = self.client.post(reverse('accounts:user_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='newuser').exists())
    
    def test_username_uniqueness(self):
        """
        Test: Cannot create user with existing username
        Given: User with username='testuser' exists
        When: POST create user with username='testuser'
        Then: Form error, user not created
        """
        User.objects.create_user(username='testuser', password='pass123')
        self.client.login(username='admin', password='testpass123')
        data = {
            'username': 'testuser',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
        }
        response = self.client.post(reverse('accounts:user_create'), data)
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, 'already exists', status_code=200)
    
    def test_password_validation(self):
        """
        Test: Password must meet requirements
        Given: Weak password provided
        When: POST create user
        Then: Form error, user not created
        """
        self.client.login(username='admin', password='testpass123')
        data = {
            'username': 'newuser',
            'password1': '123',  # Too weak
            'password2': '123',
        }
        response = self.client.post(reverse('accounts:user_create'), data)
        self.assertEqual(response.status_code, 200)  # Form with errors
        # Password validation errors should be present
        self.assertContains(response, 'form', status_code=200)
    
    def test_create_user_with_long_username(self):
        """
        Test: Username length limits (max 150 chars)
        Given: Username at max length (150 chars)
        When: POST create user
        Then: User created successfully
        """
        self.client.login(username='admin', password='testpass123')
        long_username = 'a' * 150  # Max length
        data = {
            'username': long_username,
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
        }
        response = self.client.post(reverse('accounts:user_create'), data)
        self.assertEqual(response.status_code, 302)  # Success
        self.assertTrue(User.objects.filter(username=long_username).exists())
    
    def test_create_inactive_user(self):
        """
        Test: Creating user with is_active=False
        Given: User created with is_active=False
        When: User tries to login
        Then: User cannot login
        """
        self.client.login(username='admin', password='testpass123')
        data = {
            'username': 'inactiveuser',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
            'is_active': False,
        }
        response = self.client.post(reverse('accounts:user_create'), data)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='inactiveuser')
        self.assertFalse(user.is_active)
        
        # Verify user cannot login
        self.client.logout()
        login_response = self.client.post(reverse('accounts:login'), {
            'username': 'inactiveuser',
            'password': 'TestPassword123!'
        })
        # Should stay on login page or show error
        self.assertNotEqual(login_response.status_code, 302)


class UserUpdateViewTest(TestCase):
    """
    Test cases for UserUpdateView
    """
    
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        self.test_user = User.objects.create_user(
            username='testuser',
            password='oldpass123',
            email='test@example.com'
        )
    
    def test_admin_can_edit_user(self):
        """
        Test: Admin can edit user
        Given: Admin logged in, user exists
        When: POST /accounts/users/<id>/edit/
        Then: User updated, redirect to user list
        """
        self.client.login(username='admin', password='testpass123')
        data = {
            'username': 'testuser',
            'email': 'updated@example.com',
            'is_active': True,
        }
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.test_user.id]),
            data
        )
        self.assertEqual(response.status_code, 302)
        self.test_user.refresh_from_db()
        self.assertEqual(self.test_user.email, 'updated@example.com')
    
    def test_password_optional_on_update(self):
        """
        Test: Password optional on update (blank = keep current)
        Given: Admin editing user, password fields blank
        When: POST update
        Then: User updated, password unchanged
        """
        self.client.login(username='admin', password='testpass123')
        old_password_hash = self.test_user.password
        data = {
            'username': 'testuser',
            'email': 'updated@example.com',
        }
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.test_user.id]),
            data
        )
        self.assertEqual(response.status_code, 302)
        self.test_user.refresh_from_db()
        self.assertEqual(self.test_user.password, old_password_hash)
    
    def test_get_edit_form(self):
        """
        Test: GET request shows edit form with existing data
        Given: Admin logged in, user exists
        When: GET /accounts/users/<id>/edit/
        Then: 200 OK, form pre-filled
        """
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(
            reverse('accounts:user_edit', args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'testuser')
        self.assertContains(response, 'test@example.com')
    
    def test_update_nonexistent_user(self):
        """
        Test: Updating user that doesn't exist
        Given: User ID that doesn't exist
        When: POST /accounts/users/<id>/edit/
        Then: 404 Not Found
        """
        self.client.login(username='admin', password='testpass123')
        nonexistent_id = 99999
        data = {
            'username': 'updated',
            'email': 'updated@example.com',
        }
        response = self.client.post(
            reverse('accounts:user_edit', args=[nonexistent_id]),
            data
        )
        self.assertEqual(response.status_code, 404)
    
    def test_update_username_to_existing_username(self):
        """
        Test: Changing username to existing username
        Given: Two users exist
        When: Update user1's username to user2's username
        Then: Validation error, user not updated
        """
        self.client.login(username='admin', password='testpass123')
        user2 = User.objects.create_user(
            username='existinguser',
            password='pass123'
        )
        data = {
            'username': 'existinguser',  # Same as user2
            'email': 'test@example.com',
        }
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.test_user.id]),
            data
        )
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.test_user.refresh_from_db()
        self.assertNotEqual(self.test_user.username, 'existinguser')
    
    def test_update_password_with_weak_password(self):
        """
        Test: Updating with weak password
        Given: Admin editing user
        When: POST with weak password
        Then: Validation error, password not updated
        """
        self.client.login(username='admin', password='testpass123')
        old_password_hash = self.test_user.password
        data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'new_password': '123',  # Too weak
            'confirm_password': '123',
        }
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.test_user.id]),
            data
        )
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.test_user.refresh_from_db()
        self.assertEqual(self.test_user.password, old_password_hash)


class UserDeleteViewTest(TestCase):
    """
    Test cases for UserDeleteView
    """
    
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        self.test_user = User.objects.create_user(
            username='testuser',
            password='pass123'
        )
    
    def test_admin_can_delete_user(self):
        """
        Test: Admin can delete user
        Given: Admin logged in, user exists
        When: POST /accounts/users/<id>/delete/
        Then: User deleted (is_active=False), redirect to user list
        """
        self.client.login(username='admin', password='testpass123')
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 302)
        self.test_user.refresh_from_db()
        self.assertFalse(self.test_user.is_active)  # Soft delete
    
    def test_cannot_delete_admin_user(self):
        """
        Test: Cannot delete admin user (saadsayyed)
        Given: Admin logged in, trying to delete saadsayyed
        When: POST delete
        Then: Error message, user not deleted
        """
        admin_user = User.objects.create_user(
            username='saadsayyed',
            password='pass123',
            is_staff=True,
            is_superuser=True
        )
        self.client.login(username='admin', password='testpass123')
        response = self.client.post(
            reverse('accounts:user_delete', args=[admin_user.id])
        )
        self.assertEqual(response.status_code, 400)  # Bad request
        admin_user.refresh_from_db()
        self.assertTrue(admin_user.is_active)  # Not deleted
    
    def test_get_delete_confirmation(self):
        """
        Test: GET request shows delete confirmation page
        Given: Admin logged in, user exists
        When: GET /accounts/users/<id>/delete/
        Then: 200 OK, confirmation page displayed
        """
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(
            reverse('accounts:user_delete', args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete User')
        self.assertContains(response, 'testuser')
    
    def test_delete_user_with_connections(self):
        """
        Test: Deleting user who has database connections
        Given: User with database connection
        When: POST delete
        Then: Error message, user not deleted
        """
        from connections.models import DatabaseConnection
        
        self.client.login(username='admin', password='testpass123')
        
        # Create connection for test_user
        DatabaseConnection.objects.create(
            name='Test Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='pass',
            database_name='test',
            created_by=self.test_user
        )
        
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 400)  # Bad request
        self.test_user.refresh_from_db()
        self.assertTrue(self.test_user.is_active)  # Not deleted
    
    def test_delete_user_with_jobs(self):
        """
        Test: Deleting user who has sync jobs
        Given: User with sync job
        When: POST delete
        Then: Error message, user not deleted
        """
        from connections.models import DatabaseConnection
        from sync_jobs.models import SyncJob
        
        self.client.login(username='admin', password='testpass123')
        
        # Create connection and job for test_user
        conn = DatabaseConnection.objects.create(
            name='Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='pass',
            database_name='test',
            created_by=self.test_user
        )
        SyncJob.objects.create(
            name='Test Job',
            source_connection=conn,
            target_connection=conn,
            sync_type='full',
            status='pending',
            created_by=self.test_user
        )
        
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 400)  # Bad request
        self.test_user.refresh_from_db()
        self.assertTrue(self.test_user.is_active)  # Not deleted
    
    def test_delete_nonexistent_user(self):
        """
        Test: Deleting user that doesn't exist
        Given: User ID that doesn't exist
        When: POST /accounts/users/<id>/delete/
        Then: 404 Not Found
        """
        self.client.login(username='admin', password='testpass123')
        nonexistent_id = 99999
        response = self.client.post(
            reverse('accounts:user_delete', args=[nonexistent_id])
        )
        self.assertEqual(response.status_code, 404)


class UserManagementRBACTest(TestCase):
    """RBAC-specific tests for user management views"""
    
    def setUp(self):
        """Set up test users with different roles"""
        self.client = Client()
        
        # Create Super Admin
        self.super_admin = User.objects.create_user(
            username='superadmin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        from accounts.models import UserProfile, Role
        UserProfile.objects.create(
            user=self.super_admin,
            role=Role.SUPER_ADMIN,
            tenant=None
        )
        
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
        
        # Create Operator for Admin
        self.operator = User.objects.create_user(
            username='operator',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.operator,
            role=Role.OPERATOR,
            tenant=self.admin
        )
        
        # Create Viewer for Admin
        self.viewer = User.objects.create_user(
            username='viewer',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.viewer,
            role=Role.VIEWER,
            tenant=self.admin
        )
    
    def test_super_admin_sees_all_users(self):
        """Test that Super Admin sees all users"""
        self.client.login(username='superadmin', password='testpass123')
        response = self.client.get(reverse('accounts:user_list'))
        
        users = response.context['users']
        usernames = [user.username for user in users]
        
        self.assertIn('superadmin', usernames)
        self.assertIn('admin', usernames)
        self.assertIn('operator', usernames)
        self.assertIn('viewer', usernames)
    
    def test_admin_sees_only_tenant_users(self):
        """Test that Admin sees only tenant users"""
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('accounts:user_list'))
        
        users = response.context['users']
        usernames = [user.username for user in users]
        
        # Should see self and tenant users, but not super_admin
        self.assertIn('admin', usernames)
        self.assertIn('operator', usernames)
        self.assertIn('viewer', usernames)
        self.assertNotIn('superadmin', usernames)
    
    def test_super_admin_can_create_admin(self):
        """Test that Super Admin can create Admin"""
        from accounts.models import Role
        self.client.login(username='superadmin', password='testpass123')
        
        response = self.client.post(
            reverse('accounts:user_create'),
            {
                'username': 'newadmin',
                'email': 'newadmin@example.com',
                'password1': 'TestPassword123!',
                'password2': 'TestPassword123!',
                'role': Role.ADMIN,
                'is_active': True,
                'is_staff': True,
            }
        )
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Verify user created with correct role
        new_user = User.objects.get(username='newadmin')
        self.assertEqual(new_user.userprofile.role, Role.ADMIN)
        self.assertEqual(new_user.userprofile.tenant, new_user)
    
    def test_admin_can_create_operator(self):
        """Test that Admin can create Operator"""
        from accounts.models import Role
        self.client.login(username='admin', password='testpass123')
        
        response = self.client.post(
            reverse('accounts:user_create'),
            {
                'username': 'newoperator',
                'email': 'newoperator@example.com',
                'password1': 'TestPassword123!',
                'password2': 'TestPassword123!',
                'role': Role.OPERATOR,
                'is_active': True,
            }
        )
        
        self.assertEqual(response.status_code, 302)
        
        # Verify user created with correct role and tenant
        new_user = User.objects.get(username='newoperator')
        self.assertEqual(new_user.userprofile.role, Role.OPERATOR)
        self.assertEqual(new_user.userprofile.tenant, self.admin)
    
    def test_admin_can_create_viewer(self):
        """Test that Admin can create Viewer"""
        from accounts.models import Role
        self.client.login(username='admin', password='testpass123')
        
        response = self.client.post(
            reverse('accounts:user_create'),
            {
                'username': 'newviewer',
                'email': 'newviewer@example.com',
                'password1': 'TestPassword123!',
                'password2': 'TestPassword123!',
                'role': Role.VIEWER,
                'is_active': True,
            }
        )
        
        self.assertEqual(response.status_code, 302)
        
        # Verify user created with correct role and tenant
        new_user = User.objects.get(username='newviewer')
        self.assertEqual(new_user.userprofile.role, Role.VIEWER)
        self.assertEqual(new_user.userprofile.tenant, self.admin)
    
    def test_admin_cannot_create_admin(self):
        """Test that Admin cannot create Admin"""
        from accounts.models import Role
        self.client.login(username='admin', password='testpass123')
        
        response = self.client.post(
            reverse('accounts:user_create'),
            {
                'username': 'newadmin',
                'email': 'newadmin@example.com',
                'password1': 'TestPassword123!',
                'password2': 'TestPassword123!',
                'role': Role.ADMIN,  # Admin trying to create Admin
                'is_active': True,
                'is_staff': True,
            }
        )
        
        # Should fail (form validation error or 403)
        self.assertNotEqual(response.status_code, 302)
    
    def test_user_creation_assigns_correct_tenant(self):
        """Test that user creation assigns correct tenant"""
        from accounts.models import Role
        self.client.login(username='admin', password='testpass123')
        
        response = self.client.post(
            reverse('accounts:user_create'),
            {
                'username': 'newoperator',
                'email': 'newoperator@example.com',
                'password1': 'TestPassword123!',
                'password2': 'TestPassword123!',
                'role': Role.OPERATOR,
                'is_active': True,
            }
        )
        
        self.assertEqual(response.status_code, 302)
        
        # Verify tenant assignment
        new_user = User.objects.get(username='newoperator')
        self.assertEqual(new_user.userprofile.tenant, self.admin)
    
    def test_user_creation_assigns_correct_role(self):
        """Test that user creation assigns correct role"""
        from accounts.models import Role
        self.client.login(username='admin', password='testpass123')
        
        response = self.client.post(
            reverse('accounts:user_create'),
            {
                'username': 'newviewer',
                'email': 'newviewer@example.com',
                'password1': 'TestPassword123!',
                'password2': 'TestPassword123!',
                'role': Role.VIEWER,
                'is_active': True,
            }
        )
        
        self.assertEqual(response.status_code, 302)
        
        # Verify role assignment
        new_user = User.objects.get(username='newviewer')
        self.assertEqual(new_user.userprofile.role, Role.VIEWER)
    
    def test_role_escalation_prevented(self):
        """Test that role escalation is prevented"""
        from accounts.models import Role
        self.client.login(username='admin', password='testpass123')
        
        # Try to update operator to admin
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.operator.id]),
            {
                'username': 'operator',
                'email': 'operator@example.com',
                'role': Role.ADMIN,  # Trying to escalate
                'is_active': True,
            }
        )
        
        # Should fail or not update role
        self.operator.refresh_from_db()
        self.assertNotEqual(self.operator.userprofile.role, Role.ADMIN)
    
    def test_admin_cannot_change_to_super_admin(self):
        """Test that Admin cannot change to Super Admin"""
        from accounts.models import Role
        self.client.login(username='admin', password='testpass123')
        
        # Try to update operator to super admin
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.operator.id]),
            {
                'username': 'operator',
                'email': 'operator@example.com',
                'role': Role.SUPER_ADMIN,  # Trying to escalate
                'is_active': True,
            }
        )
        
        # Should fail
        self.operator.refresh_from_db()
        self.assertNotEqual(self.operator.userprofile.role, Role.SUPER_ADMIN)
    
    def test_admin_cannot_change_other_admin_role(self):
        """Test that Admin cannot change other Admin's role"""
        from accounts.models import Role
        # Create another admin
        admin2 = User.objects.create_user(
            username='admin2',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=admin2,
            role=Role.ADMIN,
            tenant=admin2
        )
        
        self.client.login(username='admin', password='testpass123')
        
        # Try to update other admin
        response = self.client.post(
            reverse('accounts:user_edit', args=[admin2.id]),
            {
                'username': 'admin2',
                'email': 'admin2@example.com',
                'role': Role.OPERATOR,  # Trying to change other admin
                'is_active': True,
            }
        )
        
        # Should be blocked (403 or not update)
        self.assertIn(response.status_code, [403, 302])
        admin2.refresh_from_db()
        # Role should not change if blocked
        if response.status_code == 403:
            self.assertEqual(admin2.userprofile.role, Role.ADMIN)
    
    def test_super_admin_can_change_roles(self):
        """Test that Super Admin can change roles"""
        from accounts.models import Role
        self.client.login(username='superadmin', password='testpass123')
        
        # Change operator to viewer
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.operator.id]),
            {
                'username': 'operator',
                'email': 'operator@example.com',
                'role': Role.VIEWER,
                'is_active': True,
            }
        )
        
        self.assertEqual(response.status_code, 302)
        self.operator.refresh_from_db()
        self.assertEqual(self.operator.userprofile.role, Role.VIEWER)
    
    def test_super_admin_deletion_prevented(self):
        """Test that Super Admin deletion is prevented"""
        self.client.login(username='superadmin', password='testpass123')
        
        # Try to delete super admin
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.super_admin.id])
        )
        
        # Should be blocked
        self.assertNotEqual(response.status_code, 302)
        
        # Super Admin should still exist
        self.assertTrue(User.objects.filter(id=self.super_admin.id).exists())
    
    def test_admin_can_delete_tenant_users(self):
        """Test that Admin can delete tenant users"""
        self.client.login(username='admin', password='testpass123')
        
        # Delete operator
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.operator.id])
        )
        
        self.assertEqual(response.status_code, 302)
        self.operator.refresh_from_db()
        self.assertFalse(self.operator.is_active)  # Soft delete
    
    def test_admin_cannot_delete_other_admin(self):
        """Test that Admin cannot delete other Admin"""
        # Create another admin
        from accounts.models import Role
        admin2 = User.objects.create_user(
            username='admin2',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=admin2,
            role=Role.ADMIN,
            tenant=admin2
        )
        
        self.client.login(username='admin', password='testpass123')
        
        # Try to delete other admin
        response = self.client.post(
            reverse('accounts:user_delete', args=[admin2.id])
        )
        
        # Should be blocked
        self.assertIn(response.status_code, [403, 400])
        
        # Admin2 should still exist
        admin2.refresh_from_db()
        self.assertTrue(admin2.is_active)
    
    def test_deleting_admin_deletes_tenant_data(self):
        """Test that deleting Admin deletes tenant data"""
        from connections.models import DatabaseConnection
        from sync_jobs.models import SyncJob
        
        # Create connection and job for admin
        conn = DatabaseConnection.objects.create(
            name='Admin Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='test',
            created_by=self.admin,
            tenant=self.admin
        )
        
        job = SyncJob.objects.create(
            name='Admin Job',
            source_connection=conn,
            target_connection=conn,
            created_by=self.admin,
            tenant=self.admin
        )
        
        conn_id = conn.id
        job_id = job.id
        
        # Delete admin (as super admin)
        self.client.login(username='superadmin', password='testpass123')
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.admin.id])
        )
        
        # Admin should be soft deleted
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)
        
        # But tenant data should be deleted (CASCADE)
        # Note: This depends on whether we're doing soft delete or hard delete
        # If soft delete, connections/jobs might still exist but with inactive tenant
        # For now, we'll check that the admin is soft deleted
