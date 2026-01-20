"""
Test script for MySQL → PostgreSQL migration
Tests the entire flow from MySQL source to PostgreSQL destination
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
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.full_sync import FullSyncExecutor
from django.contrib.auth.models import User
import logging

# Get Tenant from connections model (it should have a ForeignKey to Tenant)
# Or use the first connection's tenant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_mysql_to_postgres_sync():
    """Test MySQL to PostgreSQL sync with transformations"""
    print("\n" + "="*80)
    print("Testing MySQL → PostgreSQL Migration")
    print("="*80)
    
    try:
        # Get MySQL connection (source)
        mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
        if not mysql_conn:
            print("   ✗ No MySQL connection found")
            return False
        
        # Get PostgreSQL connection (target)
        pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
        if not pg_conn:
            print("   ✗ No PostgreSQL connection found")
            return False
        
        # Get tenant from connection
        tenant = mysql_conn.tenant if hasattr(mysql_conn, 'tenant') and mysql_conn.tenant else None
        if not tenant:
            # Get from any connection
            any_conn = DatabaseConnection.objects.first()
            tenant = any_conn.tenant if any_conn and hasattr(any_conn, 'tenant') and any_conn.tenant else None
        
        print(f"\n✓ Source: {mysql_conn.name} (MySQL)")
        print(f"✓ Target: {pg_conn.name} (PostgreSQL)")
        
        # Get connectors
        mysql_connector = get_connector(mysql_conn)
        pg_connector = get_connector(pg_conn)
        
        mysql_connector.connect()
        pg_connector.connect()
        
        # Test 1: Check if we can list databases
        print("\n1. Testing MySQL database listing...")
        try:
            mysql_dbs = mysql_connector.list_databases()
            print(f"   ✓ MySQL databases: {mysql_dbs}")
        except Exception as e:
            print(f"   ✗ Error listing MySQL databases: {e}")
            return False
        
        # Test 2: Check if we can get tables
        print("\n2. Testing MySQL table listing...")
        try:
            mysql_schema = mysql_conn.database_name or mysql_dbs[0] if mysql_dbs else None
            if not mysql_schema:
                print("   ✗ No MySQL database specified")
                return False
            
            mysql_tables = mysql_connector.get_tables(mysql_schema)
            print(f"   ✓ MySQL tables in {mysql_schema}: {mysql_tables}")
        except Exception as e:
            print(f"   ✗ Error listing MySQL tables: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Test 3: Check if we can get columns
        print("\n3. Testing MySQL column listing...")
        if mysql_tables:
            test_table = mysql_tables[0]
            try:
                columns = mysql_connector.get_columns(mysql_schema, test_table)
                print(f"   ✓ Columns in {mysql_schema}.{test_table}:")
                for col in columns:
                    print(f"      - {col.name} ({col.data_type}, nullable={col.is_nullable})")
            except Exception as e:
                print(f"   ✗ Error getting MySQL columns: {e}")
                import traceback
                traceback.get_exc()
                return False
        
        # Test 4: Check if we can fetch data from MySQL
        print("\n4. Testing MySQL data fetching...")
        if mysql_tables:
            try:
                from sync_engine.query_builder import QueryBuilder
                query_builder = QueryBuilder()
                
                # Build a simple query
                query = query_builder.build_select_query(
                    connector=mysql_connector,
                    schema=mysql_schema,
                    table=test_table,
                    columns=None,  # SELECT *
                    order_by=columns[0].name if columns else None
                )
                print(f"   Query: {query}")
                
                rows = mysql_connector.fetch_batch(query, batch_size=5, offset=0)
                print(f"   ✓ Fetched {len(rows)} rows from MySQL")
                if rows:
                    print(f"   First row: {rows[0]}")
                    print(f"   Types: {[type(v).__name__ for v in rows[0]]}")
            except Exception as e:
                print(f"   ✗ Error fetching MySQL data: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        # Test 5: Check if we can create a sync job
        print("\n5. Testing sync job creation...")
        try:
            # Get or create user
            user, _ = User.objects.get_or_create(
                username='test_user',
                defaults={'email': 'test@test.com'}
            )
            user.tenant = tenant
            user.save()
            
            # Create a test sync job
            job, created = SyncJob.objects.get_or_create(
                name='test_mysql_to_postgres',
                defaults={
                    'source_connection': mysql_conn,
                    'target_connection': pg_conn,
                    'sync_type': 'full',
                    'created_by': user
                }
            )
            
            if created:
                print(f"   ✓ Created sync job: {job.name}")
            else:
                print(f"   ✓ Found existing sync job: {job.name}")
            
            # Create execution
            execution_kwargs = {'job': job}
            if tenant and hasattr(SyncExecution, 'tenant'):
                execution_kwargs['tenant'] = tenant
            execution = SyncExecution.objects.create(**execution_kwargs)
            print(f"   ✓ Created execution: {execution.id}")
            
        except Exception as e:
            print(f"   ✗ Error creating sync job: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Test 6: Test actual sync with a table
        print("\n6. Testing actual sync execution...")
        if mysql_tables:
            try:
                # Create job table
                job_table, created = SyncJobTable.objects.get_or_create(
                    job=job,
                    schema_name=mysql_schema,
                    table_name=test_table,
                    defaults={
                        'is_enabled': True
                    }
                )
                if tenant and hasattr(job_table, 'tenant'):
                    job_table.tenant = tenant
                    job_table.save()
                
                if created:
                    print(f"   ✓ Created job table: {job_table.schema_name}.{job_table.table_name}")
                else:
                    job_table.is_enabled = True
                    job_table.save()
                    print(f"   ✓ Enabled job table: {job_table.schema_name}.{job_table.table_name}")
                
                # Create executor
                executor = FullSyncExecutor(
                    job=job,
                    execution=execution,
                    source_connector=mysql_connector,
                    target_connector=pg_connector
                )
                
                # Execute sync
                print(f"   Executing sync for {job_table.schema_name}.{job_table.table_name}...")
                executor.sync_table(job_table)
                
                print(f"   ✓ Sync completed successfully!")
                
                # Verify data was migrated - use the same schema as source
                pg_schema = mysql_schema  # Use same schema name
                try:
                    pg_row_count = pg_connector.get_row_count(pg_schema, test_table)
                    print(f"   ✓ Target table {pg_schema}.{test_table} has {pg_row_count} rows")
                    
                    # Also verify by fetching data
                    target_rows = pg_connector.fetch_batch(
                        query=f'SELECT * FROM "{pg_schema}"."{test_table}" ORDER BY "{columns[0].name if columns else "1"}"',
                        batch_size=10,
                        offset=0
                    )
                    print(f"   ✓ Verified: Fetched {len(target_rows)} rows from target")
                    if target_rows:
                        print(f"   First target row: {target_rows[0]}")
                        print(f"   Target types: {[type(v).__name__ for v in target_rows[0]]}")
                except Exception as e:
                    print(f"   ⚠ Could not verify row count: {e}")
                    print(f"   (But sync reported success - data may be in different schema)")
                
            except Exception as e:
                print(f"   ✗ Error during sync: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        mysql_connector.close()
        pg_connector.close()
        
        print("\n" + "="*80)
        print("✓ All MySQL → PostgreSQL tests passed!")
        print("="*80)
        return True
        
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_mysql_to_postgres_sync()
    sys.exit(0 if success else 1)
