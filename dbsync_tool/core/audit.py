"""
Audit logging for compliance and security tracking
"""
import logging
from django.utils import timezone
from django.contrib.auth.models import User

logger = logging.getLogger('audit')


class AuditLogger:
    """Audit logger for tracking user actions and system events"""
    
    @staticmethod
    def log_user_action(user, action, resource_type, resource_id=None, details=None, ip_address=None):
        """
        Log user action
        
        Args:
            user: User instance or username
            action: Action performed (create, update, delete, view, etc.)
            resource_type: Type of resource (user, connection, sync_job, etc.)
            resource_id: ID of the resource
            details: Additional details
            ip_address: IP address of the user
        """
        username = user.username if isinstance(user, User) else str(user)
        user_id = user.id if isinstance(user, User) else None
        
        log_data = {
            'event_type': 'user_action',
            'username': username,
            'user_id': user_id,
            'action': action,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'details': details or {},
            'ip_address': ip_address,
            'timestamp': timezone.now().isoformat(),
        }
        
        logger.info(f"User action: {username} - {action} - {resource_type}", extra=log_data)
    
    @staticmethod
    def log_authentication_event(event_type, username, success=True, ip_address=None, details=None):
        """
        Log authentication event
        
        Args:
            event_type: Event type (login, logout, password_change, etc.)
            username: Username
            success: Whether the event was successful
            ip_address: IP address
            details: Additional details
        """
        log_data = {
            'event_type': 'authentication',
            'auth_event_type': event_type,
            'username': username,
            'success': success,
            'ip_address': ip_address,
            'details': details or {},
            'timestamp': timezone.now().isoformat(),
        }
        
        level = logging.INFO if success else logging.WARNING
        logger.log(
            level,
            f"Authentication event: {event_type} - {username} - {'Success' if success else 'Failed'}",
            extra=log_data
        )
    
    @staticmethod
    def log_authorization_failure(user, resource_type, action, reason, ip_address=None):
        """
        Log authorization failure
        
        Args:
            user: User instance or username
            resource_type: Type of resource
            action: Action attempted
            reason: Reason for failure
            ip_address: IP address
        """
        username = user.username if isinstance(user, User) else str(user)
        user_id = user.id if isinstance(user, User) else None
        
        log_data = {
            'event_type': 'authorization_failure',
            'username': username,
            'user_id': user_id,
            'resource_type': resource_type,
            'action': action,
            'reason': reason,
            'ip_address': ip_address,
            'timestamp': timezone.now().isoformat(),
        }
        
        logger.warning(
            f"Authorization failure: {username} - {action} - {resource_type} - {reason}",
            extra=log_data
        )
    
    @staticmethod
    def log_data_modification(user, resource_type, resource_id, action, changes=None, ip_address=None):
        """
        Log data modification
        
        Args:
            user: User instance
            resource_type: Type of resource
            resource_id: ID of the resource
            action: Action performed (create, update, delete)
            changes: Dictionary of changes (for updates)
            ip_address: IP address
        """
        username = user.username if isinstance(user, User) else str(user)
        user_id = user.id if isinstance(user, User) else None
        
        log_data = {
            'event_type': 'data_modification',
            'username': username,
            'user_id': user_id,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'action': action,
            'changes': changes or {},
            'ip_address': ip_address,
            'timestamp': timezone.now().isoformat(),
        }
        
        logger.info(
            f"Data modification: {username} - {action} - {resource_type} - {resource_id}",
            extra=log_data
        )
    
    @staticmethod
    def log_error_event(error_type, message, user=None, resource_type=None, resource_id=None, details=None):
        """
        Log error event
        
        Args:
            error_type: Type of error
            message: Error message
            user: User instance (if applicable)
            resource_type: Type of resource (if applicable)
            resource_id: ID of resource (if applicable)
            details: Additional details
        """
        log_data = {
            'event_type': 'error',
            'error_type': error_type,
            'message': message,
            'username': user.username if user and isinstance(user, User) else None,
            'user_id': user.id if user and isinstance(user, User) else None,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'details': details or {},
            'timestamp': timezone.now().isoformat(),
        }
        
        logger.error(f"Error event: {error_type} - {message}", extra=log_data)
    
    @staticmethod
    def log_security_event(event_type, severity, message, user=None, ip_address=None, details=None):
        """
        Log security event
        
        Args:
            event_type: Type of security event
            severity: Severity level (low, medium, high, critical)
            message: Event message
            user: User instance (if applicable)
            ip_address: IP address
            details: Additional details
        """
        username = user.username if isinstance(user, User) else None
        user_id = user.id if isinstance(user, User) else None
        
        log_data = {
            'event_type': 'security',
            'security_event_type': event_type,
            'severity': severity,
            'message': message,
            'username': username,
            'user_id': user_id,
            'ip_address': ip_address,
            'details': details or {},
            'timestamp': timezone.now().isoformat(),
        }
        
        # Use appropriate log level based on severity
        severity_map = {
            'low': logging.INFO,
            'medium': logging.WARNING,
            'high': logging.ERROR,
            'critical': logging.CRITICAL,
        }
        
        log_level = severity_map.get(severity, logging.WARNING)
        logger.log(
            log_level,
            f"Security event: {event_type} - {severity} - {message}",
            extra=log_data
        )

