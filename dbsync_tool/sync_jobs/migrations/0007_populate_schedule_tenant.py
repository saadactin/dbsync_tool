from django.db import migrations


def populate_schedule_tenants(apps, schema_editor):
    """Populate tenant field from job.tenant"""
    SyncSchedule = apps.get_model('sync_jobs', 'SyncSchedule')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    
    for schedule in SyncSchedule.objects.all():
        if schedule.tenant is None:
            # First try to get from job
            if schedule.job and schedule.job.tenant:
                schedule.tenant = schedule.job.tenant
                schedule.save()
            elif schedule.job and schedule.job.created_by:
                # Fallback: get from job's created_by
                try:
                    profile = UserProfile.objects.get(user=schedule.job.created_by)
                    if profile.role == 'admin':
                        schedule.tenant = schedule.job.created_by
                    elif profile.role == 'super_admin':
                        schedule.tenant = schedule.job.created_by
                    elif profile.tenant:
                        schedule.tenant = profile.tenant
                    else:
                        schedule.tenant = schedule.job.created_by
                    schedule.save()
                except UserProfile.DoesNotExist:
                    schedule.tenant = schedule.job.created_by
                    schedule.save()
                except Exception:
                    schedule.tenant = schedule.job.created_by
                    schedule.save()


def reverse_populate_schedule_tenants(apps, schema_editor):
    """Reverse migration - set tenant to None"""
    SyncSchedule = apps.get_model('sync_jobs', 'SyncSchedule')
    SyncSchedule.objects.all().update(tenant=None)


class Migration(migrations.Migration):
    dependencies = [
        ('sync_jobs', '0006_populate_job_tenant'),  # Ensure job.tenant is populated first
    ]

    operations = [
        migrations.RunPython(populate_schedule_tenants, reverse_populate_schedule_tenants),
    ]

