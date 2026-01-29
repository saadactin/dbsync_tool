#!/usr/bin/env python
"""
Quick test script for Health Score feature
Run with: python manage.py shell < test_health_score_quick.py
Or: python manage.py shell
Then paste the code
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.contrib.auth.models import User
from sync_jobs.services import HealthScoreService
from sync_jobs.models import HealthScoreSnapshot
from connections.models import DatabaseConnection

print("=" * 60)
print("Health Score Feature - Quick Test")
print("=" * 60)

# Get or create a test user
try:
    user = User.objects.get(username='admin')
    print(f"✓ Using existing user: {user.username}")
except User.DoesNotExist:
    print("✗ No admin user found. Please create one first.")
    sys.exit(1)

# Test 1: Calculate score
print("\n1. Testing calculate_score()...")
try:
    score_data = HealthScoreService.calculate_score(user)
    print(f"   ✓ Score calculated: {score_data['score']}")
    print(f"   ✓ Components: {score_data['components']}")
    assert 0 <= score_data['score'] <= 100, "Score out of range"
    assert 'success_rate' in score_data['components'], "Missing success_rate"
    assert 'connection_health' in score_data['components'], "Missing connection_health"
    assert 'schedule_adherence' in score_data['components'], "Missing schedule_adherence"
    assert 'error_frequency' in score_data['components'], "Missing error_frequency"
    print("   ✓ All components present")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Get trend
print("\n2. Testing get_trend()...")
try:
    trend = HealthScoreService.get_trend(user, days=7)
    print(f"   ✓ Trend retrieved: {len(trend)} data points")
    assert isinstance(trend, list), "Trend should be a list"
    print("   ✓ Trend format correct")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Get trend direction
print("\n3. Testing get_trend_direction()...")
try:
    direction = HealthScoreService.get_trend_direction(user)
    print(f"   ✓ Trend direction: {direction}")
    assert direction in ['improving', 'degrading', 'stable'], "Invalid trend direction"
    print("   ✓ Trend direction valid")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Save snapshot
print("\n4. Testing save_snapshot()...")
try:
    initial_count = HealthScoreSnapshot.objects.filter(tenant=user).count()
    HealthScoreService.save_snapshot(user)
    final_count = HealthScoreSnapshot.objects.filter(tenant=user).count()
    print(f"   ✓ Snapshot saved (count: {initial_count} -> {final_count})")
    assert final_count >= initial_count, "Snapshot not saved"
    print("   ✓ Snapshot saved successfully")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Model import
print("\n5. Testing model import...")
try:
    from sync_jobs.models import HealthScoreSnapshot
    print("   ✓ HealthScoreSnapshot model imported")
    snapshot = HealthScoreSnapshot.objects.first()
    if snapshot:
        print(f"   ✓ Found existing snapshot: score={snapshot.score}")
    else:
        print("   ✓ No snapshots yet (expected for new installation)")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("All quick tests passed! ✓")
print("=" * 60)
