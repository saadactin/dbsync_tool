# DB Sync Tool - Apache Superset Analytics

Standalone analytics layer for visualizing DB Sync Tool data using Apache Superset.

## Architecture

```
Django SQLite (dbsync_tool/db.sqlite3)
         ↓
  sync_to_postgres.py (ETL)
         ↓
Postgres 'analytics' schema
         ↓
   Apache Superset
```

**Why this architecture?**
- Django uses SQLite by default
- Superset runs in Docker and cannot access SQLite files outside the container
- Solution: Sync data from SQLite → Postgres → Superset
- Dashboards show snapshot data (refresh on-demand)

## Prerequisites

- **Docker** and **Docker Compose** installed
- **Python 3.8+** with pip
- **Django DB Sync Tool** running with SQLite database at `../dbsync_tool/db.sqlite3`

## Quick Start

### 1. First-Time Setup

```bash
cd superset_analytics
./init_superset.sh
```

This script will:
- Pull Docker images (Superset, Postgres, Redis)
- Start all containers
- Create analytics schema in Postgres
- Sync initial data from Django SQLite
- Set up admin user

⏱️ **Expected time:** 5-10 minutes

### 2. Access Superset

Open browser: **http://localhost:8088**

**Login credentials:**
- Username: `admin`
- Password: `admin`

### 3. Configure Database Connection (First Time Only)

After logging in:

1. Go to: **Settings** → **Database Connections** → **+ Database**
2. Fill in:
   - **Name:** `DB Sync Analytics`
   - **SQLAlchemy URI:**
     ```
     postgresql://superset:superset@superset_db:5432/superset?options=-c%20search_path=analytics
     ```
3. Click **Test Connection** → Should show "Connection looks good!"
4. Click **Connect**

### 4. Build Your First Dataset

1. Go to: **Data** → **Datasets** → **+ Dataset**
2. Select:
   - **Database:** `DB Sync Analytics`
   - **Schema:** `analytics`
   - **Table:** `sync_jobs` (or any table you want to explore)
3. Click **Create Dataset and Create Chart**

### 5. Create Dashboards

Now you can create dashboards using any of these tables from the `analytics` schema:

| Table Name | Description |
|------------|-------------|
| `sync_jobs` | All sync jobs (name, status, timestamps, connections) |
| `sync_executions` | Job execution records (started, completed, rows synced) |
| `sync_execution_logs` | Per-table execution logs (rows fetched, inserted, errors) |
| `database_connections` | Database connections (type, host, status) |
| `api_connections` | API connections (Zoho, SAP, Azure DevOps) |
| `sync_schedules` | Job schedules (cron, interval, next run) |
| `sync_checkpoints` | Incremental sync checkpoints |
| `connection_test_logs` | Connection test history |
| `connection_health_check_log` | Daily health check results |
| `notification_logs` | Email notification history |
| `sync_verification_reports` | Data verification reports |

## Regular Usage

### Refresh Data from Django

Since Django uses SQLite, Superset dashboards show **snapshot data** (not real-time).

**To refresh data:**

```bash
cd superset_analytics
./refresh_data.sh
```

This syncs the latest data from Django SQLite to Postgres. Run this whenever you want updated dashboards.

⏱️ **Expected time:** 10-30 seconds

### Stop Superset

```bash
docker-compose down
```

### Restart Superset

```bash
docker-compose up -d
```

### Wipe Everything and Start Fresh

```bash
docker-compose down -v  # Deletes all data
./init_superset.sh       # Full setup from scratch
```

## Dashboard Ideas

### 1. Sync Job Overview
- **Big Number:** Total jobs run (count of `sync_executions`)
- **Pie Chart:** Jobs by status (`sync_jobs.status`)
- **Line Chart:** Job executions over time (`sync_executions.started_at`)
- **Bar Chart:** Average execution duration per day

### 2. Connection Health
- **Table:** All connections with last test time
- **Bar Chart:** Success rate by database type
- **Big Number:** Total active connections
- **Table:** Most active connections (join `sync_jobs` with `database_connections`)

### 3. Performance Analytics
- **Bar Chart:** Rows synced per day (`sync_executions.total_rows_synced`)
- **Line Chart:** Data volume trend over time
- **Table:** Top 10 slowest jobs (execution duration)
- **Heatmap:** Job runs by hour and day of week

### 4. Error Analysis
- **Bar Chart:** Most common error types (parse `sync_execution_logs.error_message`)
- **Table:** Failed jobs with connection names
- **Line Chart:** Error rate trend (failed vs total executions)
- **Table:** Jobs needing attention (failed in last 7 days)

## Troubleshooting

### "Connection refused" when running sync script

**Problem:** Docker containers not running

**Solution:**
```bash
docker-compose up -d
docker-compose ps  # Check all services are "Up"
```

### "Postgres is not ready" timeout

**Problem:** Postgres taking too long to start

**Solution:**
```bash
docker-compose down
docker-compose up -d
# Wait 30 seconds
docker-compose logs superset_db  # Check logs
```

### "No such file or directory: db.sqlite3"

**Problem:** Django SQLite path is wrong

**Solution:**
1. Check path in `.env`:
   ```ini
   DJANGO_SQLITE_PATH=../dbsync_tool/db.sqlite3
   ```
2. Verify Django database exists:
   ```bash
   ls -la ../dbsync_tool/db.sqlite3
   ```

### Dashboards show old data

**Problem:** Data not refreshed

**Solution:**
```bash
./refresh_data.sh
```

### Can't log in to Superset

**Problem:** Wrong credentials

**Solution:**
1. Check `.env` file for `ADMIN_USERNAME` and `ADMIN_PASSWORD`
2. Default is `admin` / `admin`
3. Reset admin password:
   ```bash
   docker-compose exec superset superset fab reset-password --username admin
   ```

## Configuration

### Change Admin Credentials

Edit `.env`:
```ini
ADMIN_USERNAME=your_username
ADMIN_PASSWORD=your_secure_password
ADMIN_EMAIL=your_email@example.com
```

Then restart:
```bash
docker-compose down
docker-compose up -d
```

### Change Postgres Port (if 5433 is in use)

Edit `docker-compose.yml`:
```yaml
services:
  superset_db:
    ports:
      - "5434:5432"  # Change 5433 → 5434
```

Edit `.env`:
```ini
SUPERSET_DB_PORT=5434
```

## Upgrade to PostgreSQL for Django (Optional)

Currently, Django uses SQLite and data is synced to Superset via the ETL script.

**To make Superset read Django data directly (real-time):**

1. **Switch Django to PostgreSQL:**
   - In `dbsync_tool/.env`, set:
     ```ini
     DB_ENGINE=postgres
     POSTGRES_DB=django_app
     POSTGRES_USER=django_user
     POSTGRES_PASSWORD=django_password
     POSTGRES_HOST=localhost
     POSTGRES_PORT=5432
     ```

2. **Run Django migrations:**
   ```bash
   cd ../dbsync_tool
   python manage.py migrate
   ```

3. **Update Superset connection to point to Django Postgres** (instead of analytics schema)

4. **Delete sync_to_postgres.py** (no longer needed)

## Technical Stack

- **Superset:** Apache Superset latest (4.x)
- **Database:** PostgreSQL 15 (Superset metadata + analytics schema)
- **Cache:** Redis 7
- **ETL:** Python 3 + pandas + SQLAlchemy
- **Orchestration:** Docker Compose 3.8

## Ports Used

| Service | Port | Access |
|---------|------|--------|
| Superset | 8088 | http://localhost:8088 |
| Postgres | 5433 | localhost:5433 (external access) |
| Redis | 6380 | localhost:6380 (external access) |

## Security Notes

**⚠️ This setup is for DEVELOPMENT/TESTING only!**

**For production:**
1. Change `SUPERSET_SECRET_KEY` to a random 32+ character string
2. Use strong passwords for admin and database users
3. Enable HTTPS (set `SESSION_COOKIE_SECURE = True` in `superset_config.py`)
4. Restrict network access to containers
5. Use environment-specific `.env` files (never commit `.env` to Git)
6. Regular backups of Postgres data

## Support

For issues with:
- **Superset itself:** https://github.com/apache/superset/issues
- **This integration:** Check Django DB Sync Tool documentation

## License

Same as parent project (DB Sync Tool)
