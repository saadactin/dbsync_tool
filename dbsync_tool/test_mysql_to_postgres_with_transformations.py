"""
Test MySQL → PostgreSQL sync with transformations (WHERE clauses)
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

def test_mysql_to_postgres_with_where_clause():
    """Test MySQL to PostgreSQL sync with WHERE clause transformation"""
    print("\n" + "="*80)
    print("Testing MySQL → PostgreSQL Migration with WHERE Clause")
    print("="*80)
    
    try:
        # Get connections
        mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
        pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
        
        if not mysql_conn or not pg_conn:
            print("   ✗ Connections not found")
            return False
        
        print(f"\n✓ Source: {mysql_conn.name} (MySQL)")
        print(f"✓ Target: {pg_conn.name} (PostgreSQL)")
        
        # Get connectors
        mysql_connector = get_connector(mysql_conn)
        pg_connector = get_connector(pg_conn)
        
        mysql_connector.connect()
        pg_connector.connect()
        
        mysql_schema = mysql_conn.database_name or 'tor'
        test_table = 'cakes'
        
        # Get user
        user = User.objects.first()
        if not user:
            print("   ✗ No user found")
            return False
        
        # Get tenant
        tenant = mysql_conn.tenant if hasattr(mysql_conn, 'tenant') and mysql_conn.tenant else None
        
        # Create sync job
        job, _ = SyncJob.objects.get_or_create(
            name='test_mysql_to_postgres_with_where',
            defaults={
                'source_connection': mysql_conn,
                'target_connection': pg_conn,
                'sync_type': 'full',
                'created_by': user
            }
        )
        
        # Create execution
        execution_kwargs = {'job': job}
        if tenant and hasattr(SyncExecution, 'tenant'):
            execution_kwargs['tenant'] = tenant
        execution = SyncExecution.objects.create(**execution_kwargs)
        
        # Create job table with WHERE clause
        job_table, _ = SyncJobTable.objects.get_or_create(
            job=job,
            schema_name=mysql_schema,
            table_name=test_table,
            defaults={
                'is_enabled': True,
                'transformation_query': 'Price > 20',  # WHERE clause
                'column_transformations': {}
            }
        )
        job_table.is_enabled = True
        job_table.transformation_query = 'Price > 20'
        job_table.save()
        
        print(f"\n✓ Job table created with WHERE clause: Price > 20")
        
        # Truncate target table first
        pg_schema = mysql_schema
        try:
            pg_connector.truncate_table(pg_schema, test_table)
            print(f"✓ Truncated target table {pg_schema}.{test_table}")
        except:
            pass  # Table might not exist yet
        
        # Create executor
        executor = FullSyncExecutor(
            job=job,
            execution=execution,
            source_connector=mysql_connector,
            target_connector=pg_connector
        )
        
        # Execute sync
        print(f"\nExecuting sync for {job_table.schema_name}.{job_table.table_name} with WHERE Price > 20...")
        executor.sync_table(job_table)
        
        print(f"✓ Sync completed successfully!")
        
        # Verify data was migrated correctly
        pg_row_count = pg_connector.get_row_count(pg_schema, test_table)
        print(f"✓ Target table has {pg_row_count} rows")
        
        # Verify only rows with Price > 20 were migrated
        from sync_engine.query_builder import QueryBuilder
        query_builder = QueryBuilder()
        
        target_query = query_builder.build_select_query(
            connector=pg_connector,
            schema=pg_schema,
            table=test_table,
            columns=None,
            order_by='CakeID'
        )
        
        target_rows = pg_connector.fetch_batch(target_query, batch_size=100, offset=0)
        print(f"✓ Verified: Fetched {len(target_rows)} rows from target")
        
        if target_rows:
            print(f"✓ First target row: {target_rows[0]}")
            # Check that all prices are > 20
            for row in target_rows:
                price_idx = 4  # Price is 5th column (index 4)
                if len(row) > price_idx:
                    price = float(row[price_idx]) if row[price_idx] else 0
                    if price <= 20:
                        print(f"   ✗ ERROR: Found row with Price={price} (should be > 20)")
                        return False
        
        print(f"✓ All rows have Price > 20 - transformation working correctly!")
        
        mysql_connector.close()
        pg_connector.close()
        
        print("\n" + "="*80)
        print("✓ MySQL → PostgreSQL with WHERE clause test passed!")
        print("="*80)
        return True
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_mysql_to_postgres_with_where_clause()
    sys.exit(0 if success else 1)
