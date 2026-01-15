from django.db import migrations


def populate_job_tenants(apps, schema_editor):
    """Populate tenant field from created_by"""
    SyncJob = apps.get_model('sync_jobs', 'SyncJob')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    
    for job in SyncJob.objects.all():
        if job.tenant is None:
            try:
                profile = UserProfile.objects.get(user=job.created_by)
                if profile.role == 'admin':
                    job.tenant = job.created_by
                elif profile.role == 'super_admin':
                    # Super Admin: use themselves as tenant
                    job.tenant = job.created_by
                elif profile.tenant:
                    job.tenant = profile.tenant
                else:
                    # Fallback: use created_by as tenant
                    job.tenant = job.created_by
                job.save()
            except UserProfile.DoesNotExist:
                # Fallback: use created_by as tenant
                job.tenant = job.created_by
                job.save()
            except Exception:
                # Last resort: use created_by as tenant
                job.tenant = job.created_by
                job.save()


def reverse_populate_job_tenants(apps, schema_editor):
    """Reverse migration - set tenant to None"""
    SyncJob = apps.get_model('sync_jobs', 'SyncJob')
    SyncJob.objects.all().update(tenant=None)


class Migration(migrations.Migration):
    dependencies = [
        ('sync_jobs', '0005_syncjob_tenant_syncschedule_tenant_and_more'),
        ('accounts', '0002_populate_userprofile'),  # Ensure UserProfile exists
    ]

    operations = [
        migrations.RunPython(populate_job_tenants, reverse_populate_job_tenants),
    ]

