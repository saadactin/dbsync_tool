from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from accounts.models import UserProfile, Role
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Auto-create UserProfile when User is created
    This ensures every user has a profile
    """
    if created:
        # Determine role based on is_staff/is_superuser
        if instance.is_superuser:
            role = Role.SUPER_ADMIN
            tenant = None
        elif instance.is_staff:
            role = Role.ADMIN
            tenant = instance  # Admin is their own tenant
        else:
            role = Role.VIEWER
            tenant = None  # Will be set when assigned to admin
        
        try:
            profile, profile_created = UserProfile.objects.get_or_create(
                user=instance,
                defaults={
                    'role': role,
                    'tenant': tenant
                }
            )
            
            if profile_created:
                logger.info(
                    f'Created UserProfile for user {instance.username} with role {role}',
                    extra={
                        'username': instance.username,
                        'role': role,
                        'tenant_id': tenant.id if tenant else None
                    }
                )
        except Exception as e:
            logger.error(
                f'Failed to create UserProfile for user {instance.username}: {str(e)}',
                extra={'username': instance.username, 'error': str(e)}
            )
            # Don't raise - allow user creation to succeed
            # Profile can be created manually later

