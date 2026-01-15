"""
Input sanitization utilities to prevent XSS, SQL injection, and other attacks
"""
import re
import html
from django.utils.html import strip_tags, escape
from django.utils.safestring import mark_safe


def sanitize_string(value, allow_html=False, max_length=None):
    """
    Sanitize a string input
    
    Args:
        value: String to sanitize
        allow_html: If True, allow safe HTML tags (not recommended)
        max_length: Maximum length of the string
    
    Returns:
        Sanitized string
    """
    if value is None:
        return None
    
    if not isinstance(value, str):
        value = str(value)
    
    # Strip whitespace
    value = value.strip()
    
    # Remove null bytes
    value = value.replace('\x00', '')
    
    # Apply max length
    if max_length and len(value) > max_length:
        value = value[:max_length]
    
    if allow_html:
        # Only allow safe HTML tags (not recommended for user input)
        # This is a basic implementation - use a proper HTML sanitizer in production
        value = strip_tags(value)
    else:
        # Escape HTML entities
        value = escape(value)
    
    return value


def sanitize_username(username):
    """
    Sanitize username input
    
    Args:
        username: Username string
    
    Returns:
        Sanitized username
    """
    if not username:
        return None
    
    username = str(username).strip()
    
    # Only allow alphanumeric, underscore, hyphen
    username = re.sub(r'[^a-zA-Z0-9_-]', '', username)
    
    return username


def sanitize_email(email):
    """
    Sanitize email input
    
    Args:
        email: Email string
    
    Returns:
        Sanitized email
    """
    if not email:
        return None
    
    email = str(email).strip().lower()
    
    # Remove any HTML/script tags
    email = strip_tags(email)
    
    # Basic email format validation (Django will do full validation)
    # Just ensure no dangerous characters
    email = re.sub(r'[<>"\']', '', email)
    
    return email


def sanitize_filename(filename):
    """
    Sanitize filename to prevent path traversal
    
    Args:
        filename: Filename string
    
    Returns:
        Sanitized filename
    """
    if not filename:
        return None
    
    filename = str(filename).strip()
    
    # Remove path separators
    filename = filename.replace('/', '').replace('\\', '')
    
    # Remove dangerous characters
    filename = re.sub(r'[<>:"|?*]', '', filename)
    
    # Remove leading dots
    filename = filename.lstrip('.')
    
    return filename


def sanitize_sql_input(value):
    """
    Sanitize input for SQL queries (Django ORM handles this, but extra validation)
    
    Args:
        value: Value to sanitize
    
    Returns:
        Sanitized value
    """
    if value is None:
        return None
    
    value = str(value)
    
    # Remove SQL comment markers
    value = value.replace('--', '')
    value = value.replace('/*', '')
    value = value.replace('*/', '')
    
    # Remove semicolons (statement separators)
    value = value.replace(';', '')
    
    # Remove single quotes (parameterized queries should be used)
    # But we'll escape them if needed
    value = value.replace("'", "''")
    
    return value


def remove_html_tags(text):
    """
    Remove all HTML tags from text
    
    Args:
        text: Text with potential HTML tags
    
    Returns:
        Text without HTML tags
    """
    if not text:
        return None
    
    return strip_tags(str(text))


def remove_script_tags(text):
    """
    Remove script tags and event handlers from text
    
    Args:
        text: Text with potential script tags
    
    Returns:
        Text without script tags
    """
    if not text:
        return None
    
    text = str(text)
    
    # Remove script tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove event handlers (onclick, onerror, etc.)
    text = re.sub(r'\s*on\w+\s*=\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
    
    # Remove javascript: protocol
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
    
    return text


def sanitize_for_xss(text):
    """
    Comprehensive XSS prevention
    
    Args:
        text: Text to sanitize
    
    Returns:
        Sanitized text safe from XSS
    """
    if not text:
        return None
    
    text = str(text)
    
    # Remove script tags
    text = remove_script_tags(text)
    
    # Escape HTML entities
    text = escape(text)
    
    return text


def validate_path_traversal(path):
    """
    Validate path to prevent directory traversal attacks
    
    Args:
        path: File path
    
    Returns:
        True if path is safe, False otherwise
    """
    if not path:
        return False
    
    path = str(path)
    
    # Check for path traversal patterns
    dangerous_patterns = [
        '..',
        '//',
        '\\\\',
        '~',
    ]
    
    for pattern in dangerous_patterns:
        if pattern in path:
            return False
    
    # Check for absolute paths (if not allowed)
    if path.startswith('/') or (len(path) > 1 and path[1] == ':'):
        return False
    
    return True

