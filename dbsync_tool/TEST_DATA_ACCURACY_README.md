# Data Accuracy Test Suite

This test suite verifies **100% data accuracy** for PostgreSQL ↔ MySQL migrations.

## Overview

The test suite includes:
1. **PostgreSQL → MySQL Test**: Verifies data accuracy when migrating from PostgreSQL to MySQL
2. **MySQL → PostgreSQL Test**: Verifies data accuracy when migrating from MySQL to PostgreSQL
3. **Large Dataset Test**: Tests with 1000 rows to ensure scalability

## What Gets Tested

### 1. Row Count Verification
- Verifies that the number of rows in source matches target exactly

### 2. Column Structure Verification
- Verifies that all columns exist in target
- Verifies no extra columns in target
- Verifies column names match exactly

### 3. Data Integrity Verification
- Compares **every single row** between source and target
- Compares **every single column value** for each row
- Handles data type conversions (Decimal → float, datetime comparisons)
- Verifies NULL values are preserved correctly
- Verifies special characters and Unicode are preserved

### 4. Edge Cases
- NULL value preservation
- Data type conversions
- Special characters and Unicode
- Large datasets (1000+ rows)

## Test Data

The test creates a comprehensive test table with:
- **100 rows** of test data (or 1000 for large dataset test)
- **10 columns** with various data types:
  - `id` (INTEGER, Primary Key)
  - `name` (VARCHAR(255))
  - `email` (VARCHAR(255))
  - `age` (INTEGER)
  - `salary` (DECIMAL(10,2))
  - `is_active` (BOOLEAN)
  - `created_at` (TIMESTAMP)
  - `birth_date` (DATE)
  - `description` (TEXT with special characters and Unicode)
  - `null_field` (VARCHAR(100), with NULL values)

## Running the Tests

### Option 1: Using Django Test Runner

```bash
cd dbsync_tool
python manage.py test sync_jobs.tests.test_data_accuracy_postgres_mysql
```

### Option 2: Using Standalone Script

```bash
cd dbsync_tool
python run_accuracy_tests.py
```

## Prerequisites

1. **Database Connections**: You must have PostgreSQL and MySQL connections configured in the Connections page
   - The test will automatically use your existing connections
   - If no connections exist, it will use environment variables or defaults

2. **Database Access**: The connections must have:
   - Read/write access to source database
   - Read/write access to target database
   - Permission to create tables and insert data

## Environment Variables (Optional)

If you want to override the database connections, set these environment variables:

```bash
# PostgreSQL
export TEST_POSTGRES_HOST=localhost
export TEST_POSTGRES_PORT=5432
export TEST_POSTGRES_USER=postgres
export TEST_POSTGRES_PASSWORD=postgres
export TEST_POSTGRES_DB=tauseef

# MySQL
export TEST_MYSQL_HOST=localhost
export TEST_MYSQL_PORT=3306
export TEST_MYSQL_USER=root
export TEST_MYSQL_PASSWORD=root
export TEST_MYSQL_DB=test_sync_source
```

## Test Output

The test will output:
- ✓ Row count matches
- ✓ Column structure matches
- ✓ All rows match exactly
- ✓ NULL values preserved
- ✅ PASSED: Test name

If any test fails, you'll see:
- ❌ FAILED: Test name
- Detailed error messages showing exactly what didn't match
- Row-by-row comparison results

## Understanding Test Results

### Success Criteria

A test **PASSES** only if:
1. ✅ Row count in source = Row count in target
2. ✅ All columns exist in both source and target
3. ✅ Every single row matches exactly
4. ✅ Every single column value matches exactly
5. ✅ NULL values are preserved correctly
6. ✅ Data types are converted correctly

### Failure Scenarios

The test will **FAIL** if:
- Row counts don't match
- Columns are missing or extra
- Any row has mismatched data
- Any column value doesn't match
- NULL values are not preserved
- Data type conversions are incorrect

## Example Output

```
================================================================================
Data Accuracy Test Suite - PostgreSQL ↔ MySQL
================================================================================

✓ Found PostgreSQL connection: My PostgreSQL (localhost:5432/tauseef)
✓ Found MySQL connection: My MySQL (localhost:3306/test_sync_target)

--------------------------------------------------------------------------------
Test 1: PostgreSQL → MySQL Data Accuracy
--------------------------------------------------------------------------------
✓ Row count matches: 100 rows
✓ Column structure matches: 10 columns
✓ Fetched 100 rows for comparison
✓ All 100 rows match exactly
✓ NULL values preserved: 10 NULL values
✅ PASSED: PostgreSQL → MySQL accuracy test

--------------------------------------------------------------------------------
Test 2: MySQL → PostgreSQL Data Accuracy
--------------------------------------------------------------------------------
✓ Row count matches: 100 rows
✓ Column structure matches: 10 columns
✓ Fetched 100 rows for comparison
✓ All 100 rows match exactly
✓ NULL values preserved: 10 NULL values
✅ PASSED: MySQL → PostgreSQL accuracy test

================================================================================
✅ ALL TESTS PASSED - 100% Data Accuracy Verified!
================================================================================
```

## Troubleshooting

### Test Fails with "Database not available"
- Check that your database connections are configured correctly
- Verify that the databases are running and accessible
- Check network connectivity

### Test Fails with "Row count mismatch"
- Check if the sync job completed successfully
- Verify that no data was lost during migration
- Check execution logs for errors

### Test Fails with "Column mismatch"
- Verify that all columns were created in the target
- Check if any columns were skipped during table creation
- Review table creation logs

### Test Fails with "Value mismatch"
- Check data type mappings
- Verify that special characters are handled correctly
- Check for encoding issues (UTF-8)
- Review NULL value handling

## Notes

- The test creates temporary test tables that are cleaned up after the test
- The test uses your existing database connections from the Connections page
- The test verifies **100% accuracy** - any mismatch will cause the test to fail
- The test compares **every single row and column** - not just a sample



