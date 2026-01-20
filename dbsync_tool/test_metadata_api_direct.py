"""
Direct test of metadata API to debug loading issue
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from metadata.views import load_schemas_view
import json

def test_metadata_api():
    """Test metadata API directly"""
    print("\n" + "="*60)
    print("TESTING METADATA API DIRECTLY")
    print("="*60)
    
    # Get existing connection
    pg_conn = DatabaseConnection.objects.filter(
        name__icontains='pg2'
    ).first() or DatabaseConnection.objects.filter(
        db_type='postgres'
    ).first()
    
    if not pg_conn:
        print("[ERROR] No PostgreSQL connection found")
        return False
    
    print(f"\nFound connection: {pg_conn.name} ({pg_conn.id})")
    print(f"  Host: {pg_conn.host}")
    print(f"  Database: {pg_conn.database_name}")
    print(f"  Tenant: {pg_conn.tenant_id}")
    
    # Get or create a user with access
    user = pg_conn.created_by
    if not user:
        print("[ERROR] Connection has no creator")
        return False
    
    print(f"\nUsing user: {user.username}")
    
    # Create request
    factory = RequestFactory()
    url = f'/metadata/api/{pg_conn.id}/schemas/?use_cache=false'
    request = factory.get(url)
    request.user = user
    
    print(f"\nTesting URL: {url}")
    print(f"Request user: {request.user.username}")
    
    try:
        import time
        start_time = time.time()
        response = load_schemas_view(request, connection_id=str(pg_conn.id))
        duration = time.time() - start_time
        
        print(f"\nResponse time: {duration:.2f} seconds")
        print(f"Status code: {response.status_code}")
        
        # Parse response (DRF Response object)
        if hasattr(response, 'data'):
            response_data = response.data
        else:
            response_data = json.loads(response.content)
        print(f"Response data keys: {list(response_data.keys())}")
        
        if response.status_code == 200:
            if response_data.get('success'):
                schemas = response_data.get('data', [])
                print(f"[OK] Successfully loaded {len(schemas)} schemas")
                print(f"  Schemas: {[s.get('name') for s in schemas[:5]]}")
                return True
            else:
                print(f"[ERROR] API returned success=false")
                print(f"  Error: {response_data.get('error', 'Unknown error')}")
        else:
            print(f"[ERROR] HTTP {response.status_code}")
            print(f"  Response: {response_data}")
            
    except Exception as e:
        print(f"[ERROR] Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return False

if __name__ == '__main__':
    test_metadata_api()
