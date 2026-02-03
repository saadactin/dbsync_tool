import uuid
import logging
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
    
    # Zoho-specific fields
    client_id = models.CharField(max_length=255, help_text="OAuth Client ID")
    client_secret = models.TextField(help_text="Encrypted OAuth Client Secret")  # Encrypted
    refresh_token = models.TextField(help_text="Encrypted OAuth Refresh Token")  # Encrypted
    api_domain = models.CharField(max_length=255, help_text="Zoho API domain")
    token_url = models.CharField(max_length=255, help_text="OAuth token URL")
    
    # Module configuration
    selected_modules = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="List of selected module names for syncing"
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
        super().clean()
        
        # Validate API type
        valid_types = [choice[0] for choice in API_TYPE_CHOICES]
        if self.api_type not in valid_types:
            raise ValidationError({'api_type': f'Invalid API type. Must be one of: {", ".join(valid_types)}'})
        
        # Validate api_domain is a valid URL format
        if self.api_domain:
            from urllib.parse import urlparse
            parsed = urlparse(self.api_domain)
            if not parsed.scheme or not parsed.netloc:
                raise ValidationError({'api_domain': 'API domain must be a valid URL (e.g., https://www.zohoapis.in)'})
        
        # Validate token_url is a valid URL format
        if self.token_url:
            from urllib.parse import urlparse
            parsed = urlparse(self.token_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValidationError({'token_url': 'Token URL must be a valid URL (e.g., https://accounts.zoho.in/oauth/v2/token)'})
        
        # Validate selected_modules is a list (if provided)
        if self.selected_modules is not None and not isinstance(self.selected_modules, list):
            raise ValidationError({'selected_modules': 'Selected modules must be a list'})
    
    def save(self, *args, **kwargs):
        """Override save to encrypt credentials and set defaults before saving"""
        # Set default api_domain if not provided
        if not self.api_domain:
            self.api_domain = 'https://www.zohoapis.in'
        
        # Set default token_url based on api_domain if not provided
        if not self.token_url and self.api_domain:
            self.token_url = ZOHO_DEFAULT_TOKEN_URLS.get(self.api_domain, 'https://accounts.zoho.in/oauth/v2/token')
        
        # Set default selected_modules if None
        if self.selected_modules is None:
            self.selected_modules = []
        
        # Validate before saving
        try:
            self.full_clean()
        except ValidationError as e:
            raise e
        
        # Encrypt client_secret before saving (only if it's not already encrypted and not empty)
        if self.client_secret and self.client_secret != 'RESET_REQUIRED':
            # Check if client_secret is already encrypted (Fernet encrypted strings start with 'gAAAAAB')
            if not self.client_secret.startswith('gAAAAAB'):
                try:
                    self.client_secret = encrypt_password(self.client_secret)
                except Exception as e:
                    raise EncryptionError(f"Failed to encrypt client secret: {str(e)}")
        
        # Encrypt refresh_token before saving (only if it's not already encrypted and not empty)
        if self.refresh_token and self.refresh_token != 'RESET_REQUIRED':
            # Check if refresh_token is already encrypted (Fernet encrypted strings start with 'gAAAAAB')
            if not self.refresh_token.startswith('gAAAAAB'):
                try:
                    self.refresh_token = encrypt_password(self.refresh_token)
                except Exception as e:
                    raise EncryptionError(f"Failed to encrypt refresh token: {str(e)}")
        
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
    
    def get_connection_params(self):
        """
        Get connection parameters as dictionary
        
        Returns:
            dict: Connection parameters with decrypted credentials
        """
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
            # Import here to avoid circular imports
            from connections.connectors.zoho import ZohoConnector
            
            # Only support Zoho CRM for now
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
