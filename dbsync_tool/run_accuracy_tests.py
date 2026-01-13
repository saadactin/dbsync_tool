#!/usr/bin/env python
"""
Standalone script to run data accuracy tests for PostgreSQL ↔ MySQL migration
This script can be run directly to test data accuracy with your existing databases
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from connections.connectors.base import ColumnInfo
from sync_jobs.tests.test_data_accuracy_postgres_mysql import DataAccuracyTest
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_accuracy_tests():
    """Run data accuracy tests using existing database connections"""
    print("=" * 80)
    print("Data Accuracy Test Suite - PostgreSQL <-> MySQL")
    print("=" * 80)
    print()
    
    # Get or create test user
    try:
        user = User.objects.get(username='accuracytest')
    except User.DoesNotExist:
        user = User.objects.create_user(
            username='accuracytest',
            password='testpass123',
            email='accuracy@example.com'
        )
        print(f"[OK] Created test user: {user.username}")
    
    # Get existing database connections
    pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
    mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
    
    if not pg_conn:
        print("[ERROR] No PostgreSQL connection found. Please create one in the Connections page.")
        return False
    
    if not mysql_conn:
        print("[ERROR] No MySQL connection found. Please create one in the Connections page.")
        return False
    
    print(f"[OK] Found PostgreSQL connection: {pg_conn.name} ({pg_conn.host}:{pg_conn.port}/{pg_conn.database_name})")
    print(f"[OK] Found MySQL connection: {mysql_conn.name} ({mysql_conn.host}:{mysql_conn.port}/{mysql_conn.database_name})")
    print()
    
    # Create test instance
    test_instance = DataAccuracyTest()
    test_instance.user = user
    test_instance.setUp()
    
    # Test PostgreSQL -> MySQL
    print("-" * 80)
    print("Test 1: PostgreSQL -> MySQL Data Accuracy")
    print("-" * 80)
    
    try:
        test_instance.test_postgres_to_mysql_accuracy()
        print("[PASSED] PostgreSQL -> MySQL accuracy test")
    except Exception as e:
        print(f"[FAILED] PostgreSQL -> MySQL accuracy test")
        print(f"   Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    
    # Test MySQL -> PostgreSQL
    print("-" * 80)
    print("Test 2: MySQL -> PostgreSQL Data Accuracy")
    print("-" * 80)
    
    try:
        test_instance.test_mysql_to_postgres_accuracy()
        print("[PASSED] MySQL -> PostgreSQL accuracy test")
    except Exception as e:
        print(f"[FAILED] MySQL -> PostgreSQL accuracy test")
        print(f"   Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 80)
    print("[SUCCESS] ALL TESTS PASSED - 100% Data Accuracy Verified!")
    print("=" * 80)
    return True


if __name__ == '__main__':
    success = run_accuracy_tests()
    sys.exit(0 if success else 1)

