from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib.auth.models import User
from django.utils import timezone
import logging
from accounts.models import UserProfile, Role

logger = logging.getLogger('accounts.permissions')

class RoleRequiredMixin:
    """
    Base mixin to restrict access based on user role
    Subclasses should define allowed_roles list
    """
    allowed_roles = []
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            logger.info(
                'Unauthenticated access attempt',
                extra={
                    'event_type': 'access_unauthenticated',
                    'path': request.path,
                    'method': request.method,
                    'ip_address': self._get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            return redirect('accounts:login')
        
        try:
            profile = request.user.userprofile
            if profile.role not in self.allowed_roles:
                logger.warning(
                    'Access denied: Insufficient role',
                    extra={
                        'event_type': 'access_denied_role',
                        'user_id': request.user.id,
                        'username': request.user.username,
                        'user_role': profile.role,
                        'required_roles': self.allowed_roles,
                        'path': request.path,
                        'method': request.method,
                        'ip_address': self._get_client_ip(request),
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                raise PermissionDenied(
                    f"Access denied. Required roles: {', '.join([Role(r).label for r in self.allowed_roles])}"
                )
        except UserProfile.DoesNotExist:
            logger.error(
                'Access denied: Missing UserProfile',
                extra={
                    'event_type': 'access_denied_no_profile',
                    'user_id': request.user.id,
                    'username': request.user.username,
                    'path': request.path,
                    'method': request.method,
                    'ip_address': self._get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            raise PermissionDenied("User profile not found. Please contact administrator.")
        
        return super().dispatch(request, *args, **kwargs)

class SuperAdminRequiredMixin(RoleRequiredMixin):
    """Only Super Admin can access"""
    allowed_roles = [Role.SUPER_ADMIN]

class AdminOrSuperAdminMixin(RoleRequiredMixin):
    """Admin or Super Admin can access"""
    allowed_roles = [Role.SUPER_ADMIN, Role.ADMIN]

class OperatorOrAboveMixin(RoleRequiredMixin):
    """Operator, Admin, or Super Admin can access"""
    allowed_roles = [Role.SUPER_ADMIN, Role.ADMIN, Role.OPERATOR]

class ViewerReadOnlyMixin:
    """
    Prevent Viewer from accessing write operations (POST, PUT, DELETE)
    Should be combined with RoleRequiredMixin
    """
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            try:
                profile = request.user.userprofile
                if profile.is_viewer() and request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
                    logger.warning(
                        'Viewer attempted write operation',
                        extra={
                            'event_type': 'viewer_write_blocked',
                            'user_id': request.user.id,
                            'username': request.user.username,
                            'method': request.method,
                            'path': request.path,
                            'ip_address': self._get_client_ip(request),
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    raise PermissionDenied("Viewers have read-only access. This operation is not allowed.")
            except UserProfile.DoesNotExist:
                pass  # Let RoleRequiredMixin handle it
        
        return super().dispatch(request, *args, **kwargs)

