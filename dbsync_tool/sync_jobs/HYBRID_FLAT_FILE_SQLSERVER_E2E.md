# Flat-File Hybrid Incremental E2E (UI + SQL Server)

This runbook validates flat-file incremental growth in SQL Server using the UI flow.

## Preconditions

- Target DB connection exists and is tested:
  - Name: `server2`
  - DB type: `sqlserver`
  - Host: `localhost`
  - Port: `1433`
  - Database: `SmartphoneDB`
  - Username: `sa`
- App is running: `python manage.py runserver 8004`
- Fixture files exist:
  - `dbsync_tool/file_sources/imports/hybrid_devices_v1.csv`
  - `dbsync_tool/file_sources/imports/hybrid_devices_v2.csv`

## UI Steps

1. Create or edit file source connection to point to:
   - `file_sources/imports/hybrid_devices_v1.csv`
2. Create new sync job:
   - Source type: `Flat File`
   - Source file connection: created above
   - Target connection: `server2`
3. Step 2 preview:
   - Target table name: `hybrid_devices`
4. Step 3 mapping:
   - Mark `device_id` as `Protected`.
5. Step 5 configure:
   - `Sync Type`: `Incremental`
   - Flat-file mode: `Hybrid hash + control table`
   - Hash algorithm: `sha256`
   - Hash columns: `device_id,brand,model,price`
   - Leave hash-only unchecked (requires stable key).
   - Schedule: `Run Once`.
6. Submit job and wait for first execution to complete.

## Switch Source to v2

1. Update the file source path to:
   - `file_sources/imports/hybrid_devices_v2.csv`
2. Run job again (`Run now`).

## SQL Verification (SQL Server)

Use any SQL client connected to `SmartphoneDB`:

```sql
-- Row count after first run should be 5
SELECT COUNT(*) AS row_count_run1 FROM [dbo].[hybrid_devices];

-- Row count after second run should be 8
SELECT COUNT(*) AS row_count_run2 FROM [dbo].[hybrid_devices];

-- No duplicate keys
SELECT device_id, COUNT(*) AS c
FROM [dbo].[hybrid_devices]
GROUP BY device_id
HAVING COUNT(*) > 1;

-- Appended rows should exist
SELECT *
FROM [dbo].[hybrid_devices]
WHERE device_id IN ('1006', '1007', '1008');
```

## Expected Outcome

- First run inserts 5 rows.
- Second incremental run inserts only 3 new rows.
- Final row count is 8.
- Duplicate-key check returns 0 rows.
- Execution log indicates hybrid incremental behavior and checkpoint/control decisions.
