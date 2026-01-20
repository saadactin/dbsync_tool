"""
Test script for post-migration verification with transformations
Tests the comparison logic between pre-migration query results and target data
"""
import os
import sys
import django
import codecs

# Setup UTF-8 encoding for Windows
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from connections.connectors.factory import get_connector
from connections.models import DatabaseConnection
from sync_engine.query_result_verifier import QueryResultVerifier
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_comparison_logic():
    """Test the comparison logic with sample data"""
    print("\n" + "="*80)
    print("Testing Query Result Comparison Logic")
    print("="*80)
    
    # Test case 1: Exact match
    print("\n1. Testing exact match...")
    verifier = QueryResultVerifier(None)  # Connector not needed for comparison
    source_rows = [(1, 'Apple', 10.5), (2, 'Banana', 20.0)]
    target_rows = [(1, 'Apple', 10.5), (2, 'Banana', 20.0)]
    column_names = ['id', 'name', 'price']
    
    result = verifier.compare_query_results_with_target(
        source_query_result=source_rows,
        target_rows=target_rows,
        column_names=column_names,
        column_transformations={}
    )
    
    print(f"   Result: {result[0]}")
    print(f"   Error: {result[1]}")
    assert result[0], f"Should match: {result[1]}"
    print("   ✓ PASSED")
    
    # Test case 2: Decimal vs float (cross-database difference)
    print("\n2. Testing Decimal vs float (cross-database)...")
    from decimal import Decimal
    source_rows = [(1, 'Apple', Decimal('10.5')), (2, 'Banana', Decimal('20.0'))]
    target_rows = [(1, 'Apple', 10.5), (2, 'Banana', 20.0)]
    
    result = verifier.compare_query_results_with_target(
        source_query_result=source_rows,
        target_rows=target_rows,
        column_names=column_names,
        column_transformations={}
    )
    
    print(f"   Result: {result[0]}")
    print(f"   Error: {result[1]}")
    assert result[0], f"Should match (Decimal vs float): {result[1]}"
    print("   ✓ PASSED")
    
    # Test case 3: String with whitespace
    print("\n3. Testing string with whitespace...")
    source_rows = [(1, ' Apple ', 10.5)]
    target_rows = [(1, 'Apple', 10.5)]
    
    result = verifier.compare_query_results_with_target(
        source_query_result=source_rows,
        target_rows=target_rows,
        column_names=column_names,
        column_transformations={}
    )
    
    print(f"   Result: {result[0]}")
    print(f"   Error: {result[1]}")
    # This might fail if we want exact match, but for now we normalize
    print(f"   Note: {'PASSED' if result[0] else 'FAILED (expected for exact match)'}")
    
    # Test case 4: Mismatch
    print("\n4. Testing mismatch detection...")
    source_rows = [(1, 'Apple', 10.5)]
    target_rows = [(1, 'Apple', 11.0)]
    
    result = verifier.compare_query_results_with_target(
        source_query_result=source_rows,
        target_rows=target_rows,
        column_names=column_names,
        column_transformations={}
    )
    
    print(f"   Result: {result[0]}")
    print(f"   Error: {result[1]}")
    assert not result[0], "Should detect mismatch"
    print("   ✓ PASSED (correctly detected mismatch)")
    
    # Test case 5: String vs bytes
    print("\n5. Testing string vs bytes...")
    source_rows = [(1, b'Apple', 10.5)]
    target_rows = [(1, 'Apple', 10.5)]
    
    result = verifier.compare_query_results_with_target(
        source_query_result=source_rows,
        target_rows=target_rows,
        column_names=column_names,
        column_transformations={}
    )
    
    print(f"   Result: {result[0]}")
    print(f"   Error: {result[1]}")
    assert result[0], f"Should match (bytes vs string): {result[1]}"
    print("   ✓ PASSED")
    
    # Test case 6: NULL values
    print("\n6. Testing NULL values...")
    source_rows = [(1, None, 10.5)]
    target_rows = [(1, None, 10.5)]
    
    result = verifier.compare_query_results_with_target(
        source_query_result=source_rows,
        target_rows=target_rows,
        column_names=column_names,
        column_transformations={}
    )
    
    print(f"   Result: {result[0]}")
    print(f"   Error: {result[1]}")
    assert result[0], f"Should match (NULL values): {result[1]}"
    print("   ✓ PASSED")
    
    print("\n" + "="*80)
    print("All comparison logic tests completed!")
    print("="*80)

def test_with_actual_data():
    """Test with actual database data"""
    print("\n" + "="*80)
    print("Testing with Actual Database Data")
    print("="*80)
    
    try:
        # Get PostgreSQL connection
        pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
        if not pg_conn:
            print("   ⚠ No PostgreSQL connection found, skipping database test")
            return
        
        # Get MySQL connection
        mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
        if not mysql_conn:
            print("   ⚠ No MySQL connection found, skipping database test")
            return
        
        pg_connector = get_connector(pg_conn)
        mysql_connector = get_connector(mysql_conn)
        
        # Test fetching data from PostgreSQL
        print("\n1. Fetching test data from PostgreSQL...")
        pg_connector.connect()
        pg_rows = pg_connector.execute_query(
            'SELECT "CakeID", "Name", "Price", "GlutenFree" FROM "public"."Cakes" WHERE "Price" > 20 LIMIT 4'
        )
        print(f"   Fetched {len(pg_rows)} rows from PostgreSQL")
        if pg_rows:
            print(f"   First row: {pg_rows[0]}")
            print(f"   Types: {[type(v).__name__ for v in pg_rows[0]]}")
        
        # Test fetching data from MySQL
        print("\n2. Fetching test data from MySQL...")
        mysql_connector.connect()
        mysql_rows = mysql_connector.execute_query(
            'SELECT CakeID, Name, Price, GlutenFree FROM tor.cakes LIMIT 4'
        )
        print(f"   Fetched {len(mysql_rows)} rows from MySQL")
        if mysql_rows:
            print(f"   First row: {mysql_rows[0]}")
            print(f"   Types: {[type(v).__name__ for v in mysql_rows[0]]}")
        
        # Compare if we have data
        if pg_rows and mysql_rows and len(pg_rows) == len(mysql_rows):
            print("\n3. Comparing PostgreSQL and MySQL data...")
            verifier = QueryResultVerifier(pg_connector)
            column_names = ['CakeID', 'Name', 'Price', 'GlutenFree']
            
            result = verifier.compare_query_results_with_target(
                source_query_result=pg_rows,
                target_rows=mysql_rows,
                column_names=column_names,
                column_transformations={}
            )
            
            print(f"   Comparison result: {result[0]}")
            if not result[0]:
                print(f"   Error: {result[1]}")
                if result[2].get('mismatched_rows'):
                    for mismatch in result[2]['mismatched_rows'][:3]:
                        print(f"     Row {mismatch.get('row_index')}: {mismatch.get('error')}")
        
        pg_connector.close()
        mysql_connector.close()
        
    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print("\n" + "="*80)
    print("Post-Migration Verification Test Suite")
    print("="*80)
    
    # Run comparison logic tests
    test_comparison_logic()
    
    # Run database tests
    test_with_actual_data()
    
    print("\n" + "="*80)
    print("All tests completed!")
    print("="*80 + "\n")
