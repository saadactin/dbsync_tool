# Quick Start Guide - Superset Analytics

## 1-Minute Setup

```bash
# Navigate to superset_analytics folder
cd superset_analytics

# Run setup script (first time only)
./init_superset.sh

# Wait ~5 minutes for containers to start and initialize

# Open browser
# http://localhost:8088
# Login: admin / admin
```

## Configure Database (One-Time)

After logging in to Superset:

1. Click **Settings** (top right) → **Database Connections**
2. Click **+ Database** button
3. Select **PostgreSQL**
4. Fill in:
   - **Display Name:** `DB Sync Analytics`
   - **SQLAlchemy URI:** 
     ```
     postgresql://superset:superset@superset_db:5432/superset?options=-c%20search_path=analytics
     ```
5. Click **Test Connection** → Should succeed
6. Click **Connect**

## Create Your First Chart

1. Go to **Data** → **Datasets** → **+ Dataset**
2. Select:
   - **Database:** `DB Sync Analytics`
   - **Schema:** `analytics`
   - **Table:** `sync_executions`
3. Click **Create Dataset and Create Chart**
4. Choose chart type (e.g., "Line Chart")
5. Configure:
   - **X-axis:** `started_at` (temporal)
   - **Metrics:** COUNT(*) or SUM(total_rows_synced)
6. Click **Update Chart**
7. Click **Save** to save your chart

## Available Tables

Once connected, you'll see these tables in the `analytics` schema:

- `sync_jobs` - All sync jobs
- `sync_executions` - Job execution history
- `sync_execution_logs` - Per-table execution details
- `database_connections` - Database connections
- `api_connections` - API connections (Zoho, SAP, etc.)
- `sync_schedules` - Job schedules
- `connection_health_check_log` - Connection health status
- ... and more

## Refresh Data

Superset shows **snapshot data** from Django SQLite.

To get latest data:

```bash
./refresh_data.sh
```

Run this whenever you want updated charts/dashboards.

## Common Commands

```bash
# Stop Superset
docker-compose down

# Start Superset
docker-compose up -d

# View logs
docker-compose logs -f superset

# Reset everything
docker-compose down -v
./init_superset.sh
```

## Troubleshooting

**Can't access http://localhost:8088?**
```bash
docker-compose ps  # Check if containers are running
docker-compose logs superset  # Check for errors
```

**Connection test fails?**
- Make sure you're using `superset_db` as host (not `localhost`)
- Check the SQLAlchemy URI has `options=-c%20search_path=analytics`

**No data in tables?**
```bash
./refresh_data.sh  # Sync data from Django SQLite
```

## Next Steps

1. ✅ Set up database connection
2. ✅ Create your first chart
3. 📊 Create a dashboard:
   - Go to **Dashboards** → **+ Dashboard**
   - Add charts to the dashboard
   - Arrange and resize
   - Save
4. 🔄 Set up regular data refresh (cron job):
   ```bash
   # Add to crontab: refresh every hour
   0 * * * * cd /path/to/superset_analytics && ./refresh_data.sh
   ```

## Full Documentation

See [README.md](README.md) for complete documentation.
