# Complete End-to-End Flow Testing Guide

## ✅ Fixed Issues
1. **JavaScript Loading**: Added multiple fallback mechanisms to ensure `loadSchemas()` is called
2. **Error Handling**: Improved error messages and recovery
3. **Timeout Handling**: Added 60-second timeout to prevent infinite hanging
4. **Element References**: Fixed potential null reference issues

## 🧪 Test Complete Flow

### Step 1: Verify Connections Work

**PostgreSQL Connection:**
- Host: localhost
- Port: 5432
- Database: Tor2 (or test99)
- Username: migration_user
- Password: StrongPassword123

**MySQL Connection:**
- Host: localhost
- Port: 3306
- Database: classicmodels (or any database)
- Username: root
- Password: root

### Step 2: Create Sync Job Flow

#### Test 1: PostgreSQL → MySQL (Full Sync)
1. **Step 1**: 
   - Job Name: "Test PG to MySQL Full"
   - Source: PostgreSQL connection
   - Target: MySQL connection
   - Click Next

2. **Step 2** (NOW FIXED):
   - Page should load schemas automatically
   - If stuck, check browser console (F12)
   - Select at least one table
   - Optionally configure transformations:
     - Click "⚙️ Transform" button
     - Add WHERE clause (e.g., `id > 100`)
     - Add column transformations
     - Click "Validate"
   - Click Next

3. **Step 3**:
   - Sync Type: Full Sync
   - Schedule: Once
   - Click "Create Job"

4. **Execute**:
   - Go to job detail page
   - Click "Run Now"
   - Monitor execution
   - Verify data in target database

#### Test 2: MySQL → PostgreSQL (Full Sync)
1. **Step 1**: 
   - Job Name: "Test MySQL to PG Full"
   - Source: MySQL connection
   - Target: PostgreSQL connection
   - Click Next

2. **Step 2**: Same as above

3. **Step 3**: Same as above

4. **Execute**: Same as above

#### Test 3: PostgreSQL → MySQL (Incremental Sync)
1. **Step 1**: 
   - Job Name: "Test PG to MySQL Incremental"
   - Source: PostgreSQL connection
   - Target: MySQL connection
   - Click Next

2. **Step 2**: 
   - Select tables
   - Click Next

3. **Step 3**: 
   - Sync Type: **Incremental Sync**
   - For each table, select incremental column (e.g., `id` or `created_at`)
   - Schedule: Daily
   - Click "Create Job"

4. **Execute**:
   - Run job
   - Verify only new/changed rows are synced
   - Run again - should sync incrementally

#### Test 4: MySQL → PostgreSQL (Incremental Sync)
Same as Test 3 but reversed.

#### Test 5: With Transformations
1. **Step 1**: Create job normally

2. **Step 2**: 
   - Select a table
   - Click "⚙️ Transform"
   - WHERE clause: `status = 'active'`
   - Column transformations:
     - `email` → LOWER
     - `name` → TRIM
   - Click "Validate"
   - Click Next

3. **Step 3**: Create job

4. **Execute**:
   - Verify only active records synced
   - Verify email is lowercase
   - Verify names are trimmed

## 🔍 Debugging Step 2 Loading Issue

### If Page Still Stuck on "Loading tables...":

1. **Open Browser Console** (F12 → Console tab)
   - Look for messages starting with "Step 2:" or "MetadataLoader:"
   - Check for any red error messages

2. **Check Network Tab** (F12 → Network tab)
   - Filter: XHR
   - Look for request to `/metadata/api/[connection-id]/schemas/`
   - Check status code (200 = success, 500 = error)
   - Check response time

3. **Hard Refresh**:
   - Press `Ctrl + Shift + R` (Windows) or `Cmd + Shift + R` (Mac)
   - Or clear browser cache

4. **Check Django Logs**:
   - Look at terminal where `manage.py runserver` is running
   - Check for any errors

## ✅ What Was Fixed

1. **Multiple Load Triggers**: 
   - Immediate call if DOM ready
   - setTimeout backup (100ms)
   - Window load event fallback (200ms)

2. **Better Error Handling**:
   - Clear error messages
   - Retry button
   - Links to fix connection

3. **Timeout Protection**:
   - 60-second timeout to prevent infinite hanging
   - Clear error if timeout occurs

4. **Element Reference Safety**:
   - Get fresh element references
   - Check for null before using

## 📊 Expected Console Output (When Working)

```
Step 2: Initializing...
Step 2: SOURCE_CONNECTION_ID = [uuid]
Step 2: connectionId = [uuid]
[OK] Connection ID found: [uuid]
Step 2: Setting up schema load...
Step 2: DOM ready, calling loadSchemas immediately...
Step 2: loadSchemas() called, useCache= true
Step 2: All elements found, starting load...
MetadataLoader: Loading schemas from URL: /metadata/api/[uuid]/schemas/?use_cache=true
MetadataLoader: Sending fetch request...
MetadataLoader: Fetch completed in 180ms, status: 200
MetadataLoader: Response data received: {success: true, data: [...]}
MetadataLoader: Successfully loaded 1 schemas
Step 2: Schemas loaded successfully in 200ms: 1 schemas
Step 2: Displaying schemas...
Step 2: Schemas displayed successfully
```

## 🚀 Next Steps

1. **Refresh the page** (Ctrl+Shift+R)
2. **Open browser console** (F12)
3. **Check the console output** - you should see the messages above
4. **If errors**, share the console output

The page should now work! All fixes have been applied and static files collected.
