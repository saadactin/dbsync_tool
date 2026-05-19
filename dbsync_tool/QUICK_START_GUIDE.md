# 🚀 Quick Start Guide - Database Migrations

## Prerequisites

### Database Connections
1. **SQL Server** → PostgreSQL:
   - Source: SQL Server with tables to migrate
   - Target: PostgreSQL database

2. **PostgreSQL** → ClickHouse:
   - Source: PostgreSQL with tables to migrate
   - Target: ClickHouse database

---

## 🎯 Full Sync (Initial Migration)

### SQL Server → PostgreSQL

```python
from sync_jobs.models import SyncJob, SyncJobTable, DatabaseConnection
from django.contrib.auth.models import User

# Get or create connections
sqlserver_conn = DatabaseConnection.objects.get(name='Your SQL Server')
postgres_conn = DatabaseConnection.objects.get(name='Your PostgreSQL')
user = User.objects.first()

# Create full sync job
job = SyncJob.objects.create(
    name='SQLServer_to_Postgres_Full',
    source_connection=sqlserver_conn,
    target_connection=postgres_conn,
    sync_type='full',
    verification_mode='hash',
    no_delete_propagation=True,
    created_by=user,
    tenant=user
)

# Configure table to sync
job_table = SyncJobTable.objects.create(
    job=job,
    schema_name='dbo',  # Source schema
    table_name='your_table_name',
    is_enabled=True
)

# Execute sync
from sync_engine.executor import SyncExecutor
executor = SyncExecutor(job)
executor.execute()
```

### PostgreSQL → ClickHouse

```python
from sync_jobs.models import SyncJob, SyncJobTable, DatabaseConnection
from django.contrib.auth.models import User

# Get or create connections
postgres_conn = DatabaseConnection.objects.get(name='Your PostgreSQL')
clickhouse_conn = DatabaseConnection.objects.get(name='Your ClickHouse')
user = User.objects.first()

# Create full sync job
job = SyncJob.objects.create(
    name='Postgres_to_ClickHouse_Full',
    source_connection=postgres_conn,
    target_connection=clickhouse_conn,
    sync_type='full',
    verification_mode='hash',
    no_delete_propagation=True,
    created_by=user,
    tenant=user
)

# Configure table to sync
job_table = SyncJobTable.objects.create(
    job=job,
    schema_name='public',  # Source schema
    table_name='your_table_name',
    incremental_column='updated_at',  # Optional: for future incremental sync
    incremental_key_columns=['id'],   # Primary key for upsert
    is_enabled=True
)

# Execute sync
from sync_engine.executor import SyncExecutor
executor = SyncExecutor(job)
executor.execute()
```

---

## 🔄 Incremental Sync (Ongoing Updates)

### SQL Server → PostgreSQL

```python
# Get existing job
job = SyncJob.objects.get(name='SQLServer_to_Postgres_Full')

# Update to incremental
job.sync_type = 'incremental'
job.save()

# Ensure job table has incremental configuration
job_table = SyncJobTable.objects.get(job=job, table_name='your_table_name')
job_table.incremental_column = 'updated_at'  # Column that tracks changes
job_table.incremental_key_columns = ['id']    # Primary key for upsert
job_table.save()

# Execute incremental sync
executor = SyncExecutor(job)
executor.execute()
```

### PostgreSQL → ClickHouse

```python
# Get existing job
job = SyncJob.objects.get(name='Postgres_to_ClickHouse_Full')

# Update to incremental
job.sync_type = 'incremental'
job.save()

# Ensure job table has incremental configuration
job_table = SyncJobTable.objects.get(job=job, table_name='your_table_name')
job_table.incremental_column = 'updated_at'  # Column that tracks changes
job_table.incremental_key_columns = ['id']    # Primary key for upsert
job_table.save()

# Execute incremental sync
executor = SyncExecutor(job)
executor.execute()
```

---

## 🎛️ Configuration Options

### SyncJob Fields

| Field | Description | Values |
|-------|-------------|--------|
| `sync_type` | Type of sync | `'full'` or `'incremental'` |
| `verification_mode` | How to verify data | `'hash'`, `'row_count'`, or `None` |
| `no_delete_propagation` | Skip deletes | `True` or `False` |

### SyncJobTable Fields

| Field | Description | Required For |
|-------|-------------|--------------|
| `schema_name` | Source schema | All syncs |
| `table_name` | Source table | All syncs |
| `incremental_column` | Column for checkpoint | Incremental sync |
| `incremental_key_columns` | Primary key(s) | Incremental sync (upsert) |
| `is_enabled` | Enable this table | All syncs |

---

## 📊 Monitoring

### Check Sync Status

```python
from sync_jobs.models import SyncExecution

# Get latest execution
execution = SyncExecution.objects.filter(job=job).order_by('-created_at').first()

print(f"Status: {execution.status}")
print(f"Rows synced: {execution.total_rows_synced}")
print(f"Duration: {execution.duration_seconds}s")
print(f"Errors: {execution.error_count}")
```

### Check Logs

```python
from sync_jobs.models import SyncExecutionLog

# Get logs for execution
logs = SyncExecutionLog.objects.filter(execution=execution).order_by('created_at')

for log in logs:
    print(f"[{log.log_level}] {log.table_name}: {log.message}")
```

### Check Checkpoint

```python
from sync_engine.checkpoint_manager import CheckpointManager

checkpoint_manager = CheckpointManager(job)
checkpoint = checkpoint_manager.get_checkpoint_value('public', 'your_table_name')
print(f"Last checkpoint: {checkpoint}")
```

---

## ⚠️ Important Notes

### For SQL Server → PostgreSQL

1. **Primary Keys**: 
   - If source has primary key, it will be auto-detected
   - Otherwise, set `incremental_key_columns` manually

2. **Schema Mapping**: 
   - SQL Server schemas (e.g., `dbo`) map to PostgreSQL `public` schema

3. **Type Mapping**: 
   - IDENTITY → SERIAL
   - NVARCHAR → VARCHAR
   - DATETIME2 → TIMESTAMP
   - BIT → BOOLEAN

### For PostgreSQL → ClickHouse

1. **ReplacingMergeTree**:
   - Version column (`incremental_column`) must NOT be NULL
   - Used for deduplication in ClickHouse

2. **Target Database**:
   - Always uses target connection's `database_name`
   - NOT the source schema name

3. **Metadata Columns**:
   - `is_deleted`: Soft delete flag (0=active, 1=deleted)
   - `__sync_version`: Monotonic timestamp
   - `__sync_timestamp`: Sync timestamp

4. **Querying**:
   - Always use `FINAL` to get deduplicated results
   - Example: `SELECT * FROM test_sql.table FINAL WHERE is_deleted = 0`

5. **Checkpoint Table**:
   - Created automatically: `{database}._sync_checkpoints`
   - Stores last synced value per table

---

## 🧪 Testing

### Run Tests

```bash
cd dbsync_tool
python test_migrations.py
```

### Expected Output

```
SQL Server → PostgreSQL:
  Full Sync:        ✅ PASSED
  Incremental Sync: ✅ PASSED

PostgreSQL → ClickHouse:
  Full Sync:        ✅ PASSED
  Incremental Sync: ✅ PASSED

✅ ALL TESTS PASSED - 100% ACCURACY ACHIEVED
```

---

## 🐛 Troubleshooting

### Issue: "No stable upsert key available"

**Solution**: Set `incremental_key_columns` on the SyncJobTable:
```python
job_table.incremental_key_columns = ['id']
job_table.save()
```

### Issue: "No checkpoint found"

**Solution**: Run full sync first to create initial checkpoint:
```python
job.sync_type = 'full'
job.save()
executor.execute()
```

### Issue: ClickHouse "Table does not exist"

**Solution**: Ensure target database exists and is specified correctly:
```python
clickhouse_conn.database_name = 'your_database'
clickhouse_conn.save()
```

### Issue: ReplacingMergeTree version column error

**Solution**: Ensure incremental column is NOT NULL in source table:
```sql
ALTER TABLE your_table ALTER COLUMN updated_at SET NOT NULL;
```

---

## 📞 Support

- **Documentation**: See `FINAL_TEST_RESULTS_100_PERCENT.md` for detailed results
- **Test Script**: `test_migrations.py` for reference implementation
- **Logs**: Check Django admin → Sync Executions → Logs

---

## ✅ Checklist

### Before First Sync
- [ ] Database connections configured
- [ ] Source table exists with data
- [ ] Target database exists (ClickHouse)
- [ ] User has necessary permissions
- [ ] Incremental column has index (for performance)

### Before Incremental Sync
- [ ] Full sync completed successfully
- [ ] Checkpoint exists
- [ ] `incremental_column` set
- [ ] `incremental_key_columns` set
- [ ] Source table has updates since last sync

### After Sync
- [ ] Row counts match
- [ ] No duplicates
- [ ] Data integrity verified
- [ ] Email notification received
- [ ] No errors in logs

---

**Last Updated**: May 8, 2026  
**Version**: 1.0  
**Status**: ✅ Production Ready
