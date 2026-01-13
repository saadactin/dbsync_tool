"""
Password encryption/decryption utility using Fernet (symmetric encryption)
"""
from cryptography.fernet import Fernet
import os
from django.conf import settings

class EncryptionService:
    """
    Singleton service for encrypting/decrypting sensitive data
    Uses Fernet symmetric encryption (AES 128 in CBC mode)
    """
    _instance = None
    _fernet = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EncryptionService, cls).__new__(cls)
        return cls._instance
    
    def _get_fernet(self):
        """Get or create Fernet instance with encryption key"""
        if self._fernet is None:
            # Get encryption key from settings or environment
            key = getattr(settings, 'ENCRYPTION_KEY', None)
            if not key:
                key = os.environ.get('ENCRYPTION_KEY')
            
            if not key:
                # Generate a key for development (WARNING: Not for production!)
                key = Fernet.generate_key()
                print(f"WARNING: Generated new encryption key. Set ENCRYPTION_KEY={key.decode()} in settings.py")
            
            # If key is a string, encode it
            if isinstance(key, str):
                key = key.encode()
            
            # Validate key length (Fernet keys are 32 bytes, base64 encoded = 44 chars)
            if len(key) != 44:
                # Generate a new key if invalid
                key = Fernet.generate_key()
                print(f"WARNING: Invalid encryption key length. Generated new key: {key.decode()}")
                print(f"Add this to settings.py: ENCRYPTION_KEY = '{key.decode()}'")
            
            try:
                self._fernet = Fernet(key)
            except Exception as e:
                raise ValueError(f"Invalid encryption key format: {str(e)}")
        
        return self._fernet
    
    def encrypt(self, plaintext):
        """
        Encrypt a string and return base64 encoded string
        
        Args:
            plaintext (str): The string to encrypt
            
        Returns:
            str: Encrypted string (base64 encoded)
            
        Raises:
            ValueError: If encryption fails
        """
        if not plaintext:
            return None
        
        try:
            fernet = self._get_fernet()
            encrypted = fernet.encrypt(plaintext.encode('utf-8'))
            return encrypted.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Encryption failed: {str(e)}")
    
    def decrypt(self, ciphertext):
        """
        Decrypt a base64 encoded string and return plaintext
        
        Args:
            ciphertext (str): The encrypted string to decrypt
            
        Returns:
            str: Decrypted plaintext string
            
        Raises:
            ValueError: If decryption fails (invalid key, corrupted data, etc.)
        """
        if not ciphertext:
            return None
        
        try:
            fernet = self._get_fernet()
            decrypted = fernet.decrypt(ciphertext.encode('utf-8'))
            return decrypted.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Decryption failed: {str(e)}. This may indicate corrupted data or wrong encryption key.")


# Convenience functions for easy import
def encrypt_password(password):
    """
    Encrypt a password string
    
    Args:
        password (str): Password to encrypt
        
    Returns:
        str: Encrypted password
    """
    service = EncryptionService()
    return service.encrypt(password)


def decrypt_password(encrypted_password):
    """
    Decrypt an encrypted password
    
    Args:
        encrypted_password (str): Encrypted password to decrypt
        
    Returns:
        str: Decrypted password
    """
    service = EncryptionService()
    return service.decrypt(encrypted_password)


