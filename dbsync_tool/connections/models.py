import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from core.constants import DB_TYPE_CHOICES, DEFAULT_PORTS
from core.encryption import encrypt_password, decrypt_password
from core.exceptions import EncryptionError


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, help_text="Whether this connection is active")
    
    class Meta:
        db_table = 'database_connections'
        ordering = ['-created_at']
        verbose_name = 'Database Connection'
        verbose_name_plural = 'Database Connections'
        indexes = [
            models.Index(fields=['created_by', 'is_active']),
            models.Index(fields=['db_type', 'is_active']),
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
