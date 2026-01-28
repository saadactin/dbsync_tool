# Data Transformation Queries Feature - Complete User Guide

## Overview

The Data Transformation Queries feature allows you to apply SQL transformations during database migration. You can:
- Filter data with WHERE clauses (e.g., `age >= 30`)
- Transform columns (TRIM, UPPER, LOWER)
- Configure transformations per table on Step 2

---

## Step-by-Step Process

### **STEP 1: Job Name & Connections Selection**

**URL**: `/sync-jobs/create/step1/`

**What You'll See:**
- Form with three fields:
  1. **Job Name** - Text input field
  2. **Source Connection** - Dropdown of your database connections
  3. **Target Connection** - Dropdown of your database connections

**What to Input:**
1. **Job Name**: Enter a descriptive name (e.g., "Users Migration with Filters")
2. **Source Connection**: Select the source database from the dropdown
3. **Target Connection**: Select the target database from the dropdown

**Important Rules:**
- Source and Target connections must be different
- Both connections must be active
- You must have access to both connections

**After Submission:**
- Click **"Next"** button
- System validates your inputs
- Redirects to **Step 2** if valid

---

### **STEP 2: Select Tables & Configure Transformations** ⭐ NEW FEATURE

**URL**: `/sync-jobs/create/step2/`

**What You'll See:**
- **Progress Bar**: Shows "Step 2 of 3"
- **Source Connection Info Card**: Displays connection name, type, and database
- **Table Selection Area** with:
  - Search box to filter tables
  - "Select All" / "Deselect All" buttons
  - Refresh button (🔄)
  - Expandable schema tree (click schema name to see tables)
  - Checkboxes next to each table name
  - **⚙️ Transform button** next to each table (NEW!)

**What to Do:**

#### A. Select Tables to Sync
1. **Expand Schemas**: Click on schema names to see tables
2. **Select Tables**: Check the boxes next to tables you want to sync
3. **Search**: Use the search box to quickly find specific tables
4. **Bulk Selection**: Use "Select All" or "Deselect All" for convenience

#### B. Configure Transformations (NEW!)

For each table you want to transform, follow these steps:

1. **Click the "⚙️ Transform" button** next to the table name
   - A transformation panel will appear below the table

2. **Configure WHERE Clause (Optional)**
   - In the "WHERE Clause" textarea, enter your SQL WHERE condition
   - **IMPORTANT**: Don't include the word "WHERE" - just the condition
   - **Examples**:
     ```
     age >= 30
     status = 'active' AND created_at >= '2024-01-01'
     department_id IN (1, 2, 3)
     email IS NOT NULL
     ```

3. **Configure Column Transformations (Optional)**
   - Click **"+ Add Column Transformation"** button
   - A new row appears with two dropdowns:
     - **Column Dropdown**: Select the column to transform
     - **Transformation Dropdown**: Choose from:
       - `None` - No transformation
       - `TRIM` - Removes leading/trailing spaces
       - `UPPER` - Converts to uppercase
       - `LOWER` - Converts to lowercase
   - **Add Multiple**: You can add multiple column transformations
   - **Remove**: Click "Remove" button to delete a transformation

4. **Validate Transformation**
   - Click **"Validate"** button
   - System checks:
     - WHERE clause syntax is correct
     - Columns exist in the table
     - No SQL injection attempts
   - **Success**: Green message "✓ Transformation is valid"
   - **Error**: Red message with error details

5. **Clear Transformation (Optional)**
   - Click **"Clear"** button to reset all transformations for that table
   - You can reconfigure from scratch

6. **Hide/Show Panel**
   - Click "⚙️ Transform" button again to hide the panel
   - Your configurations are saved while the panel is hidden

**Example Transformation Configuration:**

**Table**: `public.users`

**WHERE Clause**:
```
age >= 25 AND status = 'active'
```

**Column Transformations**:
- `name` → `TRIM` (removes spaces)
- `email` → `LOWER` (converts to lowercase)
- `department` → `UPPER` (converts to uppercase)

**Result**: Only users aged 25+ with active status will be migrated, and their names will be trimmed, emails lowercased, and departments uppercased.

#### C. Continue to Step 3
- Click **"Next"** button (bottom of page)
- System saves your table selections and transformation configurations
- Redirects to **Step 3**

**Note**: 
- You can configure transformations for some tables and leave others without transformations
- Transformations are optional - you can skip them entirely
- If you don't click "Transform" button, the table will sync without transformations

---

### **STEP 3: Sync Type & Schedule Configuration**

**URL**: `/sync-jobs/create/step3/`

**What You'll See:**
- **Progress Bar**: Shows "Step 3 of 3"
- **Job Name Display**: Shows your job name
- **Source Connection Info**: Connection details
- **Selected Tables List**: Shows all tables you selected in Step 2
- **Sync Type Selection**: Radio buttons
  - `Full Sync` - Complete table sync
  - `Incremental Sync` - Only sync new/changed rows
- **Schedule Type Selection**: Radio buttons with options:
  - `Once` - Run immediately, one time
  - `Hourly` - Run every hour
  - `Daily` - Run daily at midnight
  - `Weekly` - Run every Monday
  - `Custom` - Use cron expression
- **Incremental Column Selection** (if Incremental Sync selected):
  - For each table, dropdown to select the incremental column
- **Start Date/Time** (if scheduled):
  - Date-time picker for scheduled runs

**What to Input:**

1. **Sync Type**:
   - Choose **Full Sync** or **Incremental Sync**
   - Full Sync: Syncs entire table every time
   - Incremental Sync: Only syncs rows where incremental column value > last checkpoint

2. **Incremental Column** (if Incremental Sync):
   - For each table, select the column to use for incremental sync
   - Common choices: `id`, `created_at`, `updated_at`
   - Only timestamp/date and integer columns are shown

3. **Schedule Type**:
   - **Once**: Immediate one-time execution
   - **Hourly/Daily/Weekly**: Recurring schedule
   - **Custom**: Enter cron expression (advanced)

4. **Start Date/Time** (if not "Once"):
   - Select when to start the scheduled sync
   - Format: Date and time picker

**After Submission:**
- Click **"Create Job"** button
- System:
  1. Creates the sync job
  2. Saves all table configurations
  3. **Saves all transformation configurations**
  4. Creates the schedule (if applicable)
  5. Redirects to job detail page

---

## Complete Example Walkthrough

### Scenario: Migrate Active Users with Transformations

**Step 1:**
- Job Name: `Active Users Migration`
- Source: `Production PostgreSQL`
- Target: `Analytics PostgreSQL`

**Step 2:**
- Select Table: `public.users`
- Click **"⚙️ Transform"**
- WHERE Clause: `status = 'active' AND created_at >= '2024-01-01'`
- Column Transformations:
  - `email` → `LOWER`
  - `first_name` → `TRIM`
  - `last_name` → `TRIM`
- Click **"Validate"** → ✓ Success
- Click **"Next"**

**Step 3:**
- Sync Type: `Full Sync`
- Schedule: `Daily`
- Start Date/Time: `Tomorrow 2:00 AM`
- Click **"Create Job"**

**Result:**
- Job created successfully
- Will sync daily at 2 AM
- Only active users created after Jan 1, 2024
- Emails converted to lowercase
- First and last names trimmed

---

## Transformation Features Explained

### WHERE Clause Filtering

**Purpose**: Filter rows before migration

**Examples**:
```
age >= 30
status = 'active' AND is_verified = true
created_at >= '2024-01-01' AND created_at < '2025-01-01'
department_id IN (1, 2, 3, 4, 5)
email IS NOT NULL AND email != ''
```

**What Happens**:
- Only rows matching the WHERE clause are migrated
- System executes query on source first to validate
- Row count is verified before migration starts

### Column Transformations

**TRIM**:
- Removes leading and trailing spaces
- Example: `"  John Doe  "` → `"John Doe"`

**UPPER**:
- Converts to uppercase
- Example: `"john@example.com"` → `"JOHN@EXAMPLE.COM"`

**LOWER**:
- Converts to lowercase
- Example: `"John@Example.COM"` → `"john@example.com"`

**What Happens**:
- Transformations applied in SQL during data fetch
- Applied before data is inserted into target
- NULL values are preserved (not transformed)

---

## Validation & Safety Features

### Pre-Migration Validation

When you click **"Validate"**:
1. ✅ WHERE clause syntax checked
2. ✅ Column existence verified
3. ✅ SQL injection attempts blocked
4. ✅ Query executed on source database
5. ✅ Row count preview shown

### During Migration

1. **Query Execution Before Migration**:
   - Full query executed on source first
   - Results verified
   - Migration only proceeds if validation passes

2. **Data Accuracy Verification**:
   - Row count compared (source vs target)
   - Sample rows compared
   - Transformations verified
   - Rollback if verification fails

3. **Zero Data Loss**:
   - All rows matching WHERE clause are migrated
   - System verifies 100% accuracy
   - Migration fails if data loss detected

---

## Tips & Best Practices

### WHERE Clause Tips
- ✅ Use proper SQL syntax
- ✅ Test your WHERE clause manually first
- ✅ Use quotes for string values: `'active'`
- ✅ Use date format: `'2024-01-01'`
- ❌ Don't include the word "WHERE"
- ❌ Don't use DROP, DELETE, INSERT, UPDATE statements

### Column Transformation Tips
- ✅ TRIM is useful for cleaning whitespace
- ✅ UPPER/LOWER for standardizing text
- ✅ Apply transformations consistently across columns
- ✅ Test with sample data first

### Performance Tips
- ⚡ WHERE clauses improve performance (less data to migrate)
- ⚡ Use indexed columns in WHERE clauses when possible
- ⚡ Column transformations add minimal overhead
- ⚡ Large datasets may take time to validate

---

## Troubleshooting

### Validation Errors

**"Column does not exist"**:
- Check column name spelling
- Verify column exists in source table
- Column names are case-sensitive for some databases

**"WHERE clause syntax error"**:
- Check SQL syntax
- Verify table and column names
- Use proper quotes for string values
- Don't include "WHERE" keyword

**"SQL injection attempt blocked"**:
- Remove any semicolons (;)
- Remove SQL comments (--, /* */)
- Remove dangerous keywords (DROP, DELETE, etc.)

### Transformation Not Applied

- Ensure you clicked "Validate" successfully
- Check that transformation was saved before clicking "Next"
- Verify transformations in job detail page after creation

---

## Accessing Your Created Job

After creating the job:
1. You'll be redirected to the **Job Detail Page**
2. See job status, configuration, and execution history
3. Transformations are displayed in the table configuration section
4. You can run the job immediately or wait for schedule
5. View execution logs to see transformation results

---

## Need Help?

- Check job execution logs for detailed error messages
- Review transformation configuration in job detail page
- Validate transformations before migration to catch errors early
- Use "Preview" feature (coming soon) to see transformation results before migration

---

## Summary

**The Complete Flow:**

1. **Step 1**: Name job, select source & target connections
2. **Step 2**: Select tables, click "⚙️ Transform" to configure:
   - WHERE clause filtering (optional)
   - Column transformations (optional)
   - Validate your configuration
3. **Step 3**: Choose sync type, schedule, and create job

**Transformations are applied:**
- ✅ Before migration (query executed and validated)
- ✅ During migration (data transformed before insertion)
- ✅ After migration (accuracy verified)

**Result**: Perfect migration with zero data loss and 100% accuracy! 🎉
