from django.db import migrations


def populate_connection_tenants(apps, schema_editor):
    """Populate tenant field from created_by"""
    DatabaseConnection = apps.get_model('connections', 'DatabaseConnection')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    User = apps.get_model('auth', 'User')
    
    for conn in DatabaseConnection.objects.all():
        if conn.tenant is None:
            try:
                profile = UserProfile.objects.get(user=conn.created_by)
                if profile.role == 'admin':
                    conn.tenant = conn.created_by
                elif profile.role == 'super_admin':
                    # Super Admin: use themselves as tenant (they own their own data)
                    conn.tenant = conn.created_by
                elif profile.tenant:
                    conn.tenant = profile.tenant
                else:
                    # Fallback: use created_by as tenant
                    conn.tenant = conn.created_by
                conn.save()
            except UserProfile.DoesNotExist:
                # Fallback: use created_by as tenant
                conn.tenant = conn.created_by
                conn.save()
            except Exception as e:
                # Last resort: use created_by as tenant
                conn.tenant = conn.created_by
                conn.save()


def reverse_populate_connection_tenants(apps, schema_editor):
    """Reverse migration - set tenant to None"""
    DatabaseConnection = apps.get_model('connections', 'DatabaseConnection')
    DatabaseConnection.objects.all().update(tenant=None)


class Migration(migrations.Migration):
    dependencies = [
        ('connections', '0002_databaseconnection_tenant_and_more'),
        ('accounts', '0002_populate_userprofile'),  # Ensure UserProfile exists
    ]

    operations = [
        migrations.RunPython(populate_connection_tenants, reverse_populate_connection_tenants),
    ]

