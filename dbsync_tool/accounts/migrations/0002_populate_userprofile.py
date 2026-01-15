from django.db import migrations


def create_user_profiles(apps, schema_editor):
    """Create UserProfile for all existing users"""
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    
    for user in User.objects.all():
        if UserProfile.objects.filter(user=user).exists():
            continue
        
        # Determine role based on existing flags
        if user.is_superuser:
            role = 'super_admin'
            tenant = None
        elif user.is_staff:
            role = 'admin'
            tenant = user  # Admin is their own tenant
        else:
            role = 'viewer'
            tenant = None  # Will be assigned when assigned to admin
        
        UserProfile.objects.create(
            user=user,
            role=role,
            tenant=tenant
        )


def reverse_create_user_profiles(apps, schema_editor):
    """Reverse migration - delete all UserProfiles"""
    UserProfile = apps.get_model('accounts', 'UserProfile')
    UserProfile.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_user_profiles, reverse_create_user_profiles),
    ]

