"""
Mixin classes for user management
"""
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
import logging
from .services import is_admin
from .permissions import (
    RoleRequiredMixin,
    SuperAdminRequiredMixin,
    AdminOrSuperAdminMixin,
    OperatorOrAboveMixin,
    ViewerReadOnlyMixin
)

logger = logging.getLogger(__name__)

# Keep existing mixin for backward compatibility
class AdminRequiredMixin:
    """
    Mixin to restrict access to admin users only
    Raises PermissionDenied if user is not admin
    DEPRECATED: Use AdminOrSuperAdminMixin instead
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        
        if not is_admin(request.user):
            logger.warning(
                f'Unauthorized access attempt to admin-only page by user: {request.user.username}',
                extra={
                    'username': request.user.username,
                    'path': request.path,
                    'method': request.method
                }
            )
            raise PermissionDenied("Only administrators can access this page.")
        
        return super().dispatch(request, *args, **kwargs)

# Export new mixins
__all__ = [
    'AdminRequiredMixin',  # Keep for backward compatibility
    'RoleRequiredMixin',
    'SuperAdminRequiredMixin',
    'AdminOrSuperAdminMixin',
    'OperatorOrAboveMixin',
    'ViewerReadOnlyMixin',
]

