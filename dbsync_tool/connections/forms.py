"""
Forms for connection management
"""
import json
import re
from django import forms
from django.core.exceptions import ValidationError
from .models import DatabaseConnection, APIConnection
from core.constants import (
    DB_TYPE_CHOICES,
    DEFAULT_PORTS,
    API_TYPE_CHOICES,
    ZOHO_API_DOMAINS,
    ZOHO_DEFAULT_TOKEN_URLS,
)
from core.sanitization import sanitize_string
from urllib.parse import urlparse


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
        db_type_from_data = None
        if 'db_type' in self.data:
            db_type_from_data = self.data['db_type']
            if db_type_from_data in DEFAULT_PORTS:
                self.fields['port'].initial = DEFAULT_PORTS[db_type_from_data]
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
        
        # For create mode (no instance), make database_name optional initially for non-Oracle types.
        # JavaScript will populate it before submission for engines that support database listing.
        if not self.instance or not self.instance.pk:
            self.fields['database_name'].required = False

        # Apply Oracle ADW specific label/help and requirements for service name
        db_type_effective = db_type_from_data or (
            self.instance.db_type if getattr(self.instance, 'db_type', None) else None
        )
        if db_type_effective == 'oracle_adw':
            # For Oracle ADW we always expect an explicit service name entered by the user.
            self.fields['database_name'].required = True
            self.fields['database_name'].label = "Service Name (Oracle ADW)"
            self.fields['database_name'].help_text = (
                "Use the service name from your JDBC/connection string (e.g. mytpdb_high). Required for Oracle ADW."
            )
            # Oracle-specific placeholders (also set dynamically by JS when switching db_type)
            self.fields['host'].widget.attrs['placeholder'] = 'adw-instance.region.tenant.oraclecloud.com'
            self.fields['port'].widget.attrs['placeholder'] = '1522'
            self.fields['database_name'].widget.attrs['placeholder'] = 'mytpdb_high'
    
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
            db_type = self.data.get('db_type') if getattr(self, 'data', None) else None
            if db_type == 'oracle_adw':
                raise forms.ValidationError("Host is required for Oracle ADW.")
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
            db_type = self.data.get('db_type') if getattr(self, 'data', None) else None
            if db_type == 'oracle_adw':
                raise forms.ValidationError("Port must be between 1 and 65535 (Oracle ADW often uses 1522).")
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
        db_type = (
            self.cleaned_data.get('db_type')
            or (self.data.get('db_type') if getattr(self, 'data', None) else None)
        )
        
        # For edit mode, use existing value if not provided
        if not database_name or not database_name.strip():
            if self.instance and self.instance.pk:
                # Edit mode: use existing database_name
                return self.instance.database_name
            else:
                # Create mode: required, but message depends on DB type
                if db_type == 'oracle_adw':
                    raise forms.ValidationError(
                        "Service name is required for Oracle ADW (use the value from your JDBC connection string)."
                    )
                raise forms.ValidationError(
                    "Database name is required. Please select a database from the list after testing the connection."
                )
        
        # Strip and sanitize: accept any value valid for migration (backend will reject at connect if invalid)
        database_name = database_name.strip()
        database_name = sanitize_string(database_name, max_length=255)
        
        if len(database_name) < 1:
            raise forms.ValidationError("Database name cannot be empty.")
        
        if len(database_name) > 255:
            raise forms.ValidationError(
                "Database name must be no more than 255 characters long."
            )
        
        # Only block null bytes and control characters (safety); allow anything else the DB might accept
        if re.search(r'[\x00-\x1f\x7f]', database_name):
            raise forms.ValidationError(
                "Database name must not contain control characters."
            )
        
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


class APIConnectionForm(forms.ModelForm):
    """Form for creating and editing API connections (Zoho and SAP)."""
    client_id = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="OAuth Client ID (Zoho)"
    )
    client_secret = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={'class': 'form-control'}),
        required=False,
        help_text="OAuth Client Secret (will be encrypted)"
    )
    refresh_token = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={'class': 'form-control'}),
        required=False,
        help_text="OAuth Refresh Token (will be encrypted)"
    )
    api_domain = forms.ChoiceField(
        choices=[],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_api_domain'}),
        help_text="Zoho API domain based on your region"
    )
    token_url = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_token_url',
            'readonly': 'readonly'
        }),
        required=False,
        help_text="OAuth token URL (auto-populated based on API domain)"
    )
    # SAP-specific form fields (mapped to model in save())
    sap_base_url = forms.CharField(
        max_length=512,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_sap_base_url',
            'placeholder': 'https://yourserver:50000/b1s/v2/',
        }),
        help_text="SAP B1 Service Layer base URL (e.g. https://server:50000/b1s/v2/)"
    )
    sap_user_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_sap_user_name',
            'placeholder': 'e.g. manager',
        }),
        help_text="SAP User Name (Login)"
    )
    sap_company_db = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_sap_company_db',
            'placeholder': 'e.g. SBODEMO',
        }),
        help_text="SAP Company Database"
    )
    sap_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'class': 'form-control', 'id': 'id_sap_password'}),
        help_text="SAP password (encrypted at rest)"
    )

    class Meta:
        model = APIConnection
        fields = [
            'name', 'api_type', 'client_id', 'client_secret', 'refresh_token',
            'api_domain', 'token_url', 'selected_modules',
            'sap_base_url', 'sap_password', 'sap_endpoints',
            'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'api_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_api_type'}),
            'client_id': forms.TextInput(attrs={'class': 'form-control'}),
            'selected_modules': forms.HiddenInput(),
            'sap_endpoints': forms.HiddenInput(),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set API domain choices
        api_domain_choices = [
            ('', '-- Select API Domain --'),
        ]
        for key, value in ZOHO_API_DOMAINS.items():
            api_domain_choices.append((value, f"{key.title()} ({value})"))
        self.fields['api_domain'].choices = api_domain_choices
        self.fields['api_domain'].widget.attrs.update({'class': 'form-control', 'id': 'id_api_domain'})
        
        # Set API type choices
        self.fields['api_type'].widget.choices = API_TYPE_CHOICES
        
        # Make token_url read-only
        self.fields['token_url'].widget.attrs['readonly'] = 'readonly'
        
        # Set initial token_url if api_domain is set
        if self.instance and self.instance.pk and self.instance.api_domain:
            self.fields['token_url'].initial = ZOHO_DEFAULT_TOKEN_URLS.get(
                self.instance.api_domain, 
                'https://accounts.zoho.in/oauth/v2/token'
            )
        elif 'api_domain' in self.initial and self.initial['api_domain']:
            self.fields['token_url'].initial = ZOHO_DEFAULT_TOKEN_URLS.get(
                self.initial['api_domain'],
                'https://accounts.zoho.in/oauth/v2/token'
            )
        
        # On edit mode, make password/secret fields optional
        if self.instance and self.instance.pk:
            self.fields['client_secret'].required = False
            self.fields['client_secret'].help_text = "Leave blank to keep existing client secret"
            self.fields['refresh_token'].required = False
            self.fields['refresh_token'].help_text = "Leave blank to keep existing refresh token"
            self.fields['sap_password'].required = False
            self.fields['sap_password'].help_text = "Leave blank to keep existing password"
            # SAP initial values when editing
            if self.instance.api_type == 'sap_b1':
                self.fields['sap_base_url'].initial = self.instance.sap_base_url or ''
                if self.instance.sap_username:
                    self.fields['sap_user_name'].initial = self.instance.sap_username.get('UserName') or ''
                    self.fields['sap_company_db'].initial = self.instance.sap_username.get('CompanyDB') or ''
                if self.instance.sap_password == 'RESET_REQUIRED' or not self.instance.sap_password:
                    self.fields['sap_password'].required = True
                    self.fields['sap_password'].help_text = "⚠️ SAP password must be set. Previous password could not be decrypted."
                    self.fields['sap_password'].widget.attrs['class'] = 'form-control is-invalid'
            # Check if Zoho credentials need to be reset
            if self.instance.client_secret == 'RESET_REQUIRED' or not self.instance.client_secret:
                self.fields['client_secret'].required = True
                self.fields['client_secret'].help_text = "⚠️ Client secret must be set. Previous secret could not be decrypted."
                self.fields['client_secret'].widget.attrs['class'] = 'form-control is-invalid'
            if self.instance.refresh_token == 'RESET_REQUIRED' or not self.instance.refresh_token:
                self.fields['refresh_token'].required = True
                self.fields['refresh_token'].help_text = "⚠️ Refresh token must be set. Previous token could not be decrypted."
                self.fields['refresh_token'].widget.attrs['class'] = 'form-control is-invalid'
    
    def clean_name(self):
        """Validate connection name"""
        name = self.cleaned_data.get('name')
        
        if not name:
            raise forms.ValidationError("Connection name is required.")
        
        name = name.strip()
        name = sanitize_string(name, max_length=255)
        
        if len(name) < 1:
            raise forms.ValidationError("Connection name cannot be empty.")
        
        if len(name) > 255:
            raise forms.ValidationError("Connection name must be no more than 255 characters long.")
        
        if not re.match(r'^[a-zA-Z0-9\s_-]+$', name):
            raise forms.ValidationError("Connection name can only contain letters, numbers, spaces, underscores, and hyphens.")
        
        return name
    
    def clean_api_type(self):
        """Validate API type"""
        api_type = self.cleaned_data.get('api_type')
        
        if not api_type:
            raise forms.ValidationError("API type is required.")
        
        valid_types = [choice[0] for choice in API_TYPE_CHOICES]
        if api_type not in valid_types:
            raise forms.ValidationError(f"Invalid API type. Must be one of: {', '.join(valid_types)}")
        
        return api_type
    
    def _get_api_type(self):
        """Return api_type from cleaned_data or form data (for validation order)."""
        return (
            self.cleaned_data.get('api_type')
            or (self.data.get('api_type') if getattr(self, 'data', None) else None)
            or 'zoho_crm'
        )

    def clean_client_id(self):
        """Validate client ID (required only for Zoho)."""
        api_type = self._get_api_type()
        if api_type != 'zoho_crm':
            return self.cleaned_data.get('client_id') or ''
        client_id = self.cleaned_data.get('client_id')
        if not client_id or not str(client_id).strip():
            raise forms.ValidationError("Client ID is required for Zoho CRM.")
        client_id = str(client_id).strip()
        client_id = sanitize_string(client_id, max_length=255)
        if len(client_id) > 255:
            raise forms.ValidationError("Client ID must be no more than 255 characters long.")
        return client_id

    def clean_client_secret(self):
        """Validate client secret (required only for Zoho)."""
        api_type = self._get_api_type()
        if api_type != 'zoho_crm':
            return self.cleaned_data.get('client_secret')
        client_secret = self.cleaned_data.get('client_secret')
        if not self.instance or not self.instance.pk:
            if not client_secret:
                raise forms.ValidationError("Client secret is required for Zoho CRM.")
        else:
            if not client_secret:
                return None
        if client_secret and len(str(client_secret).strip()) < 1:
            raise forms.ValidationError("Client secret cannot be empty.")
        return client_secret

    def clean_refresh_token(self):
        """Validate refresh token (required only for Zoho)."""
        api_type = self._get_api_type()
        if api_type != 'zoho_crm':
            return self.cleaned_data.get('refresh_token')
        refresh_token = self.cleaned_data.get('refresh_token')
        if not self.instance or not self.instance.pk:
            if not refresh_token:
                raise forms.ValidationError("Refresh token is required for Zoho CRM.")
        else:
            if not refresh_token:
                return None
        if refresh_token and len(str(refresh_token).strip()) < 1:
            raise forms.ValidationError("Refresh token cannot be empty.")
        return refresh_token

    def clean_api_domain(self):
        """Validate API domain (required only for Zoho)."""
        api_type = self._get_api_type()
        if api_type != 'zoho_crm':
            return self.cleaned_data.get('api_domain') or ''
        api_domain = self.cleaned_data.get('api_domain')
        if not api_domain:
            raise forms.ValidationError("API domain is required for Zoho CRM.")
        parsed = urlparse(api_domain)
        if not parsed.scheme or not parsed.netloc:
            raise forms.ValidationError("API domain must be a valid URL (e.g., https://www.zohoapis.in)")
        if api_domain not in ZOHO_API_DOMAINS.values():
            raise forms.ValidationError(f"Invalid API domain. Must be one of: {', '.join(ZOHO_API_DOMAINS.values())}")
        return api_domain

    def clean_token_url(self):
        """Validate token URL (required only for Zoho)."""
        api_type = self._get_api_type()
        if api_type != 'zoho_crm':
            return self.cleaned_data.get('token_url') or ''
        token_url = self.cleaned_data.get('token_url')
        if not token_url:
            api_domain = self.cleaned_data.get('api_domain')
            if api_domain:
                token_url = ZOHO_DEFAULT_TOKEN_URLS.get(api_domain, 'https://accounts.zoho.in/oauth/v2/token')
                self.cleaned_data['token_url'] = token_url
            else:
                raise forms.ValidationError("Token URL is required for Zoho CRM.")
        if token_url:
            parsed = urlparse(token_url)
            if not parsed.scheme or not parsed.netloc:
                raise forms.ValidationError("Token URL must be a valid URL.")
        return token_url or ''

    def clean_sap_base_url(self):
        """Validate SAP base URL (required only for SAP)."""
        api_type = self._get_api_type()
        if api_type != 'sap_b1':
            return self.cleaned_data.get('sap_base_url') or ''
        url = (self.cleaned_data.get('sap_base_url') or '').strip()
        if not url:
            raise forms.ValidationError("SAP base URL is required for SAP B1 connections.")
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise forms.ValidationError("SAP base URL must be a valid URL.")
        return url

    def clean_sap_user_name(self):
        """Validate SAP user name (required only for SAP)."""
        api_type = self._get_api_type()
        if api_type != 'sap_b1':
            return self.cleaned_data.get('sap_user_name') or ''
        val = (self.cleaned_data.get('sap_user_name') or '').strip()
        if not val:
            raise forms.ValidationError("SAP User Name is required for SAP B1 connections.")
        return sanitize_string(val, max_length=255)

    def clean_sap_company_db(self):
        """Validate SAP company DB (required only for SAP)."""
        api_type = self._get_api_type()
        if api_type != 'sap_b1':
            return self.cleaned_data.get('sap_company_db') or ''
        val = (self.cleaned_data.get('sap_company_db') or '').strip()
        if not val:
            raise forms.ValidationError("SAP Company DB is required for SAP B1 connections.")
        return sanitize_string(val, max_length=255)

    def clean_sap_password(self):
        """Validate SAP password (required only for SAP)."""
        api_type = self._get_api_type()
        if api_type != 'sap_b1':
            return self.cleaned_data.get('sap_password')
        password = self.cleaned_data.get('sap_password')
        if not self.instance or not self.instance.pk:
            if not password:
                raise forms.ValidationError("SAP password is required for SAP B1 connections.")
        else:
            if not password:
                return None
        if password and len(str(password).strip()) < 1:
            raise forms.ValidationError("SAP password cannot be empty.")
        return password

    def clean_sap_endpoints(self):
        """Validate sap_endpoints is a list (accept JSON string from hidden input)."""
        val = self.cleaned_data.get('sap_endpoints')
        if val is None:
            return []
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return []
            try:
                val = json.loads(val)
            except (ValueError, TypeError):
                raise forms.ValidationError("SAP endpoints must be a valid list.")
        if not isinstance(val, list):
            raise forms.ValidationError("SAP endpoints must be a list.")
        return val
    
    def clean_selected_modules(self):
        """Validate selected modules"""
        selected_modules = self.cleaned_data.get('selected_modules')
        
        if selected_modules is None:
            return []
        
        if not isinstance(selected_modules, list):
            raise forms.ValidationError("Selected modules must be a list.")
        
        return selected_modules
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        api_type = cleaned_data.get('api_type')

        if api_type == 'zoho_crm':
            api_domain = cleaned_data.get('api_domain')
            token_url = cleaned_data.get('token_url')
            if api_domain and not token_url:
                cleaned_data['token_url'] = ZOHO_DEFAULT_TOKEN_URLS.get(
                    api_domain, 'https://accounts.zoho.in/oauth/v2/token'
                )
        elif api_type == 'sap_b1':
            sap_endpoints = cleaned_data.get('sap_endpoints') or []
            if not sap_endpoints:
                self.add_error('sap_endpoints', 'Please select at least one SAP endpoint to sync.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        api_type = getattr(instance, 'api_type', None) or self.cleaned_data.get('api_type')

        if api_type == 'zoho_crm':
            if 'client_secret' in self.cleaned_data and self.cleaned_data['client_secret']:
                instance.client_secret = self.cleaned_data['client_secret']
            if 'refresh_token' in self.cleaned_data and self.cleaned_data['refresh_token']:
                instance.refresh_token = self.cleaned_data['refresh_token']
        elif api_type == 'sap_b1':
            instance.sap_base_url = self.cleaned_data.get('sap_base_url') or ''
            instance.sap_username = {
                'UserName': self.cleaned_data.get('sap_user_name') or '',
                'CompanyDB': self.cleaned_data.get('sap_company_db') or '',
            }
            instance.sap_endpoints = self.cleaned_data.get('sap_endpoints') or []
            if self.cleaned_data.get('sap_password'):
                instance.sap_password = self.cleaned_data['sap_password']

        if commit:
            instance.save()
        return instance
