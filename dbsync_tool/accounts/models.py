from django.db import models
from django.contrib.auth.models import User


class Role(models.TextChoices):
    """Role choices for RBAC system"""
    SUPER_ADMIN = 'super_admin', 'Super Admin'
    ADMIN = 'admin', 'Admin'
    OPERATOR = 'operator', 'Operator'
    VIEWER = 'viewer', 'Viewer'


class UserProfile(models.Model):
    """
    Extended user profile with role and tenant information
    One-to-one relationship with Django User model
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='userprofile',
        verbose_name='User'
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        db_index=True,
        help_text='User role in the system'
    )
    tenant = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='tenant_users',
        help_text='Admin user who owns this tenant (null for Super Admin)',
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_profiles'
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['tenant']),
            models.Index(fields=['role', 'tenant']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
    
    # Role check methods
    def is_super_admin(self):
        """Check if user is Super Admin"""
        return self.role == Role.SUPER_ADMIN
    
    def is_admin(self):
        """Check if user is Admin (tenant owner)"""
        return self.role == Role.ADMIN
    
    def is_operator(self):
        """Check if user is Operator"""
        return self.role == Role.OPERATOR
    
    def is_viewer(self):
        """Check if user is Viewer (read-only)"""
        return self.role == Role.VIEWER
    
    def get_tenant(self):
        """
        Get the tenant (Admin user) for this user
        Returns:
            User instance (Admin) or None (Super Admin)
        """
        if self.is_super_admin():
            return None
        if self.is_admin():
            return self.user
        return self.tenant
