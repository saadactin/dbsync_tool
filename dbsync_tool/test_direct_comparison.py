"""
Direct comparison test - query both databases and compare
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from connections.connectors.factory import get_connector
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable

# Get the job
job = SyncJob.objects.filter(name='saad1').first()
if not job:
    print("Job not found")
    sys.exit(1)

# Get the job table
job_table = job.tables.first()
if not job_table:
    print("No tables in job")
    sys.exit(1)

print(f"Job: {job.name}")
print(f"Table: {job_table.schema_name}.{job_table.table_name}")
print(f"WHERE: {job_table.transformation_query}")
print()

# Get connectors
source_conn = job.source_connection
target_conn = job.target_connection

source_connector = get_connector(source_conn)
target_connector = get_connector(target_conn)

source_connector.connect()
target_connector.connect()

# Get columns
schema = job_table.schema_name
table = job_table.table_name
columns = source_connector.get_columns(schema, table)
column_names = [col.name for col in columns]

print(f"Columns: {column_names}")
print()

# Build source query with WHERE clause
where_clause = job_table.transformation_query
col_list = ', '.join(f'"{col}"' for col in column_names)
source_query = f'SELECT {col_list} FROM "{schema}"."{table}"'
if where_clause:
    source_query += f' WHERE {where_clause}'
source_query += f' ORDER BY "{column_names[0]}"'  # Order by first column (CakeID)

print(f"Source Query: {source_query}")

# Execute source query - use fetch_batch to get rows
source_rows = []
offset = 0
while True:
    batch = source_connector.fetch_batch(source_query, 1000, offset)
    if not batch:
        break
    source_rows.extend(batch)
    offset += len(batch)
    if len(batch) < 1000:
        break

print(f"\nSource Rows ({len(source_rows)}):")
for i, row in enumerate(source_rows[:5], 1):
    print(f"  Row {i}: {row}")
    print(f"    Types: {[type(v).__name__ for v in row]}")

# Get target schema - MySQL uses database name as schema
# For MySQL targets, use database_name
target_schema = target_conn.database_name
print(f"\nTarget Schema: {target_schema}")

# Build target query
target_col_list = ', '.join(f'`{col}`' for col in column_names)
target_query = f'SELECT {target_col_list} FROM `{target_schema}`.`{table}`'
target_query += f' ORDER BY `{column_names[0]}`'  # Order by first column

print(f"\nTarget Query: {target_query}")

# Execute target query - use fetch_batch to get rows
target_rows = []
offset = 0
while True:
    batch = target_connector.fetch_batch(target_query, 1000, offset)
    if not batch:
        break
    target_rows.extend(batch)
    offset += len(batch)
    if len(batch) < 1000:
        break

print(f"\nTarget Rows ({len(target_rows)}):")
for i, row in enumerate(target_rows[:5], 1):
    print(f"  Row {i}: {row}")
    print(f"    Types: {[type(v).__name__ for v in row]}")

# Compare row by row
print(f"\n{'='*80}")
print("Row-by-Row Comparison:")
print(f"{'='*80}")

if len(source_rows) != len(target_rows):
    print(f"MISMATCH: Row count - Source: {len(source_rows)}, Target: {len(target_rows)}")
else:
    print(f"Row count matches: {len(source_rows)} rows")
    
    for i, (source_row, target_row) in enumerate(zip(source_rows, target_rows), 1):
        print(f"\nRow {i}:")
        matches = True
        for col_idx, col_name in enumerate(column_names):
            source_val = source_row[col_idx]
            target_val = target_row[col_idx]
            
            # Compare values
            if source_val != target_val:
                # Try type conversion
                if isinstance(source_val, bool) and isinstance(target_val, (int, bool)):
                    # PostgreSQL returns True/False, MySQL might return 1/0
                    source_bool = bool(source_val)
                    target_bool = bool(target_val)
                    if source_bool == target_bool:
                        print(f"  {col_name}: ✓ (bool conversion: {source_val} == {target_val})")
                        continue
                
                if isinstance(source_val, (int, float)) and isinstance(target_val, (int, float)):
                    if abs(float(source_val) - float(target_val)) < 0.0001:
                        print(f"  {col_name}: ✓ (numeric: {source_val} ≈ {target_val})")
                        continue
                
                print(f"  {col_name}: ✗ MISMATCH!")
                print(f"    Source: {source_val!r} (type: {type(source_val).__name__})")
                print(f"    Target: {target_val!r} (type: {type(target_val).__name__})")
                matches = False
            else:
                print(f"  {col_name}: ✓ ({source_val!r})")
        
        if not matches:
            print(f"\n  ✗ Row {i} does not match!")
        else:
            print(f"\n  ✓ Row {i} matches!")

source_connector.close()
target_connector.close()
