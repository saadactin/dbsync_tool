from django.db import models
from django.contrib.auth.models import User
from accounts.models import UserProfile, Role
import logging

logger = logging.getLogger('accounts.services')

class TenantService:
    """
    Centralized service for tenant-based query filtering and tenant management
    All tenant-related logic should go through this service
    """
    
    @staticmethod
    def get_queryset_for_user(qs, user):
        """
        Filter queryset based on user's role and tenant
        
        Rules:
        - Super Admin: No filtering (sees everything)
        - Admin: Filter by tenant=self
        - Operator/Viewer: Filter by tenant=profile.tenant
        
        Args:
            qs: Django QuerySet (must have 'tenant' field)
            user: User instance (must be authenticated)
            
        Returns:
            Filtered QuerySet
            
        Raises:
            None (always returns valid queryset, may be empty)
        """
        if not user or not user.is_authenticated:
            logger.debug(
                'Unauthenticated user attempted query',
                extra={
                    'event_type': 'query_unauthenticated',
                    'model': qs.model.__name__ if hasattr(qs, 'model') else 'Unknown',
                }
            )
            return qs.none()
        
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            # Profile should always exist (signal creates it)
            # But handle gracefully for safety
            logger.warning(
                'UserProfile missing for query',
                extra={
                    'event_type': 'query_missing_profile',
                    'user_id': user.id,
                    'username': user.username,
                    'model': qs.model.__name__ if hasattr(qs, 'model') else 'Unknown',
                }
            )
            return qs.none()
        
        # Log query filtering
        original_count = qs.count()
        
        # Super Admin sees everything
        if profile.is_super_admin():
            filtered_qs = qs
            logger.debug(
                'Super Admin query (no filtering)',
                extra={
                    'event_type': 'query_super_admin',
                    'user_id': user.id,
                    'username': user.username,
                    'model': qs.model.__name__ if hasattr(qs, 'model') else 'Unknown',
                    'result_count': filtered_qs.count(),
                }
            )
            return filtered_qs
        
        # Admin sees only their tenant data
        if profile.is_admin():
            filtered_qs = qs.filter(tenant=user)
            logger.debug(
                'Admin query filtered by tenant',
                extra={
                    'event_type': 'query_admin',
                    'user_id': user.id,
                    'username': user.username,
                    'tenant_id': user.id,
                    'model': qs.model.__name__ if hasattr(qs, 'model') else 'Unknown',
                    'original_count': original_count,
                    'filtered_count': filtered_qs.count(),
                }
            )
            return filtered_qs
        
        # Operator/Viewer see only their tenant's data
        if profile.tenant:
            filtered_qs = qs.filter(tenant=profile.tenant)
            logger.debug(
                'Operator/Viewer query filtered by tenant',
                extra={
                    'event_type': 'query_operator_viewer',
                    'user_id': user.id,
                    'username': user.username,
                    'user_role': profile.role,
                    'tenant_id': profile.tenant.id,
                    'tenant_username': profile.tenant.username,
                    'model': qs.model.__name__ if hasattr(qs, 'model') else 'Unknown',
                    'original_count': original_count,
                    'filtered_count': filtered_qs.count(),
                }
            )
            return filtered_qs
        
        # Fallback: no tenant assigned (shouldn't happen)
        logger.warning(
            'Query with no tenant assigned',
            extra={
                'event_type': 'query_no_tenant',
                'user_id': user.id,
                'username': user.username,
                'role': profile.role,
                'model': qs.model.__name__ if hasattr(qs, 'model') else 'Unknown',
            }
        )
        return qs.none()
    
    @staticmethod
    def get_user_tenant(user):
        """
        Get the tenant (Admin user) for a given user
        
        Args:
            user: User instance
            
        Returns:
            User instance (Admin) or None (Super Admin)
        """
        if not user or not user.is_authenticated:
            return None
        
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            return None
        
        if profile.is_super_admin():
            return None
        if profile.is_admin():
            return user
        return profile.tenant
    
    @staticmethod
    def can_user_manage_tenant(user, target_tenant):
        """
        Check if user can manage a specific tenant
        
        Args:
            user: User instance (the one trying to manage)
            target_tenant: User instance (the tenant to manage)
            
        Returns:
            bool: True if user can manage target_tenant
        """
        if not user or not user.is_authenticated:
            return False
        
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            return False
        
        # Super Admin can manage all tenants
        if profile.is_super_admin():
            return True
        
        # Admin can only manage themselves
        if profile.is_admin() and target_tenant == user:
            return True
        
        return False
    
    @staticmethod
    def get_tenant_users(tenant_admin):
        """
        Get all users belonging to a tenant (Admin + Operators + Viewers)
        
        Args:
            tenant_admin: User instance (Admin user)
            
        Returns:
            QuerySet of User instances
        """
        from django.contrib.auth.models import User
        
        return User.objects.filter(
            models.Q(pk=tenant_admin.pk) |  # Include Admin themselves
            models.Q(userprofile__tenant=tenant_admin)
        )

