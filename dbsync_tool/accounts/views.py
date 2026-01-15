from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib import messages
from django.views import View
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
import logging
from django.utils import timezone
from .forms import LoginForm, UserCreateForm, UserUpdateForm
from .mixins import AdminOrSuperAdminMixin
from .services import can_delete_user
from .models import UserProfile, Role
from .services.tenant_service import TenantService
from django.db.models import Q
from django.core.exceptions import PermissionDenied

logger = logging.getLogger('accounts.views')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    
    def get_client_ip(request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip
    
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            ip_address = get_client_ip(request)
            
            # Check rate limiting for failed login attempts
            from django.core.cache import cache
            login_attempt_key = f"login_attempts:{username}:{ip_address}"
            failed_attempts = cache.get(login_attempt_key, 0)
            
            if failed_attempts >= 5:
                retry_after = cache.ttl(login_attempt_key) or 900
                from core.audit import AuditLogger
                AuditLogger.log_security_event(
                    'rate_limit_exceeded',
                    'high',
                    f'Too many failed login attempts for {username}',
                    ip_address=ip_address
                )
                messages.error(
                    request,
                    f'Too many failed login attempts. Please try again in {retry_after // 60} minutes.'
                )
                return render(request, 'accounts/login.html', {'form': form})
            
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if user.is_active:
                    # Successful login - clear failed attempts
                    cache.delete(login_attempt_key)
                    login(request, user)
                    
                    # Audit log
                    from core.audit import AuditLogger
                    AuditLogger.log_authentication_event(
                        'login',
                        username,
                        success=True,
                        ip_address=ip_address
                    )
                    
                    messages.success(request, f'Welcome back, {user.username}!')
                    next_url = request.GET.get('next')
                    if next_url:
                        return redirect(next_url)
                    return redirect('core:dashboard')
                else:
                    # Account inactive
                    cache.set(login_attempt_key, failed_attempts + 1, 900)  # 15 minutes
                    from core.audit import AuditLogger
                    AuditLogger.log_authentication_event(
                        'login',
                        username,
                        success=False,
                        ip_address=ip_address,
                        details={'reason': 'account_inactive'}
                    )
                    messages.error(request, 'Account is inactive. Please contact administrator.')
            else:
                # Invalid credentials
                cache.set(login_attempt_key, failed_attempts + 1, 900)  # 15 minutes
                from core.audit import AuditLogger
                AuditLogger.log_authentication_event(
                    'login',
                    username,
                    success=False,
                    ip_address=ip_address,
                    details={'reason': 'invalid_credentials'}
                )
                messages.error(request, 'Wrong credentials. Please check your username and password.')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = LoginForm()
    
    return render(request, 'accounts/login.html', {'form': form})

@login_required
def logout_view(request):
    from django.contrib.auth import logout
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('accounts:login')

@login_required
def profile_view(request):
    """Display user profile information"""
    context = {
        'user': request.user,
        'page_title': 'My Profile'
    }
    return render(request, 'accounts/profile.html', context)

@login_required
def change_password_view(request):
    """Allow users to change their password"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Important!
            messages.success(request, 'Your password was successfully updated!')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(request.user)
    
    # Add Bootstrap classes to form fields
    for field in form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})
    
    return render(request, 'accounts/change_password.html', {'form': form})


class UserListView(AdminOrSuperAdminMixin, View):
    """
    List all users (Admin or Super Admin only)
    Super Admin sees all users, Admin sees only tenant users
    """
    template_name = 'accounts/user_list.html'
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get(self, request):
        logger.info(
            'User list accessed',
            extra={
                'event_type': 'user_list_accessed',
                'user_id': request.user.id,
                'username': request.user.username,
                'user_role': request.user.userprofile.role,
                'ip_address': self._get_client_ip(request),
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        # Base queryset with select_related for performance
        users = User.objects.select_related('userprofile').all()
        
        # Filter based on role
        profile = request.user.userprofile
        if profile.is_admin():
            # Admin sees only their tenant users
            users = users.filter(
                Q(pk=request.user.pk) |  # Self
                Q(userprofile__tenant=request.user)  # Tenant users
            )
        # Super Admin sees all (no filtering)
        
        users = users.order_by('-date_joined')
        
        # Pagination (20 per page)
        paginator = Paginator(users, 20)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        context = {
            'users': page_obj,
            'page_obj': page_obj,
            'is_paginated': paginator.num_pages > 1,
            'user_role': profile.role,  # For template display
        }
        return render(request, self.template_name, context)


class UserCreateView(AdminOrSuperAdminMixin, View):
    """
    Create new user (Admin or Super Admin only)
    Role assignment based on creator's role
    """
    template_name = 'accounts/user_form.html'
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get(self, request):
        form = UserCreateForm(user=request.user)  # Pass user for role restrictions
        context = {
            'form': form,
            'form_title': 'Create User',
            'submit_button': 'Create User',
            'user_role': request.user.userprofile.role,
        }
        return render(request, self.template_name, context)
    
    def post(self, request):
        form = UserCreateForm(request.POST, user=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            
            # Get creator's profile
            creator_profile = request.user.userprofile
            
            # Determine role and tenant based on creator
            if creator_profile.is_super_admin():
                # Super Admin can create Admin, Operator, Viewer
                role = form.cleaned_data.get('role', Role.VIEWER)
                if role == Role.ADMIN:
                    tenant = None  # Will be set to user after creation
                else:
                    tenant = None  # Will be assigned later
            elif creator_profile.is_admin():
                # Admin can only create Operator, Viewer
                role = form.cleaned_data.get('role', Role.VIEWER)
                if role not in [Role.OPERATOR, Role.VIEWER]:
                    messages.error(
                        request,
                        'You can only create Operator or Viewer users.'
                    )
                    context = {
                        'form': form,
                        'form_title': 'Create User',
                        'submit_button': 'Create User',
                    }
                    return render(request, self.template_name, context)
                tenant = request.user  # Admin is the tenant
            else:
                messages.error(request, 'You do not have permission to create users.')
                return redirect('accounts:user_list')
            
            # Save user
            user.save()
            
            # Create or update UserProfile
            profile, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': role,
                    'tenant': tenant if role != Role.ADMIN else user
                }
            )
            if not created:
                profile.role = role
                profile.tenant = tenant if role != Role.ADMIN else user
                profile.save()
            
            # If Admin, set tenant to self
            if role == Role.ADMIN:
                profile.tenant = user
                profile.save()
            
            logger.info(
                'User created',
                extra={
                    'event_type': 'user_created',
                    'created_user_id': user.id,
                    'created_username': user.username,
                    'created_user_email': user.email,
                    'role': role,
                    'tenant_id': profile.tenant.id if profile.tenant else None,
                    'tenant_username': profile.tenant.username if profile.tenant else None,
                    'created_by_id': request.user.id,
                    'created_by_username': request.user.username,
                    'created_by_role': request.user.userprofile.role,
                    'timestamp': timezone.now().isoformat(),
                    'ip_address': self._get_client_ip(request),
                }
            )
            messages.success(request, f'User "{user.username}" created successfully.')
            return redirect('accounts:user_list')
        else:
            logger.warning(
                'User creation failed',
                extra={
                    'event_type': 'user_creation_failed',
                    'created_by_id': request.user.id,
                    'created_by_username': request.user.username,
                    'errors': form.errors,
                    'timestamp': timezone.now().isoformat(),
                    'ip_address': self._get_client_ip(request),
                }
            )
            messages.error(request, 'Please correct the errors below.')
            context = {
                'form': form,
                'form_title': 'Create User',
                'submit_button': 'Create User',
            }
            return render(request, self.template_name, context)


class UserUpdateView(AdminOrSuperAdminMixin, View):
    """
    Update existing user (Admin or Super Admin only)
    Prevent role escalation, protect Super Admin
    """
    template_name = 'accounts/user_form.html'
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        
        # Check tenant ownership (Admin can only update tenant users)
        profile = request.user.userprofile
        if profile.is_admin():
            target_profile = user.userprofile
            if target_profile.tenant != request.user and user != request.user:
                raise PermissionDenied("You can only update users in your tenant.")
        
        form = UserUpdateForm(instance=user, user=request.user)
        context = {
            'form': form,
            'user': user,
            'form_title': 'Edit User',
            'submit_button': 'Update User',
            'user_role': profile.role,
        }
        return render(request, self.template_name, context)
    
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        
        # Check tenant ownership
        profile = request.user.userprofile
        if profile.is_admin():
            target_profile = user.userprofile
            if target_profile.tenant != request.user and user != request.user:
                raise PermissionDenied("You can only update users in your tenant.")
        
        form = UserUpdateForm(request.POST, instance=user, user=request.user)
        if form.is_valid():
            # Enhanced role escalation prevention
            new_role = form.cleaned_data.get('role')
            if new_role:
                creator_profile = request.user.userprofile
                target_profile = user.userprofile
                
                # Security check 1: Protect Super Admin
                if target_profile.is_super_admin() and new_role != Role.SUPER_ADMIN:
                    logger.warning(
                        'Role escalation attempt: Super Admin role change',
                        extra={
                            'event_type': 'role_escalation_blocked',
                            'user_id': request.user.id,
                            'username': request.user.username,
                            'target_user_id': user.id,
                            'target_username': user.username,
                            'attempted_role': new_role,
                            'current_role': target_profile.role,
                            'ip_address': self._get_client_ip(request),
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    messages.error(request, 'Super Admin role cannot be changed.')
                    context = {
                        'form': form,
                        'user': user,
                        'form_title': 'Edit User',
                        'submit_button': 'Update User',
                    }
                    return render(request, self.template_name, context)
                
                # Security check 2: Prevent Admin from escalating to Super Admin
                if creator_profile.is_admin() and new_role == Role.SUPER_ADMIN:
                    logger.warning(
                        'Role escalation attempt: Admin to Super Admin',
                        extra={
                            'event_type': 'role_escalation_blocked',
                            'user_id': request.user.id,
                            'username': request.user.username,
                            'target_user_id': user.id,
                            'target_username': user.username,
                            'attempted_role': new_role,
                            'current_role': target_profile.role,
                            'ip_address': self._get_client_ip(request),
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    messages.error(request, 'You cannot assign Super Admin role.')
                    context = {
                        'form': form,
                        'user': user,
                        'form_title': 'Edit User',
                        'submit_button': 'Update User',
                    }
                    return render(request, self.template_name, context)
                
                # Security check 3: Prevent Admin from creating/changing other Admins
                if creator_profile.is_admin() and new_role == Role.ADMIN and user != request.user:
                    logger.warning(
                        'Role escalation attempt: Admin creating/changing other Admin',
                        extra={
                            'event_type': 'role_escalation_blocked',
                            'user_id': request.user.id,
                            'username': request.user.username,
                            'target_user_id': user.id,
                            'target_username': user.username,
                            'attempted_role': new_role,
                            'current_role': target_profile.role,
                            'ip_address': self._get_client_ip(request),
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    messages.error(request, 'You cannot assign Admin role to other users.')
                    context = {
                        'form': form,
                        'user': user,
                        'form_title': 'Edit User',
                        'submit_button': 'Update User',
                    }
                    return render(request, self.template_name, context)
                
                # Security check 4: Prevent self-escalation
                if user == request.user and new_role in [Role.SUPER_ADMIN, Role.ADMIN] and not creator_profile.is_super_admin():
                    logger.warning(
                        'Role escalation attempt: Self-escalation',
                        extra={
                            'event_type': 'role_escalation_blocked',
                            'user_id': request.user.id,
                            'username': request.user.username,
                            'attempted_role': new_role,
                            'current_role': target_profile.role,
                            'ip_address': self._get_client_ip(request),
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    messages.error(request, 'You cannot change your own role to Super Admin or Admin.')
                    context = {
                        'form': form,
                        'user': user,
                        'form_title': 'Edit User',
                        'submit_button': 'Update User',
                    }
                    return render(request, self.template_name, context)
                
                # All checks passed, update role
                old_role = target_profile.role
                target_profile.role = new_role
                target_profile.save()
                
                if old_role != new_role:
                    logger.info(
                        'Role changed',
                        extra={
                            'event_type': 'role_changed',
                            'target_user_id': user.id,
                            'target_username': user.username,
                            'old_role': old_role,
                            'new_role': new_role,
                            'changed_by_id': request.user.id,
                            'changed_by_username': request.user.username,
                            'timestamp': timezone.now().isoformat(),
                            'ip_address': self._get_client_ip(request),
                        }
                    )
            
            password_changed = bool(form.cleaned_data.get('new_password'))
            user = form.save()
            
            logger.info(
                'User updated',
                extra={
                    'event_type': 'user_updated',
                    'updated_user_id': user.id,
                    'updated_username': user.username,
                    'password_changed': password_changed,
                    'role': target_profile.role if new_role else None,
                    'updated_by_id': request.user.id,
                    'updated_by_username': request.user.username,
                    'timestamp': timezone.now().isoformat(),
                    'ip_address': self._get_client_ip(request),
                }
            )
            messages.success(request, f'User "{user.username}" updated successfully.')
            return redirect('accounts:user_list')
        else:
            logger.warning(
                'User update failed',
                extra={
                    'event_type': 'user_update_failed',
                    'user_id': pk,
                    'errors': form.errors,
                    'updated_by_id': request.user.id,
                    'updated_by_username': request.user.username,
                    'timestamp': timezone.now().isoformat(),
                    'ip_address': self._get_client_ip(request),
                }
            )
            messages.error(request, 'Please correct the errors below.')
            context = {
                'form': form,
                'user': user,
                'form_title': 'Edit User',
                'submit_button': 'Update User',
            }
            return render(request, self.template_name, context)


class UserDeleteView(AdminOrSuperAdminMixin, View):
    """
    Delete user (Admin or Super Admin only)
    Prevent Super Admin deletion, protect Admins with tenant users
    """
    template_name = 'accounts/user_confirm_delete.html'
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        
        # Check tenant ownership
        profile = request.user.userprofile
        if profile.is_admin():
            target_profile = user.userprofile
            if target_profile.tenant != request.user and user != request.user:
                raise PermissionDenied("You can only delete users in your tenant.")
        
        can_delete, reason = self._can_delete_user(user)
        context = {
            'user': user,
            'can_delete': can_delete,
            'reason': reason,
        }
        return render(request, self.template_name, context)
    
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        
        # Check tenant ownership
        profile = request.user.userprofile
        if profile.is_admin():
            target_profile = user.userprofile
            if target_profile.tenant != request.user and user != request.user:
                raise PermissionDenied("You can only delete users in your tenant.")
        
        can_delete, reason = self._can_delete_user(user)
        
        if not can_delete:
            # User-friendly error messages
            if 'Super Admin' in reason:
                error_message = 'Super Admin users cannot be deleted. This is a security measure to ensure system administration is always available.'
            elif 'tenant users' in reason.lower():
                tenant_count = reason.split()[-2] if reason.split()[-2].isdigit() else 'some'
                error_message = f'Cannot delete this Admin user because they have {tenant_count} users in their tenant. Please reassign or delete those users first.'
            else:
                error_message = reason
            
            logger.warning(
                'User deletion blocked',
                extra={
                    'event_type': 'user_deletion_blocked',
                    'user_id': pk,
                    'username': user.username,
                    'reason': reason,
                    'deleted_by_id': request.user.id,
                    'deleted_by_username': request.user.username,
                    'timestamp': timezone.now().isoformat(),
                    'ip_address': self._get_client_ip(request),
                }
            )
            messages.error(request, error_message)
            return redirect('accounts:user_list')
        
        # Soft delete: set is_active=False
        user.is_active = False
        user.save()
        
        logger.info(
            'User deleted',
            extra={
                'event_type': 'user_deleted',
                'deleted_user_id': user.id,
                'deleted_username': user.username,
                'deleted_user_role': user.userprofile.role,
                'deleted_by_id': request.user.id,
                'deleted_by_username': request.user.username,
                'timestamp': timezone.now().isoformat(),
                'ip_address': self._get_client_ip(request),
            }
        )
        messages.success(request, f'User "{user.username}" deleted successfully.')
        return redirect('accounts:user_list')
    
    def _can_delete_user(self, user):
        """Enhanced check if user can be deleted"""
        profile = user.userprofile
        
        # Security check 1: Prevent Super Admin deletion
        if profile.is_super_admin():
            logger.warning(
                'Super Admin deletion attempt blocked',
                extra={
                    'event_type': 'super_admin_deletion_blocked',
                    'target_user_id': user.id,
                    'target_username': user.username,
                    'attempted_by_id': getattr(self.request, 'user', None).id if hasattr(self, 'request') else None,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            return False, "Super Admin cannot be deleted."
        
        # Security check 2: Prevent deletion if last Super Admin
        if profile.is_super_admin():
            super_admin_count = UserProfile.objects.filter(role=Role.SUPER_ADMIN).count()
            if super_admin_count <= 1:
                logger.warning(
                    'Last Super Admin deletion attempt blocked',
                    extra={
                        'event_type': 'last_super_admin_deletion_blocked',
                        'target_user_id': user.id,
                        'target_username': user.username,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return False, "Cannot delete the last Super Admin. At least one Super Admin must exist."
        
        # Security check 3: Prevent Admin deletion if they have tenant users
        if profile.is_admin():
            tenant_users = UserProfile.objects.filter(tenant=user).exclude(user=user)
            if tenant_users.exists():
                logger.warning(
                    'Admin with tenant users deletion attempt blocked',
                    extra={
                        'event_type': 'admin_with_tenants_deletion_blocked',
                        'target_user_id': user.id,
                        'target_username': user.username,
                        'tenant_user_count': tenant_users.count(),
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return False, f"Cannot delete Admin. {tenant_users.count()} users belong to this tenant."
        
        return True, None
