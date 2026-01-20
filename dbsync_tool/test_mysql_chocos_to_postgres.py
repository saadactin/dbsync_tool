"""
Test MySQL chocos table → PostgreSQL with WHERE clause "price" > 150
This tests the exact scenario the user reported
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

def test_mysql_chocos_with_where():
    """Test MySQL chocos table → PostgreSQL with WHERE "price" > 150"""
    print("\n" + "="*80)
    print("Testing MySQL chocos → PostgreSQL with WHERE \"price\" > 150")
    print("="*80)
    
    try:
        mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
        pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
        
        if not mysql_conn or not pg_conn:
            print("   ✗ Connections not found")
            return False
        
        print(f"\n✓ Source: {mysql_conn.name} (MySQL)")
        print(f"✓ Target: {pg_conn.name} (PostgreSQL)")
        
        mysql_connector = get_connector(mysql_conn)
        pg_connector = get_connector(pg_conn)
        
        mysql_connector.connect()
        pg_connector.connect()
        
        mysql_schema = mysql_conn.database_name or 'tor'
        test_table = 'chocos'
        
        # First, check how many rows match the WHERE clause
        from sync_engine.query_builder import QueryBuilder
        query_builder = QueryBuilder()
        
        # Test the WHERE clause with PostgreSQL-style quotes (what user entered)
        test_where = '"price" > 150'
        print(f"\n1. Testing WHERE clause: {test_where}")
        
        # Build query to see how many rows match
        query = query_builder.build_select_query(
            connector=mysql_connector,
            schema=mysql_schema,
            table=test_table,
            columns=None,
            where_clause=test_where
        )
        print(f"   Generated query: {query}")
        
        rows = mysql_connector.fetch_batch(query, batch_size=100, offset=0)
        print(f"   ✓ Rows matching WHERE clause: {len(rows)}")
        if rows:
            print(f"   First matching row: {rows[0]}")
        
        # Now test the sync
        user = User.objects.first()
        if not user:
            print("   ✗ No user found")
            return False
        
        tenant = mysql_conn.tenant if hasattr(mysql_conn, 'tenant') and mysql_conn.tenant else None
        
        # Create sync job
        job, _ = SyncJob.objects.get_or_create(
            name='test_mysql_chocos_to_postgres',
            defaults={
                'source_connection': mysql_conn,
                'target_connection': pg_conn,
                'sync_type': 'full',
                'created_by': user
            }
        )
        
        execution_kwargs = {'job': job}
        if tenant and hasattr(SyncExecution, 'tenant'):
            execution_kwargs['tenant'] = tenant
        execution = SyncExecution.objects.create(**execution_kwargs)
        
        # Create job table with WHERE clause (PostgreSQL-style quotes as user entered)
        job_table, _ = SyncJobTable.objects.get_or_create(
            job=job,
            schema_name=mysql_schema,
            table_name=test_table,
            defaults={
                'is_enabled': True,
                'transformation_query': test_where,  # "price" > 150
                'column_transformations': {}
            }
        )
        job_table.is_enabled = True
        job_table.transformation_query = test_where
        job_table.save()
        
        print(f"\n2. Created job table with WHERE clause: {test_where}")
        
        # Truncate target
        pg_schema = mysql_schema
        try:
            pg_connector.truncate_table(pg_schema, test_table)
            print(f"✓ Truncated target table {pg_schema}.{test_table}")
        except:
            print(f"   (Target table doesn't exist yet, will be created)")
        
        # Execute sync
        print(f"\n3. Executing sync...")
        executor = FullSyncExecutor(job, execution, mysql_connector, pg_connector)
        executor.sync_table(job_table)
        
        # Verify
        pg_row_count = pg_connector.get_row_count(pg_schema, test_table)
        print(f"\n✓ Sync completed!")
        print(f"✓ Rows migrated: {pg_row_count}")
        
        if pg_row_count > 0:
            target_query = query_builder.build_select_query(
                connector=pg_connector,
                schema=pg_schema,
                table=test_table,
                columns=None,
                order_by='choco_id'
            )
            target_rows = pg_connector.fetch_batch(target_query, batch_size=10, offset=0)
            print(f"✓ Verified: Fetched {len(target_rows)} rows from target")
            if target_rows:
                print(f"   First row: {target_rows[0]}")
        
        mysql_connector.close()
        pg_connector.close()
        
        if pg_row_count > 0:
            print(f"\n{'='*80}")
            print("✓ SUCCESS: Data migrated successfully!")
            print(f"{'='*80}")
            return True
        else:
            print(f"\n{'='*80}")
            print("⚠ WARNING: No rows migrated (WHERE clause may have filtered all rows)")
            print(f"{'='*80}")
            return False
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_mysql_chocos_with_where()
    sys.exit(0 if success else 1)
