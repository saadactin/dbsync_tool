"""
Celery configuration - DISABLED
Using APScheduler instead (no Celery/Redis needed)
"""
# Celery configuration removed - using APScheduler for task scheduling
# See scheduler.service for the new scheduler implementation

# import os
# from celery import Celery
# 
# # Set default Django settings module
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
# 
# app = Celery('dbsync_tool')
# 
# # Load configuration from Django settings using namespace 'CELERY'
# app.config_from_object('django.conf:settings', namespace='CELERY')
# 
# # Auto-discover tasks from all installed apps
# app.autodiscover_tasks()
# 
# @app.task(bind=True)
# def debug_task(self):
#     """Debug task for testing Celery setup"""
#     print(f'Request: {self.request!r}')

