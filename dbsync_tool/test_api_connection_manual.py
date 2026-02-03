"""
Manual test script for APIConnection model with real credentials
Run this script to test the APIConnection model with actual Zoho credentials
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.contrib.auth.models import User
from connections.models import APIConnection

# Real credentials
ZOHO_CLIENT_ID = "1000.0L3LLVLEKE9ELW7CE0I0KJ3K4FKBBT"
ZOHO_CLIENT_SECRET = "d99c479d4c0db451c653d8c380bf6a4c557a73528c"
ZOHO_REFRESH_TOKEN = "1000.2cbaa36345c6d04b699b0cb6740c21ef.149922195c479d83c84826653ff84ff4"
ZOHO_API_DOMAIN = "https://www.zohoapis.in"

def test_api_connection():
    """Test APIConnection creation and operations"""
    print("=" * 60)
    print("Testing APIConnection Model with Real Credentials")
    print("=" * 60)
    
    # Get or create test user
    user, created = User.objects.get_or_create(
        username='test_user',
        defaults={
            'email': 'test@example.com',
            'is_staff': True,
            'is_superuser': True
        }
    )
    if created:
        user.set_password('testpass123')
        user.save()
        print(f"[OK] Created test user: {user.username}")
    else:
        print(f"[OK] Using existing test user: {user.username}")
    
    # Test 1: Create APIConnection
    print("\n[Test 1] Creating APIConnection...")
    try:
        conn = APIConnection.objects.create(
            name='Manual Test Zoho Connection',
            api_type='zoho_crm',
            client_id=ZOHO_CLIENT_ID,
            client_secret=ZOHO_CLIENT_SECRET,
            refresh_token=ZOHO_REFRESH_TOKEN,
            api_domain=ZOHO_API_DOMAIN,
            tenant=user,
            created_by=user
        )
        print(f"[OK] APIConnection created successfully!")
        print(f"  - ID: {conn.id}")
        print(f"  - Name: {conn.name}")
        print(f"  - API Type: {conn.api_type}")
        print(f"  - API Domain: {conn.api_domain}")
        print(f"  - Token URL: {conn.token_url}")
    except Exception as e:
        print(f"✗ Failed to create APIConnection: {e}")
        return False
    
    # Test 2: Verify encryption
    print("\n[Test 2] Verifying encryption...")
    try:
        conn.refresh_from_db()
        if conn.client_secret.startswith('gAAAAAB'):
            print("[OK] Client secret is encrypted")
        else:
            print("[FAIL] Client secret is NOT encrypted")
            return False
        
        if conn.refresh_token.startswith('gAAAAAB'):
            print("[OK] Refresh token is encrypted")
        else:
            print("[FAIL] Refresh token is NOT encrypted")
            return False
    except Exception as e:
        print(f"[FAIL] Encryption verification failed: {e}")
        return False
    
    # Test 3: Test decryption
    print("\n[Test 3] Testing decryption...")
    try:
        decrypted_secret = conn.get_decrypted_client_secret()
        decrypted_token = conn.get_decrypted_refresh_token()
        
        if decrypted_secret == ZOHO_CLIENT_SECRET:
            print("[OK] Client secret decryption successful")
        else:
            print("[FAIL] Client secret decryption failed")
            return False
        
        if decrypted_token == ZOHO_REFRESH_TOKEN:
            print("[OK] Refresh token decryption successful")
        else:
            print("[FAIL] Refresh token decryption failed")
            return False
    except Exception as e:
        print(f"[FAIL] Decryption failed: {e}")
        return False
    
    # Test 4: Test get_connection_params
    print("\n[Test 4] Testing get_connection_params()...")
    try:
        params = conn.get_connection_params()
        print("[OK] Connection params retrieved successfully")
        print(f"  - Client ID: {params['client_id']}")
        print(f"  - Client Secret: {'*' * len(params['client_secret'])}")
        print(f"  - Refresh Token: {'*' * len(params['refresh_token'])}")
        print(f"  - API Domain: {params['api_domain']}")
        print(f"  - Token URL: {params['token_url']}")
        
        # Verify all keys are present
        required_keys = ['client_id', 'client_secret', 'refresh_token', 'api_domain', 'token_url']
        for key in required_keys:
            if key not in params:
                print(f"[FAIL] Missing key in params: {key}")
                return False
    except Exception as e:
        print(f"[FAIL] get_connection_params() failed: {e}")
        return False
    
    # Test 5: Test selected_modules
    print("\n[Test 5] Testing selected_modules...")
    try:
        modules = ['Leads', 'Contacts', 'Accounts']
        conn.selected_modules = modules
        conn.save()
        
        conn.refresh_from_db()
        if conn.selected_modules == modules:
            print(f"[OK] Selected modules saved and retrieved: {conn.selected_modules}")
        else:
            print(f"[FAIL] Selected modules mismatch: {conn.selected_modules} != {modules}")
            return False
    except Exception as e:
        print(f"[FAIL] Selected modules test failed: {e}")
        return False
    
    # Test 6: Test retrieval from database
    print("\n[Test 6] Testing database retrieval...")
    try:
        retrieved = APIConnection.objects.get(id=conn.id)
        if retrieved.name == conn.name:
            print("[OK] Connection retrieved successfully from database")
        else:
            print("[FAIL] Connection retrieval failed")
            return False
        
        # Test decryption after retrieval
        retrieved_secret = retrieved.get_decrypted_client_secret()
        if retrieved_secret == ZOHO_CLIENT_SECRET:
            print("[OK] Decryption works after database retrieval")
        else:
            print("[FAIL] Decryption failed after database retrieval")
            return False
    except Exception as e:
        print(f"[FAIL] Database retrieval test failed: {e}")
        return False
    
    # Test 7: Test unique constraint
    print("\n[Test 7] Testing unique constraint...")
    try:
        # Try to create duplicate name for same tenant
        try:
            duplicate = APIConnection.objects.create(
                name='Manual Test Zoho Connection',  # Same name
                api_type='zoho_crm',
                client_id=ZOHO_CLIENT_ID,
                client_secret=ZOHO_CLIENT_SECRET,
                refresh_token=ZOHO_REFRESH_TOKEN,
                api_domain=ZOHO_API_DOMAIN,
                tenant=user,  # Same tenant
                created_by=user
            )
            print("[FAIL] Unique constraint failed - duplicate created")
            return False
        except Exception:
            print("[OK] Unique constraint works - duplicate prevented")
    except Exception as e:
        print(f"[FAIL] Unique constraint test failed: {e}")
        return False
    
    # Test 8: Test test_connection stub
    print("\n[Test 8] Testing test_connection() stub...")
    try:
        success, message, modules = conn.test_connection()
        if not success and message == "Not implemented yet":
            print("[OK] test_connection() stub works correctly")
        else:
            print(f"[FAIL] test_connection() stub unexpected result: {success}, {message}")
    except Exception as e:
        print(f"[FAIL] test_connection() stub test failed: {e}")
        return False
    
    # Cleanup
    print("\n[Cleanup] Cleaning up test data...")
    try:
        APIConnection.objects.filter(name='Manual Test Zoho Connection').delete()
        print("[OK] Test data cleaned up")
    except Exception as e:
        print(f"[WARN] Cleanup warning: {e}")
    
    print("\n" + "=" * 60)
    print("All tests passed! [OK]")
    print("=" * 60)
    return True

if __name__ == '__main__':
    success = test_api_connection()
    sys.exit(0 if success else 1)
