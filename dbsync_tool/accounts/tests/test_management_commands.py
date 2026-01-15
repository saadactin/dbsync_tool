"""
Test cases for create_admin_user management command
"""
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth.models import User
from io import StringIO
import os


class CreateAdminUserCommandTest(TestCase):
    """
    Test cases for create_admin_user management command
    """
    
    def test_creates_admin_user_successfully(self):
        """
        Test: Command creates admin user with correct attributes
        Given: No admin user exists
        When: Command run with password
        Then: User created with username='saadsayyed', is_staff=True, is_superuser=True
        """
        # Arrange
        password = 'TestPassword123!'
        
        # Act
        call_command('create_admin_user', '--password', password)
        
        # Assert
        user = User.objects.get(username='saadsayyed')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(password))
    
    def test_command_idempotent(self):
        """
        Test: Command is idempotent (safe to run multiple times)
        Given: Admin user already exists
        When: Command run again
        Then: Warning shown, user not recreated
        """
        # Arrange
        password = 'TestPassword123!'
        call_command('create_admin_user', '--password', password)
        initial_user = User.objects.get(username='saadsayyed')
        initial_user_id = initial_user.id
        
        # Act
        out = StringIO()
        call_command('create_admin_user', '--password', password, stdout=out)
        
        # Assert
        self.assertIn('already exists', out.getvalue())
        user = User.objects.get(username='saadsayyed')
        self.assertEqual(user.id, initial_user_id)  # Same user, not recreated
    
    def test_password_required(self):
        """
        Test: Command requires password
        Given: No password provided (no --password, no env var)
        When: Command run
        Then: Error shown, command exits with error
        """
        # Arrange & Act
        # Clear env var if it exists
        if 'ADMIN_PASSWORD' in os.environ:
            del os.environ['ADMIN_PASSWORD']
        
        with self.assertRaises(SystemExit):
            call_command('create_admin_user')
    
    def test_uses_environment_variable(self):
        """
        Test: Command uses ADMIN_PASSWORD environment variable
        Given: ADMIN_PASSWORD env var set
        When: Command run without --password
        Then: User created with env var password
        """
        # Arrange
        password = 'EnvPassword123!'
        os.environ['ADMIN_PASSWORD'] = password
        
        try:
            # Act
            call_command('create_admin_user')
            
            # Assert
            user = User.objects.get(username='saadsayyed')
            self.assertTrue(user.check_password(password))
        finally:
            # Cleanup
            if 'ADMIN_PASSWORD' in os.environ:
                del os.environ['ADMIN_PASSWORD']
    
    def test_custom_email(self):
        """
        Test: Command accepts custom email
        Given: --email flag provided
        When: Command run
        Then: User created with custom email
        """
        # Arrange
        password = 'TestPassword123!'
        email = 'custom@example.com'
        
        # Act
        call_command('create_admin_user', '--password', password, '--email', email)
        
        # Assert
        user = User.objects.get(username='saadsayyed')
        self.assertEqual(user.email, email)
    
    def test_admin_user_has_correct_permissions(self):
        """
        Test: Admin user has is_staff=True and is_superuser=True
        Given: Command creates admin user
        When: User is created
        Then: User has correct permissions
        """
        # Arrange
        password = 'TestPassword123!'
        
        # Act
        call_command('create_admin_user', '--password', password)
        
        # Assert
        user = User.objects.get(username='saadsayyed')
        self.assertTrue(user.is_staff, "Admin user should have is_staff=True")
        self.assertTrue(user.is_superuser, "Admin user should have is_superuser=True")
        self.assertTrue(user.is_active, "Admin user should be active")

