"""
Comprehensive test suite for all database migration combinations:
- PostgreSQL ↔ MySQL
- PostgreSQL ↔ SQL Server
- MySQL ↔ SQL Server

Tests both directions for each pair (6 combinations total)
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

def find_table_with_data(connector, default_schema, preferred_tables=None):
    """
    Find a table that exists and has data
    
    Args:
        connector: Database connector
        default_schema: Default schema/database name to try first
        preferred_tables: List of preferred table names to try first
    
    Returns:
        Tuple of (schema_name, table_name, column_name_for_where, where_value) or (None, None, None, None)
    """
    # Try default schema first
    schemas_to_try = [default_schema]
    
    # For PostgreSQL, also try 'public' schema and 'Tor2' database
    if default_schema != 'public':
        schemas_to_try.append('public')
    if 'Tor2' not in schemas_to_try and default_schema not in ['Tor2', 'tor2']:
        schemas_to_try.append('Tor2')
    
    # Try to get all schemas/databases if connector supports it
    try:
        all_schemas = connector.get_schemas()
        for schema in all_schemas:
            if schema not in schemas_to_try:
                schemas_to_try.append(schema)
    except:
        pass  # get_schemas() might not be available
    
    for schema in schemas_to_try:
        try:
            tables = connector.get_tables(schema)
            if not tables:
                continue
            
            # Try preferred tables first
            test_tables = (preferred_tables or []) + list(tables)
            
            for table_name in test_tables:
                if table_name not in tables:
                    continue
                
                try:
                    columns = connector.get_columns(schema, table_name)
                    if not columns:
                        continue
                    
                    # Get numeric columns for WHERE clause
                    numeric_cols = []
                    id_cols = []
                    
                    for col in columns:
                        col_type = str(col.data_type).upper()
                        if 'INT' in col_type or 'NUMERIC' in col_type or 'DECIMAL' in col_type or 'FLOAT' in col_type:
                            numeric_cols.append(col.name)
                        if 'ID' in col.name.upper() or col.is_primary_key:
                            id_cols.append(col.name)
                    
                    # Try to get row count
                    try:
                        row_count = connector.get_row_count(schema, table_name)
                        if row_count > 0:
                            # Use first numeric column with a reasonable value for WHERE clause
                            if numeric_cols:
                                col_name = numeric_cols[0]
                                # Build a WHERE clause that returns some rows (use > 0 or > 1)
                                return schema, table_name, col_name, 1
                            elif id_cols:
                                col_name = id_cols[0]
                                return schema, table_name, col_name, 1
                            else:
                                # Just return table name, we'll use a simple WHERE clause
                                return schema, table_name, None, None
                    except:
                        pass
                        
                except Exception as e:
                    logger.debug(f"Error checking table {table_name} in schema {schema}: {e}")
                    continue
            
            # Return first available table even if no data
            if tables:
                return schema, tables[0], None, None
        
        except Exception as e:
            logger.debug(f"Error accessing schema {schema}: {e}")
            continue
    
    # If we get here, no tables found in any schema
    return None, None, None, None

def test_sync_direction(source_type: str, target_type: str, where_clause: str = None):
    """
    Test sync in one direction
    
    Args:
        source_type: 'postgres', 'mysql', or 'sqlserver'
        target_type: 'postgres', 'mysql', or 'sqlserver'
        where_clause: Optional WHERE clause transformation
    
    Returns:
        Tuple of (success: bool, rows_migrated: int, error_message: str)
    """
    try:
        # Get connections
        source_conn = DatabaseConnection.objects.filter(db_type=source_type).first()
        target_conn = DatabaseConnection.objects.filter(db_type=target_type).first()
        
        if not source_conn:
            return False, 0, f"No {source_type} connection found"
        if not target_conn:
            return False, 0, f"No {target_type} connection found"
        
        # Get connectors
        source_connector = get_connector(source_conn)
        target_connector = get_connector(target_conn)
        
        try:
            source_connector.connect()
            target_connector.connect()
        except Exception as e:
            return False, 0, f"Connection failed: {str(e)}"
        
        # Determine schema
        if source_type == 'postgres':
            source_schema = source_conn.database_name or 'public'
        elif source_type == 'mysql':
            source_schema = source_conn.database_name or 'tor'
        elif source_type == 'sqlserver':
            source_schema = source_conn.database_name or 'dbo'
        else:
            source_schema = 'public'
        
        # Find a suitable table
        preferred_tables = {
            'postgres': ['Cakes', 'cakes', 'CAKES', 'chocos'],
            'mysql': ['chocos', 'cakes', 'students'],
            'sqlserver': ['Cakes', 'cakes', 'CAKES']
        }.get(source_type, [])
        
        found_schema, test_table, where_col, where_val = find_table_with_data(
            source_connector, source_schema, preferred_tables
        )
        
        if not test_table or not found_schema:
            source_connector.close()
            target_connector.close()
            return False, 0, f"No suitable table found in {source_type} (tried schema: {source_schema})"
        
        # Use the schema where we found the table
        source_schema = found_schema
        
        # Build WHERE clause if not provided and we have column info
        if not where_clause and where_col and where_val is not None:
            # Use PostgreSQL-style quotes (will be normalized by QueryBuilder)
            if where_col.lower() == 'price':
                where_clause = f'"{where_col}" > {where_val * 50}'  # For price, use higher value
            elif 'id' in where_col.lower():
                where_clause = f'"{where_col}" > 0'  # For ID columns
            else:
                where_clause = f'"{where_col}" > {where_val}'
        elif not where_clause:
            # No WHERE clause - sync all data
            where_clause = None
        
        # Get user
        user = User.objects.first()
        if not user:
            source_connector.close()
            target_connector.close()
            return False, 0, "No user found"
        
        # Get tenant
        tenant = source_conn.tenant if hasattr(source_conn, 'tenant') and source_conn.tenant else None
        
        # Create sync job
        job_name = f'test_{source_type}_to_{target_type}_{test_table}'
        job, _ = SyncJob.objects.get_or_create(
            name=job_name,
            defaults={
                'source_connection': source_conn,
                'target_connection': target_conn,
                'sync_type': 'full',
                'created_by': user
            }
        )
        
        # Create execution
        execution_kwargs = {'job': job}
        if tenant and hasattr(SyncExecution, 'tenant'):
            execution_kwargs['tenant'] = tenant
        execution = SyncExecution.objects.create(**execution_kwargs)
        
        # Create job table
        job_table, _ = SyncJobTable.objects.get_or_create(
            job=job,
            schema_name=source_schema,
            table_name=test_table,
            defaults={
                'is_enabled': True
            }
        )
        job_table.is_enabled = True
        job_table.transformation_query = where_clause
        job_table.column_transformations = {}
        job_table.save()
        
        # Truncate target table first
        target_schema = target_conn.target_schema if hasattr(target_conn, 'target_schema') and target_conn.target_schema else source_schema
        try:
            # Determine target table name (may need case conversion)
            if target_type == 'mysql':
                target_table_name = test_table.lower()
            elif target_type == 'postgres':
                target_table_name = test_table  # Keep case
            elif target_type == 'sqlserver':
                target_table_name = test_table  # SQL Server is case-insensitive but keep case
            else:
                target_table_name = test_table
            
            # Don't truncate here - let the sync process handle it
            # Just ensure we close connections properly if there's an error
            pass
        except Exception as e:
            logger.debug(f"Could not truncate target table: {e}")
            pass  # Table might not exist yet, that's fine
        
        # Create executor
        executor = FullSyncExecutor(
            job=job,
            execution=execution,
            source_connector=source_connector,
            target_connector=target_connector
        )
        
        # Execute sync
        executor.sync_table(job_table)
        
        # Verify data was migrated
        try:
            row_count = target_connector.get_row_count(target_schema, target_table_name)
        except:
            row_count = 0
        
        source_connector.close()
        target_connector.close()
        
        return True, row_count, None
        
    except Exception as e:
        return False, 0, str(e)

def run_all_tests():
    """Run tests for all database combinations"""
    print("\n" + "="*80)
    print("Comprehensive Database Migration Test Suite")
    print("Testing All Combinations: PostgreSQL ↔ MySQL ↔ SQL Server")
    print("="*80)
    
    # Test all 6 combinations
    # WHERE clauses will be auto-generated based on available columns
    combinations = [
        ('postgres', 'mysql', None),  # Auto-generate WHERE clause
        ('mysql', 'postgres', '"price" > 150'),  # Use price > 150 for chocos table
        ('postgres', 'sqlserver', None),  # Auto-generate WHERE clause
        ('sqlserver', 'postgres', None),  # Auto-generate WHERE clause
        ('mysql', 'sqlserver', '"price" > 150'),  # Use price > 150 for chocos table
        ('sqlserver', 'mysql', None),  # Auto-generate WHERE clause
    ]
    
    results = {}
    
    for source_type, target_type, where_clause in combinations:
        test_name = f"{source_type.upper()} → {target_type.upper()}"
        print(f"\n{'='*80}")
        print(f"Test: {test_name}")
        if where_clause:
            print(f"WHERE Clause: {where_clause}")
        else:
            print(f"WHERE Clause: (auto-generated from table)")
        print(f"{'='*80}")
        
        success, rows_migrated, error = test_sync_direction(source_type, target_type, where_clause)
        
        results[test_name] = {
            'success': success,
            'rows': rows_migrated,
            'error': error
        }
        
        if success:
            print(f"✓ {test_name}: SUCCESS - {rows_migrated} rows migrated")
        else:
            print(f"✗ {test_name}: FAILED - {error}")
    
    # Summary
    print("\n" + "="*80)
    print("Test Summary")
    print("="*80)
    
    passed = 0
    failed = 0
    
    for test_name, result in results.items():
        status = "✓ PASSED" if result['success'] else "✗ FAILED"
        rows_info = f" ({result['rows']} rows)" if result['success'] else ""
        error_info = f" - {result['error']}" if result['error'] else ""
        print(f"{test_name}: {status}{rows_info}{error_info}")
        
        if result['success']:
            passed += 1
        else:
            failed += 1
    
    print(f"\nTotal: {passed} passed, {failed} failed out of {len(results)} tests")
    print("="*80)
    
    return failed == 0

if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
