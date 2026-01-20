"""
Comprehensive test for both PostgreSQL → MySQL and MySQL → PostgreSQL
"""
import os
import sys
import django
import codecs

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from connections.connectors.factory import get_connector
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.full_sync import FullSyncExecutor
from django.contrib.auth.models import User
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_both_directions():
    """Test both PostgreSQL → MySQL and MySQL → PostgreSQL"""
    print("\n" + "="*80)
    print("Testing Both Directions: PostgreSQL ↔ MySQL")
    print("="*80)
    
    results = {'pg_to_mysql': False, 'mysql_to_pg': False}
    
    # Get connections
    mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
    pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
    
    if not mysql_conn or not pg_conn:
        print("   ✗ Connections not found")
        return False
    
    user = User.objects.first()
    if not user:
        print("   ✗ No user found")
        return False
    
    tenant = mysql_conn.tenant if hasattr(mysql_conn, 'tenant') and mysql_conn.tenant else None
    
    print(f"\n✓ Source 1: {pg_conn.name} (PostgreSQL)")
    print(f"✓ Target 1: {mysql_conn.name} (MySQL)")
    print(f"✓ Source 2: {mysql_conn.name} (MySQL)")
    print(f"✓ Target 2: {pg_conn.name} (PostgreSQL)")
    
    # Test 1: PostgreSQL → MySQL
    print("\n" + "="*80)
    print("Test 1: PostgreSQL → MySQL")
    print("="*80)
    try:
        pg_connector = get_connector(pg_conn)
        mysql_connector = get_connector(mysql_conn)
        
        pg_connector.connect()
        mysql_connector.connect()
        
        pg_schema = pg_conn.database_name or 'public'
        test_table = 'Cakes'
        
        # Create sync job
        job1, _ = SyncJob.objects.get_or_create(
            name='test_pg_to_mysql_comprehensive',
            defaults={
                'source_connection': pg_conn,
                'target_connection': mysql_conn,
                'sync_type': 'full',
                'created_by': user
            }
        )
        
        execution1 = SyncExecution.objects.create(job=job1)
        
        # Create job table with WHERE clause
        job_table1, _ = SyncJobTable.objects.get_or_create(
            job=job1,
            schema_name=pg_schema,
            table_name=test_table,
            defaults={
                'is_enabled': True,
                'transformation_query': 'Price > 20',
                'column_transformations': {}
            }
        )
        job_table1.is_enabled = True
        job_table1.transformation_query = 'Price > 20'
        job_table1.save()
        
        # Truncate target
        mysql_schema = mysql_conn.database_name or 'tor'
        try:
            mysql_connector.truncate_table(mysql_schema, test_table.lower())
        except:
            pass
        
        executor1 = FullSyncExecutor(job1, execution1, pg_connector, mysql_connector)
        executor1.sync_table(job_table1)
        
        mysql_row_count = mysql_connector.get_row_count(mysql_schema, test_table.lower())
        print(f"✓ PostgreSQL → MySQL: {mysql_row_count} rows migrated")
        results['pg_to_mysql'] = True
        
    except Exception as e:
        print(f"✗ PostgreSQL → MySQL failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: MySQL → PostgreSQL
    print("\n" + "="*80)
    print("Test 2: MySQL → PostgreSQL")
    print("="*80)
    try:
        # Create sync job
        job2, _ = SyncJob.objects.get_or_create(
            name='test_mysql_to_pg_comprehensive',
            defaults={
                'source_connection': mysql_conn,
                'target_connection': pg_conn,
                'sync_type': 'full',
                'created_by': user
            }
        )
        
        execution2 = SyncExecution.objects.create(job=job2)
        
        # Create job table with WHERE clause
        job_table2, _ = SyncJobTable.objects.get_or_create(
            job=job2,
            schema_name=mysql_schema,
            table_name=test_table.lower(),
            defaults={
                'is_enabled': True,
                'transformation_query': 'Price > 20',
                'column_transformations': {}
            }
        )
        job_table2.is_enabled = True
        job_table2.transformation_query = 'Price > 20'
        job_table2.save()
        
        # Truncate target
        try:
            pg_connector.truncate_table(pg_schema, test_table)
        except:
            pass
        
        executor2 = FullSyncExecutor(job2, execution2, mysql_connector, pg_connector)
        executor2.sync_table(job_table2)
        
        pg_row_count = pg_connector.get_row_count(pg_schema, test_table)
        print(f"✓ MySQL → PostgreSQL: {pg_row_count} rows migrated")
        results['mysql_to_pg'] = True
        
    except Exception as e:
        print(f"✗ MySQL → PostgreSQL failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Summary
    print("\n" + "="*80)
    print("Test Summary")
    print("="*80)
    print(f"PostgreSQL → MySQL: {'✓ PASSED' if results['pg_to_mysql'] else '✗ FAILED'}")
    print(f"MySQL → PostgreSQL: {'✓ PASSED' if results['mysql_to_pg'] else '✗ FAILED'}")
    print("="*80)
    
    return all(results.values())

if __name__ == '__main__':
    success = test_both_directions()
    sys.exit(0 if success else 1)
