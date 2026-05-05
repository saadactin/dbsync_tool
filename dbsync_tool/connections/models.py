import uuid
import logging
from pathlib import PurePath
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from core.constants import DB_TYPE_CHOICES, DEFAULT_PORTS, API_TYPE_CHOICES, ZOHO_DEFAULT_TOKEN_URLS
from core.encryption import encrypt_password, decrypt_password
from core.exceptions import EncryptionError

logger = logging.getLogger(__name__)


class DatabaseConnection(models.Model):
    """
    Model to store database connection information
    Passwords are encrypted before saving to database
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="Friendly name for this connection")
    db_type = models.CharField(max_length=20, choices=DB_TYPE_CHOICES, help_text="Database type")
    host = models.CharField(max_length=255, help_text="Database host address")
    port = models.IntegerField(help_text="Database port number")
    username = models.CharField(max_length=255, help_text="Database username")
    password = models.TextField(help_text="Encrypted database password")  # Encrypted
    database_name = models.CharField(max_length=255, help_text="Database name")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='connections')
    tenant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='tenant_connections',
        null=True,  # Nullable initially, will be made required after data migration
        blank=True,
        db_index=True,
        help_text='Tenant (Admin user) who owns this connection'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_tested_at = models.DateTimeField(null=True, blank=True, help_text="Last time this connection was successfully tested")
    is_active = models.BooleanField(default=True, help_text="Whether this connection is active")
    
    class Meta:
        db_table = 'database_connections'
        ordering = ['-created_at']
        verbose_name = 'Database Connection'
        verbose_name_plural = 'Database Connections'
        indexes = [
            models.Index(fields=['created_by', 'is_active']),
            models.Index(fields=['db_type', 'is_active']),
            models.Index(fields=['tenant']),
            models.Index(fields=['tenant', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_db_type_display()})"
    
    def clean(self):
        """Validate model data before saving"""
        super().clean()
        
        # Validate port range
        if self.port < 1 or self.port > 65535:
            raise ValidationError({'port': 'Port must be between 1 and 65535'})
        
        # Validate database type
        valid_types = [choice[0] for choice in DB_TYPE_CHOICES]
        if self.db_type not in valid_types:
            raise ValidationError({'db_type': f'Invalid database type. Must be one of: {", ".join(valid_types)}'})
        
        # Additional validation for Oracle ADW connections
        if self.db_type == 'oracle_adw':
            errors = {}
            if not (self.host or '').strip():
                errors['host'] = 'Host is required for Oracle ADW connections.'
            if not self.port:
                errors['port'] = 'Port is required for Oracle ADW connections.'
            if not (self.username or '').strip():
                errors['username'] = 'Username is required for Oracle ADW connections.'
            if not (self.password or '').strip():
                errors['password'] = 'Password is required for Oracle ADW connections.'
            if not (self.database_name or '').strip():
                # We treat database_name as the Oracle service name / TNS alias.
                errors['database_name'] = 'Service name is required for Oracle ADW connections.'
            if errors:
                raise ValidationError(errors)
    
    def save(self, *args, **kwargs):
        """Override save to encrypt password before saving"""
        # Set default port if not provided
        if not self.port:
            self.port = DEFAULT_PORTS.get(self.db_type, 5432)
        
        # Validate before saving (skip password validation if empty and updating)
        try:
            self.full_clean()
        except ValidationError as e:
            # Allow empty password during updates (user will set new password)
            if 'password' in e.error_dict and not self.password:
                # Remove password error if password is intentionally empty
                del e.error_dict['password']
                if not e.error_dict:
                    # If password was the only error, continue
                    pass
                else:
                    raise e
            else:
                raise e
        
        # Encrypt password before saving (only if it's not already encrypted and not empty)
        # Skip encryption if password is RESET_REQUIRED (special marker)
        if self.password and self.password != 'RESET_REQUIRED':
            # Check if password is already encrypted (Fernet encrypted strings start with 'gAAAAAB')
            if not self.password.startswith('gAAAAAB'):
                try:
                    self.password = encrypt_password(self.password)
                except Exception as e:
                    raise EncryptionError(f"Failed to encrypt password: {str(e)}")
        
        super().save(*args, **kwargs)
    
    def get_decrypted_password(self):
        """
        Get decrypted password for connection
        
        Returns:
            str: Decrypted password
            
        Raises:
            EncryptionError: If decryption fails
        """
        if not self.password or self.password == 'RESET_REQUIRED':
            raise EncryptionError(
                f"Password is not set for connection '{self.name}'. "
                f"Please update the password in the Connections page (Edit connection)."
            )
        
        try:
            return decrypt_password(self.password)
        except ValueError as e:
            # More specific error for encryption key mismatch
            error_msg = str(e)
            if "Decryption failed" in error_msg or "Invalid token" in error_msg or "InvalidSignature" in str(type(e).__name__):
                raise EncryptionError(
                    f"Failed to decrypt password for connection '{self.name}'. "
                    f"The encryption key may have changed. "
                    f"Please update the password by editing this connection in the Connections page."
                )
            raise EncryptionError(f"Failed to decrypt password: {error_msg}")
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt password: {str(e)}")
    
    def get_connection_params(self):
        """
        Get connection parameters as dictionary
        
        Returns:
            dict: Connection parameters
        """
        return {
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'password': self.get_decrypted_password(),
            'database_name': self.database_name,
        }
    
    def test_connection(self):
        """
        Test the database connection
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        from connections.connectors import get_connector
        from core.exceptions import DatabaseConnectionError
        
        connector = None
        try:
            connector = get_connector(
                db_type=self.db_type,
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.get_decrypted_password(),
                database_name=self.database_name
            )
            return connector.test_connection()
        except Exception:
            return False
        finally:
            if connector:
                connector.close()


FILE_FORMAT_CHOICES = [
    ('csv', 'CSV'),
    ('tsv', 'TSV'),
    ('txt', 'Plain Text (delimited)'),
    ('json', 'JSON'),
    ('jsonl', 'JSON Lines (NDJSON)'),
    ('xml', 'XML'),
    ('xlsx', 'Excel Workbook (XLSX)'),
]
DELIMITED_FORMATS = {'csv', 'tsv', 'txt'}
NESTED_STRATEGY_CHOICES = [
    ('flatten', 'Flatten with dot-paths'),
    ('json_blob', 'Keep nested values as JSON blobs'),
]


class FileSourceConnection(models.Model):
    """
    Model to store flat-file source connection information.
    The path is stored as a relative path under FILE_SYNC_ROOT.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="Friendly name for this file source")
    relative_path = models.CharField(
        max_length=1024,
        help_text="Path relative to FILE_SYNC_ROOT on the application server"
    )
    file_format = models.CharField(
        max_length=16,
        choices=FILE_FORMAT_CHOICES,
        default='csv',
        help_text="File format used by the parser engine."
    )
    delimiter = models.CharField(
        max_length=1,
        default=',',
        blank=True,
        help_text="Delimiter character for CSV/TSV/TXT (ignored for JSON/XML/XLSX)."
    )
    encoding = models.CharField(
        max_length=64,
        default='utf-8',
        help_text="File encoding (e.g., utf-8, utf-16, latin-1). Ignored for XLSX."
    )
    has_header = models.BooleanField(
        default=True,
        help_text="Whether the first row contains column headers (CSV/TSV/TXT/XLSX)."
    )
    record_path = models.CharField(
        max_length=512,
        blank=True,
        default='',
        help_text=(
            "JSON: dotted path to a list of records (e.g. data.items). "
            "XML: XPath-like record path (e.g. /root/items/item)."
        ),
    )
    sheet_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="XLSX sheet name. Empty = first sheet.",
    )
    nested_strategy = models.CharField(
        max_length=16,
        choices=NESTED_STRATEGY_CHOICES,
        default='flatten',
        help_text="How to handle nested JSON/XML structures.",
    )
    flatten_separator = models.CharField(
        max_length=4,
        default='.',
        help_text="Separator for dot-path flattening (only used when nested_strategy=flatten).",
    )
    tenant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='file_source_connections',
        db_index=True,
        help_text='Tenant (Admin user) who owns this file source connection'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_file_source_connections',
        help_text='User who created this file source connection'
    )
    is_active = models.BooleanField(default=True, help_text="Whether this file source is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'file_source_connections'
        ordering = ['-created_at']
        verbose_name = 'File Source Connection'
        verbose_name_plural = 'File Source Connections'
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
            models.Index(fields=['created_by', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_file_source_connection_name_per_tenant'
            )
        ]

    def __str__(self):
        return f"{self.name} (File Source)"

    def clean(self):
        super().clean()

        path_value = (self.relative_path or '').strip()
        if not path_value:
            raise ValidationError({'relative_path': 'Relative path is required.'})
        if '\x00' in path_value:
            raise ValidationError({'relative_path': 'Relative path contains invalid characters.'})

        candidate = PurePath(path_value)
        if candidate.is_absolute():
            raise ValidationError(
                {'relative_path': 'Path must be relative to FILE_SYNC_ROOT, not absolute.'}
            )
        if path_value.startswith('\\\\') or path_value.startswith('//'):
            raise ValidationError(
                {'relative_path': 'UNC paths are not allowed. Use a relative path under FILE_SYNC_ROOT.'}
            )
        if any(part == '..' for part in candidate.parts):
            raise ValidationError(
                {'relative_path': 'Relative path cannot contain parent-directory traversal (..).'}
            )

        fmt = (self.file_format or 'csv').lower()
        if fmt in DELIMITED_FORMATS:
            delim = self.delimiter if self.delimiter is not None else ''
            if len(delim) != 1:
                raise ValidationError(
                    {'delimiter': 'Delimiter must be exactly one character for CSV/TSV/TXT.'}
                )
        if fmt != 'xlsx':
            if not (self.encoding or '').strip():
                raise ValidationError({'encoding': 'Encoding is required.'})

        if fmt == 'xml':
            if not (self.record_path or '').strip():
                raise ValidationError(
                    {'record_path': 'XML sources require a record path (e.g. /root/items/item).'}
                )

        if fmt in {'json', 'xml'} and self.nested_strategy == 'flatten':
            sep = (self.flatten_separator or '').strip()
            if not sep:
                raise ValidationError(
                    {'flatten_separator': 'Flatten separator is required when nested_strategy=flatten.'}
                )


class ConnectionTestLog(models.Model):
    """
    Model to log connection test results
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(
        DatabaseConnection, 
        on_delete=models.CASCADE, 
        related_name='test_logs',
        help_text="The connection that was tested"
    )
    status = models.CharField(
        max_length=20, 
        choices=[('success', 'Success'), ('failed', 'Failed')],
        help_text="Test result status"
    )
    error_message = models.TextField(null=True, blank=True, help_text="Error message if test failed")
    tested_at = models.DateTimeField(auto_now_add=True, help_text="When the test was performed")
    tested_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='connection_tests',
        help_text="User who performed the test"
    )
    
    class Meta:
        db_table = 'connection_test_logs'
        ordering = ['-tested_at']
        verbose_name = 'Connection Test Log'
        verbose_name_plural = 'Connection Test Logs'
        indexes = [
            models.Index(fields=['connection', '-tested_at']),
            models.Index(fields=['status', '-tested_at']),
        ]
    
    def __str__(self):
        return f"{self.connection.name} - {self.status} - {self.tested_at.strftime('%Y-%m-%d %H:%M:%S')}"


class APIConnection(models.Model):
    """
    Model to store API connection information (Zoho CRM, etc.)
    Credentials are encrypted before saving to database
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="Friendly name for this connection")
    api_type = models.CharField(max_length=50, choices=API_TYPE_CHOICES, help_text="API type")
    
    # Zoho-specific fields (nullable so SAP connections do not require them)
    client_id = models.CharField(max_length=255, blank=True, null=True, help_text="OAuth Client ID")
    client_secret = models.TextField(blank=True, null=True, help_text="Encrypted OAuth Client Secret")  # Encrypted
    refresh_token = models.TextField(blank=True, null=True, help_text="Encrypted OAuth Refresh Token")  # Encrypted
    api_domain = models.CharField(max_length=255, blank=True, null=True, help_text="Zoho API domain")
    token_url = models.CharField(max_length=255, blank=True, null=True, help_text="OAuth token URL")
    
    # Module configuration
    selected_modules = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="List of selected module names for syncing"
    )
    
    # SAP-specific fields
    sap_base_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="SAP Business One Service Layer base URL (e.g. https://server:50000/b1s/v2/)"
    )
    sap_username = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="SAP UserName and CompanyDB (stored as JSON: {\"UserName\": \"...\", \"CompanyDB\": \"...\"})"
    )
    sap_password = models.TextField(
        blank=True,
        null=True,
        help_text="SAP password (encrypted at rest)"
    )
    sap_endpoints = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="Selected SAP document types/endpoints for sync"
    )
    
    # Azure DevOps-specific fields
    azure_tenant_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Azure AD Tenant ID (GUID)"
    )
    azure_client_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Azure DevOps Service Principal Application (client) ID"
    )
    azure_client_secret = models.TextField(
        blank=True,
        null=True,
        help_text="Azure DevOps Client Secret (encrypted at rest)"
    )
    organization = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Azure DevOps organization name"
    )
    
    # Standard fields
    tenant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='api_connections',
        db_index=True,
        help_text='Tenant (Admin user) who owns this connection'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_api_connections',
        help_text='User who created this connection'
    )
    is_active = models.BooleanField(default=True, help_text="Whether this connection is active")
    last_tested_at = models.DateTimeField(null=True, blank=True, help_text="Last time this connection was successfully tested")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'api_connections'
        ordering = ['-created_at']
        verbose_name = 'API Connection'
        verbose_name_plural = 'API Connections'
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
            models.Index(fields=['api_type', 'is_active']),
            models.Index(fields=['created_by', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_api_connection_name_per_tenant'
            )
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_api_type_display()})"
    
    def clean(self):
        """Validate model data before saving"""
        from urllib.parse import urlparse

        super().clean()
        
        # Validate API type
        valid_types = [choice[0] for choice in API_TYPE_CHOICES]
        if self.api_type not in valid_types:
            raise ValidationError({'api_type': f'Invalid API type. Must be one of: {", ".join(valid_types)}'})
        
        if self.api_type == 'zoho_crm':
            # Zoho: require Zoho-specific fields
            if not self.client_id:
                raise ValidationError({'client_id': 'Client ID is required for Zoho CRM connections.'})
            if not self.client_secret or self.client_secret == 'RESET_REQUIRED':
                raise ValidationError({'client_secret': 'Client secret is required for Zoho CRM connections.'})
            if not self.refresh_token or self.refresh_token == 'RESET_REQUIRED':
                raise ValidationError({'refresh_token': 'Refresh token is required for Zoho CRM connections.'})
            if not self.api_domain:
                raise ValidationError({'api_domain': 'API domain is required for Zoho CRM connections.'})
            if not self.token_url:
                raise ValidationError({'token_url': 'Token URL is required for Zoho CRM connections.'})
            if self.api_domain:
                parsed = urlparse(self.api_domain)
                if not parsed.scheme or not parsed.netloc:
                    raise ValidationError({'api_domain': 'API domain must be a valid URL (e.g., https://www.zohoapis.in)'})
            if self.token_url:
                parsed = urlparse(self.token_url)
                if not parsed.scheme or not parsed.netloc:
                    raise ValidationError({'token_url': 'Token URL must be a valid URL (e.g., https://accounts.zoho.in/oauth/v2/token)'})
        
        elif self.api_type == 'sap_b1':
            # SAP: require SAP-specific fields
            if not self.sap_base_url:
                raise ValidationError({'sap_base_url': 'SAP base URL is required for SAP B1 connections.'})
            if not self.sap_password or self.sap_password == 'RESET_REQUIRED':
                raise ValidationError({'sap_password': 'SAP password is required for SAP B1 connections.'})
            if self.sap_base_url:
                parsed = urlparse(self.sap_base_url)
                if not parsed.scheme or not parsed.netloc:
                    raise ValidationError({'sap_base_url': 'SAP base URL must be a valid URL.'})
            # If sap_username is already populated (e.g. when creating programmatically),
            # ensure it has the expected structure. The form-level validation for
            # sap_user_name and sap_company_db handles the required checks.
            if self.sap_username:
                if not isinstance(self.sap_username, dict) or \
                   'UserName' not in self.sap_username or \
                   'CompanyDB' not in self.sap_username:
                    raise ValidationError(
                        'SAP username payload must be a JSON object with '
                        'UserName and CompanyDB keys.'
                    )
            if self.sap_endpoints is not None and not isinstance(self.sap_endpoints, list):
                raise ValidationError({'sap_endpoints': 'SAP endpoints must be a list.'})
        
        elif self.api_type == 'azure_devops':
            # Azure DevOps: require Azure-specific fields
            if not (self.organization or '').strip():
                raise ValidationError({'organization': 'Organization is required for Azure DevOps connections.'})
            if not (self.azure_tenant_id or '').strip():
                raise ValidationError({'azure_tenant_id': 'Azure Tenant ID is required for Azure DevOps connections.'})
            if not (self.azure_client_id or '').strip():
                raise ValidationError({'azure_client_id': 'Azure Client ID is required for Azure DevOps connections.'})
            if not self.azure_client_secret or self.azure_client_secret == 'RESET_REQUIRED':
                raise ValidationError({'azure_client_secret': 'Azure Client Secret is required for Azure DevOps connections.'})
        
        # Validate selected_modules is a list (if provided)
        if self.selected_modules is not None and not isinstance(self.selected_modules, list):
            raise ValidationError({'selected_modules': 'Selected modules must be a list'})
    
    def save(self, *args, **kwargs):
        """Override save to encrypt credentials and set defaults before saving"""
        # Zoho defaults only when API type is Zoho
        if self.api_type == 'zoho_crm':
            if not self.api_domain:
                self.api_domain = 'https://www.zohoapis.in'
            if not self.token_url and self.api_domain:
                self.token_url = ZOHO_DEFAULT_TOKEN_URLS.get(self.api_domain, 'https://accounts.zoho.in/oauth/v2/token')
        
        # Set default selected_modules if None
        if self.selected_modules is None:
            self.selected_modules = []
        
        # Set default sap_endpoints for SAP
        if self.api_type == 'sap_b1' and self.sap_endpoints is None:
            self.sap_endpoints = []
        
        # Validate before saving
        try:
            self.full_clean()
        except ValidationError as e:
            raise e
        
        # Encrypt client_secret before saving (only if it's not already encrypted and not empty)
        if self.client_secret and self.client_secret != 'RESET_REQUIRED':
            if not self.client_secret.startswith('gAAAAAB'):
                try:
                    self.client_secret = encrypt_password(self.client_secret)
                except Exception as e:
                    raise EncryptionError(f"Failed to encrypt client secret: {str(e)}")
        
        # Encrypt refresh_token before saving (only if it's not already encrypted and not empty)
        if self.refresh_token and self.refresh_token != 'RESET_REQUIRED':
            if not self.refresh_token.startswith('gAAAAAB'):
                try:
                    self.refresh_token = encrypt_password(self.refresh_token)
                except Exception as e:
                    raise EncryptionError(f"Failed to encrypt refresh token: {str(e)}")
        
        # Encrypt sap_password before saving (only if it's not already encrypted and not empty)
        if self.sap_password and self.sap_password != 'RESET_REQUIRED':
            if not self.sap_password.startswith('gAAAAAB'):
                try:
                    self.sap_password = encrypt_password(self.sap_password)
                except Exception as e:
                    raise EncryptionError(f"Failed to encrypt SAP password: {str(e)}")
        
        # Encrypt azure_client_secret before saving (only if it's not already encrypted and not empty)
        if self.azure_client_secret and self.azure_client_secret != 'RESET_REQUIRED':
            if not self.azure_client_secret.startswith('gAAAAAB'):
                try:
                    self.azure_client_secret = encrypt_password(self.azure_client_secret)
                except Exception as e:
                    raise EncryptionError(f"Failed to encrypt Azure client secret: {str(e)}")
        
        super().save(*args, **kwargs)
    
    def get_decrypted_client_secret(self):
        """
        Get decrypted client secret for connection
        
        Returns:
            str: Decrypted client secret
            
        Raises:
            EncryptionError: If decryption fails or secret is not set
        """
        if not self.client_secret or self.client_secret == 'RESET_REQUIRED':
            raise EncryptionError(
                f"Client secret is not set for connection '{self.name}'. "
                f"Please update the client secret in the Connections page (Edit connection)."
            )
        
        try:
            return decrypt_password(self.client_secret)
        except ValueError as e:
            # More specific error for encryption key mismatch
            error_msg = str(e)
            if "Decryption failed" in error_msg or "Invalid token" in error_msg or "InvalidSignature" in str(type(e).__name__):
                raise EncryptionError(
                    f"Failed to decrypt client secret for connection '{self.name}'. "
                    f"The encryption key may have changed. "
                    f"Please update the client secret by editing this connection in the Connections page."
                )
            raise EncryptionError(f"Failed to decrypt client secret: {error_msg}")
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt client secret: {str(e)}")
    
    def get_decrypted_refresh_token(self):
        """
        Get decrypted refresh token for connection
        
        Returns:
            str: Decrypted refresh token
            
        Raises:
            EncryptionError: If decryption fails or token is not set
        """
        if not self.refresh_token or self.refresh_token == 'RESET_REQUIRED':
            raise EncryptionError(
                f"Refresh token is not set for connection '{self.name}'. "
                f"Please update the refresh token in the Connections page (Edit connection)."
            )
        
        try:
            return decrypt_password(self.refresh_token)
        except ValueError as e:
            # More specific error for encryption key mismatch
            error_msg = str(e)
            if "Decryption failed" in error_msg or "Invalid token" in error_msg or "InvalidSignature" in str(type(e).__name__):
                raise EncryptionError(
                    f"Failed to decrypt refresh token for connection '{self.name}'. "
                    f"The encryption key may have changed. "
                    f"Please update the refresh token by editing this connection in the Connections page."
                )
            raise EncryptionError(f"Failed to decrypt refresh token: {error_msg}")
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt refresh token: {str(e)}")
    
    def get_decrypted_sap_password(self):
        """
        Get decrypted SAP password for connection.

        Returns:
            str: Decrypted SAP password.

        Raises:
            EncryptionError: If decryption fails or password is not set.
        """
        if not self.sap_password or self.sap_password == 'RESET_REQUIRED':
            raise EncryptionError(
                f"SAP password is not set for connection '{self.name}'. "
                f"Please update the password in the Connections page (Edit connection)."
            )
        try:
            return decrypt_password(self.sap_password)
        except ValueError as e:
            error_msg = str(e)
            if "Decryption failed" in error_msg or "Invalid token" in error_msg or "InvalidSignature" in str(type(e).__name__):
                raise EncryptionError(
                    f"Failed to decrypt SAP password for connection '{self.name}'. "
                    f"The encryption key may have changed. "
                    f"Please update the password by editing this connection in the Connections page."
                )
            raise EncryptionError(f"Failed to decrypt SAP password: {error_msg}")
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt SAP password: {str(e)}")
    
    def get_decrypted_azure_client_secret(self):
        """
        Get decrypted Azure client secret for connection.

        Returns:
            str: Decrypted Azure client secret.

        Raises:
            EncryptionError: If decryption fails or secret is not set.
        """
        if not self.azure_client_secret or self.azure_client_secret == 'RESET_REQUIRED':
            raise EncryptionError(
                f"Azure client secret is not set for connection '{self.name}'. "
                f"Please update the client secret in the Connections page (Edit connection)."
            )
        try:
            return decrypt_password(self.azure_client_secret)
        except ValueError as e:
            error_msg = str(e)
            if "Decryption failed" in error_msg or "Invalid token" in error_msg or "InvalidSignature" in str(type(e).__name__):
                raise EncryptionError(
                    f"Failed to decrypt Azure client secret for connection '{self.name}'. "
                    f"The encryption key may have changed. "
                    f"Please update the client secret by editing this connection in the Connections page."
                )
            raise EncryptionError(f"Failed to decrypt Azure client secret: {error_msg}")
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt Azure client secret: {str(e)}")
    
    def get_sap_connection_params(self):
        """
        Get SAP connection parameters as dictionary (for use by SAP connector).

        Returns:
            dict: base_url, username (dict with UserName, CompanyDB), password (decrypted).
        """
        return {
            'base_url': self.sap_base_url,
            'username': self.sap_username,
            'password': self.get_decrypted_sap_password(),
        }
    
    def get_connection_params(self):
        """
        Get connection parameters as dictionary (type-specific).

        Returns:
            dict: Connection parameters with decrypted credentials (Zoho, SAP, or Azure DevOps).
        """
        if self.api_type == 'sap_b1':
            return self.get_sap_connection_params()
        if self.api_type == 'azure_devops':
            return {
                'tenant_id': self.azure_tenant_id,
                'client_id': self.azure_client_id,
                'client_secret': self.get_decrypted_azure_client_secret(),
                'organization': self.organization,
            }
        return {
            'client_id': self.client_id,
            'client_secret': self.get_decrypted_client_secret(),
            'refresh_token': self.get_decrypted_refresh_token(),
            'api_domain': self.api_domain,
            'token_url': self.token_url,
        }
    
    def test_connection(self):
        """
        Test the API connection and return available modules
        
        Returns:
            tuple: (success: bool, message: str, modules: list)
            
        Raises:
            Exception: If connection test fails with error details
        """
        try:
            if self.api_type == 'sap_b1':
                from connections.connectors.sap import SAPConnector
                connector = SAPConnector(self)
                if not connector.authenticate():
                    return (False, "Authentication failed. Please check your SAP credentials.", [])
                try:
                    modules = connector.get_available_modules()
                    if not modules:
                        return (True, "Connection successful, but no endpoints found.", [])
                    return (True, f"Connection successful. Found {len(modules)} endpoints.", modules)
                except Exception as e:
                    logger.error("SAP get_available_modules failed: %s", e)
                    return (False, f"Connection successful, but failed to fetch endpoints: {str(e)}", [])
            if self.api_type == 'azure_devops':
                from connections.connectors.azure_devops import AzureDevOpsConnector
                connector = AzureDevOpsConnector(self)
                if not connector.authenticate():
                    return (False, "Authentication failed. Please check your Azure credentials.", [])
                try:
                    projects = connector.get_available_modules()
                    if not projects:
                        return (True, "Connection successful, but no projects found.", [])
                    return (True, f"Connection successful. Found {len(projects)} project(s).", projects)
                except Exception as e:
                    logger.error("Azure DevOps get_available_modules failed: %s", e)
                    return (False, f"Connection successful, but failed to fetch projects: {str(e)}", [])
            from connections.connectors.zoho import ZohoConnector
            if self.api_type != 'zoho_crm':
                return (False, f"Unsupported API type: {self.api_type}", [])
            
            # Create connector and test authentication
            connector = ZohoConnector(self)
            
            # Test authentication
            if not connector.authenticate():
                return (False, "Authentication failed. Please check your credentials.", [])
            
            # Get available modules
            try:
                modules = connector.get_available_modules()
                if not modules:
                    return (True, "Connection successful, but no modules found.", [])
                
                return (True, f"Connection successful. Found {len(modules)} modules.", modules)
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to fetch modules: {error_msg}")
                return (False, f"Connection successful, but failed to fetch modules: {error_msg}", [])
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Connection test failed: {error_msg}")
            return (False, f"Connection test failed: {error_msg}", [])
