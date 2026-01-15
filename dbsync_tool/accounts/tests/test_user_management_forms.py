"""
Test cases for user management forms
"""
from django.test import TestCase
from django.contrib.auth.models import User
from accounts.forms import UserCreateForm, UserUpdateForm


class UserCreateFormTest(TestCase):
    """
    Test cases for UserCreateForm
    """
    
    def test_valid_form(self):
        """Test form with valid data"""
        form_data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
            'is_active': True,
        }
        form = UserCreateForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_password_mismatch(self):
        """Test form with mismatched passwords"""
        form_data = {
            'username': 'newuser',
            'password1': 'Password123!',
            'password2': 'DifferentPassword123!',
        }
        form = UserCreateForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('password2', form.errors)
    
    def test_username_uniqueness(self):
        """Test form with duplicate username"""
        User.objects.create_user(username='existing', password='pass123')
        form_data = {
            'username': 'existing',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
        }
        form = UserCreateForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
    
    def test_form_saves_user(self):
        """Test that form.save() creates a user"""
        form_data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
            'is_active': True,
            'is_staff': True,
        }
        form = UserCreateForm(data=form_data)
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.username, 'newuser')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_active)


class UserUpdateFormTest(TestCase):
    """
    Test cases for UserUpdateForm
    """
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='oldpass123'
        )
    
    def test_valid_form(self):
        """Test form with valid data"""
        form_data = {
            'username': 'testuser',
            'email': 'updated@example.com',
            'is_active': True,
        }
        form = UserUpdateForm(instance=self.user, data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_password_optional(self):
        """Test form without password (should keep current)"""
        form_data = {
            'username': 'testuser',
            'email': 'updated@example.com',
        }
        form = UserUpdateForm(instance=self.user, data=form_data)
        self.assertTrue(form.is_valid())
        old_password = self.user.password
        user = form.save()
        self.assertEqual(user.password, old_password)  # Password unchanged
    
    def test_password_update(self):
        """Test form with new password"""
        form_data = {
            'username': 'testuser',
            'email': 'updated@example.com',
            'new_password': 'NewPassword123!',
            'confirm_password': 'NewPassword123!',
        }
        form = UserUpdateForm(instance=self.user, data=form_data)
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertTrue(user.check_password('NewPassword123!'))
    
    def test_password_mismatch(self):
        """Test form with mismatched passwords"""
        form_data = {
            'username': 'testuser',
            'email': 'updated@example.com',
            'new_password': 'NewPassword123!',
            'confirm_password': 'DifferentPassword123!',
        }
        form = UserUpdateForm(instance=self.user, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)  # Non-field error
    
    def test_username_uniqueness(self):
        """Test form with duplicate username (excluding current user)"""
        User.objects.create_user(username='existing', password='pass123')
        form_data = {
            'username': 'existing',
            'email': 'updated@example.com',
        }
        form = UserUpdateForm(instance=self.user, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
    
    def test_email_optional(self):
        """Test email field is optional"""
        form_data = {
            'username': 'testuser',
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
        }
        form = UserCreateForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_username_too_long(self):
        """Test username max length (150 chars)"""
        long_username = 'a' * 151  # Exceeds max length
        form_data = {
            'username': long_username,
            'password1': 'TestPassword123!',
            'password2': 'TestPassword123!',
        }
        form = UserCreateForm(data=form_data)
        self.assertFalse(form.is_valid())

