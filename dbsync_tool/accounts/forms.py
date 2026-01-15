from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.cache import cache
from accounts.models import Role
from core.sanitization import sanitize_username


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        min_length=3,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username',
            'required': True,
            'autocomplete': 'username'
        }),
        help_text="Username must be 3-150 characters"
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
            'required': True,
            'autocomplete': 'current-password'
        })
    )
    
    def clean_username(self):
        """Validate and sanitize username"""
        username = self.cleaned_data.get('username')
        
        # Null/empty check
        if not username:
            raise forms.ValidationError("Username is required.")
        
        # Strip whitespace
        username = username.strip()
        
        # Sanitize username
        username = sanitize_username(username)
        
        # Length validation
        if len(username) < 3:
            raise forms.ValidationError("Username must be at least 3 characters long.")
        
        if len(username) > 150:
            raise forms.ValidationError("Username must be no more than 150 characters long.")
        
        # Format validation (alphanumeric, underscore, hyphen only)
        if not username.replace('_', '').replace('-', '').isalnum():
            raise forms.ValidationError("Username can only contain letters, numbers, underscores, and hyphens.")
        
        return username
    
    def clean_password(self):
        """Validate password"""
        password = self.cleaned_data.get('password')
        
        # Null/empty check
        if not password:
            raise forms.ValidationError("Password is required.")
        
        # Length check (basic)
        if len(password) < 1:
            raise forms.ValidationError("Password cannot be empty.")
        
        return password


class UserCreateForm(UserCreationForm):
    """
    Form for creating new users with role selection
    Role choices restricted based on creator's role
    """
    email = forms.EmailField(required=False, help_text="Optional")
    role = forms.ChoiceField(
        choices=[],
        required=True,
        help_text="User role in the system"
    )
    is_active = forms.BooleanField(required=False, initial=True)
    is_staff = forms.BooleanField(required=False, initial=False)
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2', 'role', 'is_active', 'is_staff')
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set role choices based on creator
        if user and hasattr(user, 'userprofile'):
            profile = user.userprofile
            if profile.is_super_admin():
                # Super Admin can create Admin, Operator, Viewer
                self.fields['role'].choices = [
                    (Role.ADMIN, Role.ADMIN.label),
                    (Role.OPERATOR, Role.OPERATOR.label),
                    (Role.VIEWER, Role.VIEWER.label),
                ]
            elif profile.is_admin():
                # Admin can only create Operator, Viewer
                self.fields['role'].choices = [
                    (Role.OPERATOR, Role.OPERATOR.label),
                    (Role.VIEWER, Role.VIEWER.label),
                ]
            else:
                # Others cannot create users
                self.fields['role'].choices = []
        else:
            # Default: no role selection
            self.fields['role'].choices = []
        
        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'
    
    def clean_username(self):
        """Enhanced username validation with sanitization"""
        username = self.cleaned_data.get('username')
        
        # Null/empty check
        if not username:
            raise forms.ValidationError("Username is required.")
        
        # Strip whitespace
        username = username.strip()
        
        # Sanitize username
        from core.sanitization import sanitize_username
        username = sanitize_username(username)
        
        # Length validation
        if len(username) < 3:
            raise forms.ValidationError("Username must be at least 3 characters long.")
        
        if len(username) > 30:
            raise forms.ValidationError("Username must be no more than 30 characters long.")
        
        # Security: Prevent reserved usernames
        reserved_usernames = ['root', 'admin', 'administrator', 'superuser', 'system']
        if username.lower() in reserved_usernames:
            raise forms.ValidationError("This username is reserved and cannot be used.")
        
        # Security: Validate username format
        if not username.replace('_', '').replace('-', '').isalnum():
            raise forms.ValidationError("Username can only contain letters, numbers, underscores, and hyphens.")
        
        # Unique constraint validation
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        
        return username
    
    def clean_email(self):
        """Enhanced email validation"""
        email = self.cleaned_data.get('email')
        
        if email:
            # Strip whitespace
            email = email.strip()
            
            # Sanitize email
            from core.sanitization import sanitize_email
            email = sanitize_email(email)
            
            # Email format validation (RFC 5322 compliant)
            try:
                validate_email(email)
            except ValidationError:
                raise forms.ValidationError("Enter a valid email address.")
            
            # Length validation (max 254 characters per RFC 5321)
            if len(email) > 254:
                raise forms.ValidationError("Email address is too long. Maximum length is 254 characters.")
            
            # Unique constraint validation
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError("A user with that email already exists.")
        
        return email
    
    def clean(self):
        """Set is_staff based on role and validate password"""
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        
        # Password validation
        if password1:
            # Length validation
            if len(password1) < 8:
                raise forms.ValidationError({'password1': 'Password must be at least 8 characters long.'})
            
            if len(password1) > 128:
                raise forms.ValidationError({'password1': 'Password must be no more than 128 characters long.'})
            
            # Password confirmation match
            if password1 != password2:
                raise forms.ValidationError({'password2': 'Password fields must match.'})
        
        # Role validation (enum validation)
        if role:
            valid_roles = [Role.ADMIN, Role.OPERATOR, Role.VIEWER]
            if role not in valid_roles:
                raise forms.ValidationError({'role': 'Invalid role selected.'})
        
        # Set is_staff based on role
        if role == Role.ADMIN:
            cleaned_data['is_staff'] = True
        elif role in [Role.OPERATOR, Role.VIEWER]:
            cleaned_data['is_staff'] = False
        
        return cleaned_data


class UserUpdateForm(forms.ModelForm):
    """
    Form for updating existing users with role selection
    Role changes restricted based on updater's role
    """
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text="Leave blank to keep current password"
    )
    confirm_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text="Confirm new password"
    )
    role = forms.ChoiceField(
        choices=[],
        required=False,
        help_text="User role (only Super Admin can change roles)"
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'is_active', 'is_staff', 'role')
    
    def __init__(self, *args, user=None, instance=None, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        
        # Set initial role from profile
        if instance and hasattr(instance, 'userprofile'):
            self.fields['role'].initial = instance.userprofile.role
        
        # Set role choices based on updater
        if user and hasattr(user, 'userprofile'):
            profile = user.userprofile
            if profile.is_super_admin():
                # Super Admin can change any role (except Super Admin for existing Super Admin)
                if instance and hasattr(instance, 'userprofile') and instance.userprofile.is_super_admin():
                    # Cannot change Super Admin role
                    self.fields['role'].widget.attrs['readonly'] = True
                    self.fields['role'].choices = [
                        (Role.SUPER_ADMIN, Role.SUPER_ADMIN.label),
                    ]
                else:
                    self.fields['role'].choices = [
                        (Role.ADMIN, Role.ADMIN.label),
                        (Role.OPERATOR, Role.OPERATOR.label),
                        (Role.VIEWER, Role.VIEWER.label),
                    ]
            else:
                # Others cannot change roles
                self.fields['role'].widget.attrs['readonly'] = True
                self.fields['role'].choices = []
        
        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, forms.PasswordInput):
                field.widget.attrs['class'] = 'form-control'
            else:
                field.widget.attrs['class'] = 'form-control'
    
    def clean_role(self):
        """Validate role changes"""
        role = self.cleaned_data.get('role')
        
        if role and self.instance and hasattr(self.instance, 'userprofile'):
            current_role = self.instance.userprofile.role
            
            # Prevent changing Super Admin role
            if current_role == Role.SUPER_ADMIN and role != Role.SUPER_ADMIN:
                raise forms.ValidationError("Super Admin role cannot be changed.")
        
        return role
    
    def clean_username(self):
        """Enhanced username validation"""
        username = self.cleaned_data.get('username')
        
        if not username:
            raise forms.ValidationError("Username is required.")
        
        # Strip and sanitize
        username = username.strip()
        from core.sanitization import sanitize_username
        username = sanitize_username(username)
        
        # Length validation
        if len(username) < 3:
            raise forms.ValidationError("Username must be at least 3 characters long.")
        
        if len(username) > 30:
            raise forms.ValidationError("Username must be no more than 30 characters long.")
        
        # Unique constraint validation (exclude current user)
        if self.instance and self.instance.pk:
            if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A user with that username already exists.")
        else:
            if User.objects.filter(username=username).exists():
                raise forms.ValidationError("A user with that username already exists.")
        
        return username
    
    def clean_email(self):
        """Enhanced email validation"""
        email = self.cleaned_data.get('email')
        
        if email:
            # Strip and sanitize
            email = email.strip()
            from core.sanitization import sanitize_email
            email = sanitize_email(email)
            
            # Email format validation
            try:
                validate_email(email)
            except ValidationError:
                raise forms.ValidationError("Enter a valid email address.")
            
            # Length validation
            if len(email) > 254:
                raise forms.ValidationError("Email address is too long. Maximum length is 254 characters.")
            
            # Unique constraint validation (exclude current user)
            if self.instance and self.instance.pk:
                if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
                    raise forms.ValidationError("A user with that email already exists.")
        
        return email
    
    def clean(self):
        """Enhanced validation with password and state checks"""
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        role = cleaned_data.get('role')
        
        # Password change validation
        if new_password or confirm_password:
            if not new_password:
                raise forms.ValidationError({'new_password': 'New password is required if changing password.'})
            
            if not confirm_password:
                raise forms.ValidationError({'confirm_password': 'Password confirmation is required.'})
            
            if new_password != confirm_password:
                raise forms.ValidationError({'confirm_password': 'Password fields must match.'})
            
            # Length validation
            if len(new_password) < 8:
                raise forms.ValidationError({'new_password': 'Password must be at least 8 characters long.'})
            
            if len(new_password) > 128:
                raise forms.ValidationError({'new_password': 'Password must be no more than 128 characters long.'})
            
            # Validate password using Django validators
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(new_password, self.instance if self.instance else None)
            except ValidationError as e:
                raise forms.ValidationError({'new_password': list(e.messages)})
        
        # State validation - cannot deactivate self
        if self.instance and self.instance.pk:
            is_active = cleaned_data.get('is_active', True)
            # This check will be done in the view, but we can add it here too
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get('new_password')
        
        if new_password:
            user.set_password(new_password)
        
        if commit:
            user.save()
        return user
