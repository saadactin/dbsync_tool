#!/usr/bin/env python
"""
Manual test script for anomaly detection - quick validation
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, AnomalyAlert
from sync_jobs.services import AnomalyDetectionService
from connections.models import DatabaseConnection

print("Creating test data...")

# Create user
user, _ = User.objects.get_or_create(username='test_anomaly_user', defaults={'email': 'test@example.com'})
user.set_password('testpass')
user.save()

# Create user profile
from accounts.models import UserProfile
profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': 'admin'})

# Create connections
source_conn, _ = DatabaseConnection.objects.get_or_create(
    name='Test Source',
    defaults={
        'db_type': 'postgres',
        'host': 'localhost',
        'port': 5432,
        'database_name': 'test',
        'username': 'test',
        'password': 'test',
        'created_by': user,
        'tenant': user,
        'is_active': True
    }
)

target_conn, _ = DatabaseConnection.objects.get_or_create(
    name='Test Target',
    defaults={
        'db_type': 'postgres',
        'host': 'localhost',
        'port': 5432,
        'database_name': 'test',
        'username': 'test',
        'password': 'test',
        'created_by': user,
        'tenant': user,
        'is_active': True
    }
)

# Create job
job, _ = SyncJob.objects.get_or_create(
    name='Test Anomaly Job',
    defaults={
        'source_connection': source_conn,
        'target_connection': target_conn,
        'sync_type': 'full',
        'status': 'completed',
        'created_by': user,
        'tenant': user
    }
)

print("Testing duration anomaly detection...")
now = timezone.now()

# Create normal executions
for i in range(5):
    SyncExecution.objects.get_or_create(
        job=job,
        started_at=now - timedelta(minutes=10-i),
        defaults={
            'status': 'completed',
            'completed_at': now - timedelta(minutes=10-i) + timedelta(seconds=10),
            'total_rows_synced': 1000
        }
    )

# Create anomalous execution
SyncExecution.objects.get_or_create(
    job=job,
    started_at=now - timedelta(minutes=1),
    defaults={
        'status': 'completed',
        'completed_at': now - timedelta(minutes=1) + timedelta(seconds=50),
        'total_rows_synced': 1000
    }
)

anomaly = AnomalyDetectionService._detect_duration_anomaly(job)
if anomaly:
    print(f"[OK] Duration anomaly detected: {anomaly['type']} - {anomaly['severity']}")
else:
    print("[WARNING] No duration anomaly detected")

print("\nTesting get_active_anomalies...")
anomalies = AnomalyDetectionService.get_active_anomalies(user)
print(f"[OK] Found {anomalies.count()} active anomalies")

print("\nTesting get_anomaly_stats...")
stats = AnomalyDetectionService.get_anomaly_stats(user)
print(f"[OK] Stats: {stats}")

print("\nAll manual tests completed!")
