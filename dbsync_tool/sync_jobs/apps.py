from django.apps import AppConfig


class SyncJobsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sync_jobs'
    
    def ready(self):
        """Import signal handlers when app is ready"""
        import sync_jobs.signals  # noqa