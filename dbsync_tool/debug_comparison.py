"""
Debug script to check what's actually being compared during post-migration verification
Run this after a failed sync to see what's mismatched
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
from sync_engine.query_result_verifier import QueryResultVerifier
from sync_engine.pre_migration_validator import PreMigrationValidator
import logging

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

def debug_last_failed_job():
    """Debug the last failed sync job"""
    print("\n" + "="*80)
    print("Debugging Last Failed Sync Job")
    print("="*80)
    
    # Get the last execution
    last_execution = SyncExecution.objects.order_by('-started_at').first()
    if not last_execution:
        print("   ✗ No executions found")
        return
    
    print(f"\nJob: {last_execution.job.name}")
    print(f"Execution ID: {last_execution.id}")
    print(f"Status: {last_execution.status}")
    print(f"Started: {last_execution.started_at}")
    
    # Get failed table logs
    from sync_jobs.models import SyncExecutionLog
    failed_logs = SyncExecutionLog.objects.filter(
        execution=last_execution,
        status='failed'
    )
    
    if not failed_logs.exists():
        print("\n   ✗ No failed table logs found")
        return
    
    for log in failed_logs:
        print(f"\n{'='*80}")
        print(f"Failed Table: {log.schema_name}.{log.table_name}")
        print(f"{'='*80}")
        print(f"Error: {log.error_message[:500]}")
        
        # Get the job table
        try:
            job_table = SyncJobTable.objects.get(
                job=last_execution.job,
                schema_name=log.schema_name,
                table_name=log.table_name
            )
            
            print(f"\nTransformation Query: {job_table.transformation_query}")
            print(f"Column Transformations: {job_table.column_transformations}")
            
            # Get connections
            source_conn = last_execution.job.source_connection
            target_conn = last_execution.job.target_connection
            
            source_connector = get_connector(source_conn)
            target_connector = get_connector(target_conn)
            
            source_connector.connect()
            target_connector.connect()
            
            # Get column names
            columns = source_connector.get_columns(log.schema_name, log.table_name)
            column_names = [col.name for col in columns]
            print(f"\nColumn Names: {column_names}")
            
            # Execute the transformation query on source
            from sync_engine.query_builder import QueryBuilder
            query_builder = QueryBuilder()
            
            where_clause = job_table.transformation_query
            column_transformations = job_table.column_transformations or {}
            
            # Get primary key for ordering
            try:
                pk_columns = source_connector.get_primary_key(log.schema_name, log.table_name)
                order_by = ', '.join(pk_columns) if pk_columns else column_names[0]
            except:
                order_by = column_names[0]
            
            source_query = query_builder.build_select_query(
                connector=source_connector,
                schema=log.schema_name,
                table=log.table_name,
                columns=column_names,
                order_by=order_by,
                where_clause=where_clause,
                column_transformations=column_transformations
            )
            
            print(f"\nSource Query: {source_query}")
            source_rows = source_connector.fetch_batch(source_query, batch_size=100, offset=0)
            print(f"\nSource Rows ({len(source_rows)}):")
            if source_rows:
                print(f"  First row: {source_rows[0]}")
                print(f"  Types: {[type(v).__name__ for v in source_rows[0]]}")
                if len(source_rows) > 1:
                    print(f"  Second row: {source_rows[1]}")
            
            # Get target rows
            target_query = query_builder.build_select_query(
                connector=target_connector,
                schema=target_conn.target_schema or target_conn.database,
                table=log.table_name,
                columns=column_names,
                order_by=order_by
            )
            
            print(f"\nTarget Query: {target_query}")
            target_rows = target_connector.fetch_batch(target_query, batch_size=100, offset=0)
            print(f"\nTarget Rows ({len(target_rows)}):")
            if target_rows:
                print(f"  First row: {target_rows[0]}")
                print(f"  Types: {[type(v).__name__ for v in target_rows[0]]}")
                if len(target_rows) > 1:
                    print(f"  Second row: {target_rows[1]}")
            
            # Compare
            print(f"\n{'='*80}")
            print("Comparing Rows...")
            print(f"{'='*80}")
            
            verifier = QueryResultVerifier(source_connector)
            result = verifier.compare_query_results_with_target(
                source_query_result=source_rows[:4],  # Limit to 4 rows
                target_rows=target_rows[:4],
                column_names=column_names,
                column_transformations=column_transformations
            )
            
            print(f"\nComparison Result: {result[0]}")
            if not result[0]:
                print(f"Error: {result[1]}")
                if result[2].get('mismatched_rows'):
                    print(f"\nMismatched Rows ({len(result[2]['mismatched_rows'])}):")
                    for i, mismatch in enumerate(result[2]['mismatched_rows'][:5], 1):
                        print(f"\n  Mismatch {i}:")
                        print(f"    Row Index: {mismatch.get('row_index')}")
                        print(f"    Error: {mismatch.get('error')}")
                        print(f"    Source Row: {mismatch.get('source_row')}")
                        print(f"    Target Row: {mismatch.get('target_row')}")
            
            source_connector.close()
            target_connector.close()
            
        except Exception as e:
            print(f"\n   ✗ Error debugging: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    debug_last_failed_job()
    print("\n" + "="*80 + "\n")
