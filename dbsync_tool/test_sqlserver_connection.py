"""
Test SQL Server connection directly
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from connections.connectors import get_connector

try:
    print("Testing SQL Server connection...")
    print("Host: localhost")
    print("Port: 1433")
    print("Username: sa")
    print("Password: root")
    print()
    
    connector = get_connector(
        db_type='sqlserver',
        host='localhost',
        port=1433,
        username='sa',
        password='root',
        database_name=None
    )
    
    print("[OK] Connector created")
    
    print("\nTesting connection...")
    success = connector.test_connection()
    if success:
        print("[OK] Connection test successful")
    else:
        print("[FAIL] Connection test failed")
        sys.exit(1)
    
    print("\nListing databases...")
    databases = connector.list_databases()
    print(f"[OK] Found {len(databases)} databases:")
    for db in databases[:10]:  # Show first 10
        print(f"  - {db}")
    
    connector.close()
    print("\n[OK] All tests passed!")
    
except Exception as e:
    print(f"\n[ERROR] Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
