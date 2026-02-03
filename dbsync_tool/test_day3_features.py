"""
Quick test script for Day 3 features
Tests imports and basic functionality without requiring database
"""
import sys
import os

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
import django
django.setup()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all new modules can be imported"""
    print("Testing imports...")
    
    try:
        from connections.connectors.api_base import APIConnector
        print("OK: APIConnector imported successfully")
    except Exception as e:
        print(f"FAILED: Failed to import APIConnector: {e}")
        return False
    
    try:
        from connections.connectors.zoho import ZohoConnector, ZohoAuthenticator
        print("OK: ZohoConnector and ZohoAuthenticator imported successfully")
    except Exception as e:
        print(f"FAILED: Failed to import ZohoConnector: {e}")
        return False
    
    try:
        from sync_engine.data_transformer import DataTransformer
        print("OK: DataTransformer imported successfully")
    except Exception as e:
        print(f"FAILED: Failed to import DataTransformer: {e}")
        return False
    
    try:
        from connections.connectors import get_api_connector
        print("OK: get_api_connector factory function imported successfully")
    except Exception as e:
        print(f"FAILED: Failed to import get_api_connector: {e}")
        return False
    
    return True

def test_data_transformer():
    """Test DataTransformer functionality"""
    print("\nTesting DataTransformer...")
    
    try:
        from sync_engine.data_transformer import DataTransformer
        import pandas as pd
        
        # Test flatten_json with simple data
        data = [
            {'id': '1', 'name': 'Test 1', 'value': 100},
            {'id': '2', 'name': 'Test 2', 'value': 200}
        ]
        
        df = DataTransformer.flatten_json(data)
        assert isinstance(df, pd.DataFrame), "Result should be DataFrame"
        assert len(df) == 2, "Should have 2 rows"
        assert 'id' in df.columns, "Should have 'id' column"
        assert '_ingestion_timestamp' in df.columns, "Should have ingestion timestamp"
        print("OK: flatten_json works correctly")
        
        # Test prepare_for_database
        df_prepared = DataTransformer.prepare_for_database(df, 'clickhouse')
        assert isinstance(df_prepared, pd.DataFrame), "Result should be DataFrame"
        assert len(df_prepared) == 2, "Should still have 2 rows"
        print("OK: prepare_for_database works correctly")
        
        # Test column name cleaning
        cleaned = DataTransformer._clean_column_name('test.name.with.dots')
        assert cleaned == 'test_name_with_dots', f"Expected 'test_name_with_dots', got '{cleaned}'"
        print("OK: _clean_column_name works correctly")
        
        return True
    except Exception as e:
        print(f"FAILED: DataTransformer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_connector_base():
    """Test APIConnector base class"""
    print("\nTesting APIConnector base class...")
    
    try:
        from connections.connectors.api_base import APIConnector
        from abc import ABC
        
        # Check it's abstract
        assert issubclass(APIConnector, ABC), "APIConnector should be abstract"
        print("OK: APIConnector is abstract base class")
        
        # Check it has required methods
        required_methods = ['authenticate', 'get_available_modules', 'fetch_records', 'fetch_incremental_records']
        for method in required_methods:
            assert hasattr(APIConnector, method), f"APIConnector should have {method} method"
        print("OK: APIConnector has all required abstract methods")
        
        return True
    except Exception as e:
        print(f"FAILED: APIConnector base class test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_zoho_connector_structure():
    """Test ZohoConnector structure"""
    print("\nTesting ZohoConnector structure...")
    
    try:
        from connections.connectors.zoho import ZohoConnector, ZohoAuthenticator
        from connections.connectors.api_base import APIConnector
        
        # Check inheritance
        assert issubclass(ZohoConnector, APIConnector), "ZohoConnector should inherit from APIConnector"
        print("OK: ZohoConnector inherits from APIConnector")
        
        # Check it has required methods
        required_methods = ['authenticate', 'get_available_modules', 'fetch_records', 'fetch_incremental_records']
        for method in required_methods:
            assert hasattr(ZohoConnector, method), f"ZohoConnector should have {method} method"
        print("OK: ZohoConnector implements all required methods")
        
        # Check ZohoAuthenticator structure
        assert hasattr(ZohoAuthenticator, 'get_access_token'), "ZohoAuthenticator should have get_access_token method"
        print("OK: ZohoAuthenticator has required methods")
        
        return True
    except Exception as e:
        print(f"FAILED: ZohoConnector structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_factory_function():
    """Test factory function"""
    print("\nTesting factory function...")
    
    try:
        from connections.connectors import get_api_connector
        
        # Check function exists
        assert callable(get_api_connector), "get_api_connector should be callable"
        print("OK: get_api_connector factory function exists")
        
        return True
    except Exception as e:
        print(f"FAILED: Factory function test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("Day 3 Features Test Suite")
    print("=" * 60)
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("DataTransformer", test_data_transformer()))
    results.append(("APIConnector Base", test_api_connector_base()))
    results.append(("ZohoConnector Structure", test_zoho_connector_structure()))
    results.append(("Factory Function", test_factory_function()))
    
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    all_passed = True
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{name}: {status}")
        if not result:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("All tests PASSED!")
        sys.exit(0)
    else:
        print("Some tests FAILED!")
        sys.exit(1)
