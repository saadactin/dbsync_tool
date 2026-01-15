"""
Forms for connection management
"""
import re
from django import forms
from django.core.exceptions import ValidationError
from .models import DatabaseConnection
from core.constants import DB_TYPE_CHOICES, DEFAULT_PORTS
from core.sanitization import sanitize_string


class DatabaseConnectionForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={'class': 'form-control'}),
        required=True,
        help_text="Database password (will be encrypted)"
    )
    
    class Meta:
        model = DatabaseConnection
        fields = ['name', 'db_type', 'host', 'port', 'username', 'password', 'database_name', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'db_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_db_type'}),
            'host': forms.TextInput(attrs={'class': 'form-control'}),
            'port': forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_port'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'database_name': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default port based on DB type
        if 'db_type' in self.data:
            db_type = self.data['db_type']
            if db_type in DEFAULT_PORTS:
                self.fields['port'].initial = DEFAULT_PORTS[db_type]
        elif self.instance and self.instance.pk:
            # Editing existing connection
            # Check if password needs to be reset
            if self.instance.password == 'RESET_REQUIRED' or not self.instance.password:
                self.fields['password'].required = True
                self.fields['password'].help_text = "⚠️ Password must be set. Previous password could not be decrypted."
                self.fields['password'].widget.attrs['class'] = 'form-control is-invalid'
            else:
                self.fields['password'].required = False
                self.fields['password'].help_text = "Leave blank to keep existing password"
        
        # For create mode (no instance), make database_name optional initially
        # JavaScript will populate it before submission
        if not self.instance or not self.instance.pk:
            self.fields['database_name'].required = False
    
    def clean_name(self):
        """Validate connection name"""
        name = self.cleaned_data.get('name')
        
        # Required field check
        if not name:
            raise forms.ValidationError("Connection name is required.")
        
        # Strip and sanitize
        name = name.strip()
        name = sanitize_string(name, max_length=100)
        
        # Length validation
        if len(name) < 1:
            raise forms.ValidationError("Connection name cannot be empty.")
        
        if len(name) > 100:
            raise forms.ValidationError("Connection name must be no more than 100 characters long.")
        
        # Format validation (alphanumeric, spaces, underscore, hyphen)
        if not re.match(r'^[a-zA-Z0-9\s_-]+$', name):
            raise forms.ValidationError("Connection name can only contain letters, numbers, spaces, underscores, and hyphens.")
        
        # Unique per tenant validation (will be checked in view)
        
        return name
    
    def clean_db_type(self):
        """Validate database type"""
        db_type = self.cleaned_data.get('db_type')
        
        # Required field check
        if not db_type:
            raise forms.ValidationError("Database type is required.")
        
        # Enum validation
        valid_types = [choice[0] for choice in DB_TYPE_CHOICES]
        if db_type not in valid_types:
            raise forms.ValidationError(f"Invalid database type. Must be one of: {', '.join(valid_types)}")
        
        return db_type
    
    def clean_host(self):
        """Validate host"""
        host = self.cleaned_data.get('host')
        
        # Required field check
        if not host:
            raise forms.ValidationError("Host is required.")
        
        # Strip and sanitize
        host = host.strip()
        host = sanitize_string(host, max_length=255)
        
        # Length validation
        if len(host) < 1:
            raise forms.ValidationError("Host cannot be empty.")
        
        if len(host) > 255:
            raise forms.ValidationError("Host must be no more than 255 characters long.")
        
        # Format validation (hostname or IP address)
        # Basic validation - IP or hostname pattern
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        hostname_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        
        if not (re.match(ip_pattern, host) or re.match(hostname_pattern, host)):
            raise forms.ValidationError("Invalid host format. Please enter a valid hostname or IP address.")
        
        return host
    
    def clean_port(self):
        """Validate port"""
        port = self.cleaned_data.get('port')
        
        # Required field check
        if port is None:
            raise forms.ValidationError("Port is required.")
        
        # Data type validation
        try:
            port = int(port)
        except (ValueError, TypeError):
            raise forms.ValidationError("Port must be a valid number.")
        
        # Range validation
        if port < 1 or port > 65535:
            raise forms.ValidationError("Port must be between 1 and 65535.")
        
        return port
    
    def clean_username(self):
        """Validate username"""
        username = self.cleaned_data.get('username')
        
        # Required field check
        if not username:
            raise forms.ValidationError("Username is required.")
        
        # Strip and sanitize
        username = username.strip()
        username = sanitize_string(username, max_length=100)
        
        # Length validation
        if len(username) < 1:
            raise forms.ValidationError("Username cannot be empty.")
        
        if len(username) > 100:
            raise forms.ValidationError("Username must be no more than 100 characters long.")
        
        return username
    
    def clean_password(self):
        """Validate password"""
        password = self.cleaned_data.get('password')
        
        # Required on create, optional on update
        if not self.instance or not self.instance.pk:
            # Create mode
            if not password:
                raise forms.ValidationError("Password is required.")
        else:
            # Update mode - password is optional
            if not password:
                return None  # Will keep existing password
        
        # Length validation
        if password and len(password) < 1:
            raise forms.ValidationError("Password cannot be empty.")
        
        if password and len(password) > 500:
            raise forms.ValidationError("Password must be no more than 500 characters long.")
        
        return password
    
    def clean_database_name(self):
        """Validate database name"""
        database_name = self.cleaned_data.get('database_name')
        
        # For edit mode, use existing value if not provided
        if not database_name or not database_name.strip():
            if self.instance and self.instance.pk:
                # Edit mode: use existing database_name
                return self.instance.database_name
            else:
                # Create mode: must select database
                raise forms.ValidationError("Database name is required. Please select a database from the list after testing the connection.")
        
        # Strip and sanitize
        database_name = database_name.strip()
        database_name = sanitize_string(database_name, max_length=100)
        
        # Length validation
        if len(database_name) < 1:
            raise forms.ValidationError("Database name cannot be empty.")
        
        if len(database_name) > 100:
            raise forms.ValidationError("Database name must be no more than 100 characters long.")
        
        # Format validation (database-specific naming rules - basic check)
        # Most databases allow alphanumeric, underscore, hyphen, dollar sign
        if not re.match(r'^[a-zA-Z0-9_$-]+$', database_name):
            raise forms.ValidationError("Database name contains invalid characters.")
        
        return database_name
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        
        # Business rule: Cannot create connection with same name in same tenant
        # This will be checked in the view with tenant context
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Only update password if provided
        if 'password' in self.cleaned_data and self.cleaned_data['password']:
            instance.password = self.cleaned_data['password']
        if commit:
            instance.save()
        return instance
