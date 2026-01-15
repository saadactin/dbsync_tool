"""
User management service functions
"""
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError


def is_admin(user):
    """
    Check if user is an administrator
    
    Args:
        user: User instance
        
    Returns:
        bool: True if user is admin (staff or superuser)
    """
    if not user or not user.is_authenticated:
        return False
    return user.is_staff or user.is_superuser


def create_user(username, email, password, is_active=True, is_staff=False):
    """
    Create a new user with validation
    
    Args:
        username: str (required, unique, max 150)
        email: str (optional, valid email format)
        password: str (required, must pass Django validators)
        is_active: bool (default: True)
        is_staff: bool (default: False)
        
    Returns:
        User: Created user object
        
    Raises:
        ValidationError: Invalid input data
        IntegrityError: Username already exists
    """
    try:
        user = User.objects.create_user(
            username=username,
            email=email or '',
            password=password,
            is_active=is_active,
            is_staff=is_staff
        )
        return user
    except IntegrityError as e:
        raise IntegrityError(f"Username '{username}' already exists") from e
    except Exception as e:
        raise ValidationError(f"Error creating user: {str(e)}") from e


def can_delete_user(user):
    """
    Check if a user can be deleted
    
    Args:
        user: User object to check
        
    Returns:
        tuple[bool, str]: (can_delete, reason)
    """
    from connections.models import DatabaseConnection
    from sync_jobs.models import SyncJob
    
    # Cannot delete admin user (saadsayyed)
    if user.username == 'saadsayyed':
        return False, "Cannot delete the admin user (saadsayyed)"
    
    # Check for related connections
    if DatabaseConnection.objects.filter(created_by=user).exists():
        return False, "User has database connections. Cannot delete."
    
    # Check for related sync jobs
    if SyncJob.objects.filter(created_by=user).exists():
        return False, "User has sync jobs. Cannot delete."
    
    return True, ""

