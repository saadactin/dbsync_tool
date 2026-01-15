from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from accounts.models import Role


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username',
            'required': True
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
            'required': True
        })
    )


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
        username = self.cleaned_data.get('username')
        
        # Security: Prevent reserved usernames
        reserved_usernames = ['root', 'admin', 'administrator', 'superuser', 'system']
        if username.lower() in reserved_usernames:
            raise forms.ValidationError("This username is reserved and cannot be used.")
        
        # Security: Validate username format
        if not username.replace('_', '').replace('-', '').isalnum():
            raise forms.ValidationError("Username can only contain letters, numbers, underscores, and hyphens.")
        
        if len(username) < 3:
            raise forms.ValidationError("Username must be at least 3 characters long.")
        
        if len(username) > 30:
            raise forms.ValidationError("Username must be no more than 30 characters long.")
        
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            try:
                validate_email(email)
            except ValidationError:
                raise forms.ValidationError("Enter a valid email address.")
        return email
    
    def clean(self):
        """Set is_staff based on role"""
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        
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
        username = self.cleaned_data.get('username')
        if self.instance and self.instance.pk and User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username
    
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if new_password or confirm_password:
            if new_password != confirm_password:
                raise forms.ValidationError("Password fields must match.")
            # Validate password using Django validators
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(new_password)
            except ValidationError as e:
                raise forms.ValidationError(list(e.messages))
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get('new_password')
        
        if new_password:
            user.set_password(new_password)
        
        if commit:
            user.save()
        return user
