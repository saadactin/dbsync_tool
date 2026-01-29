#!/usr/bin/env python
"""
Quick test script for anomaly detection - validates imports and basic functionality
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

print("Testing imports...")

try:
    from sync_jobs.models import AnomalyAlert
    print("[OK] AnomalyAlert model imported")
except Exception as e:
    print(f"[ERROR] Error importing AnomalyAlert: {e}")
    sys.exit(1)

try:
    from sync_jobs.services import AnomalyDetectionService
    print("[OK] AnomalyDetectionService imported")
except Exception as e:
    print(f"[ERROR] Error importing AnomalyDetectionService: {e}")
    sys.exit(1)

try:
    from sync_jobs.serializers import AnomalyAlertSerializer
    print("[OK] AnomalyAlertSerializer imported")
except Exception as e:
    print(f"[ERROR] Error importing AnomalyAlertSerializer: {e}")
    sys.exit(1)

print("\nTesting service methods exist...")

methods = [
    'detect_all_anomalies',
    'detect_job_anomalies',
    '_detect_duration_anomaly',
    '_detect_failure_pattern',
    '_detect_row_count_anomaly',
    '_detect_connection_timeout',
    'get_active_anomalies',
    'acknowledge_anomaly',
    'get_anomaly_stats'
]

for method in methods:
    if hasattr(AnomalyDetectionService, method):
        print(f"[OK] {method} exists")
    else:
        print(f"[ERROR] {method} missing")
        sys.exit(1)

print("\nAll checks passed!")
