# Quick Start Guide - DB Sync Tool

## Issue Found: Redis Not Running

The auto-start feature for "Run Once (Manual)" jobs requires **Redis and Celery Worker** to be running. Since Redis is not running, the job was created but the execution didn't start automatically.

## Solution: Start Required Services

You need to start these services in separate terminal windows:

### Terminal 1: Start Redis
```powershell
redis-server
```

### Terminal 2: Start Celery Worker  
```powershell
cd C:\Users\SaadSayyed\Desktop\test_proj\tauseef_sir\dbsync_tool
.\venv\Scripts\Activate.ps1
celery -A dbsync_tool worker --loglevel=info
```

### Terminal 3: Start Django Server (if not already running)
```powershell
cd C:\Users\SaadSayyed\Desktop\test_proj\tauseef_sir\dbsync_tool
.\venv\Scripts\Activate.ps1
python manage.py runserver 8005
```

## After Starting Services

1. **Refresh the job detail page** - The job should show as "Completed" with execution history
2. **Or create a new job** - The auto-start will work properly with Redis running
3. **Or click "Run Now"** - Manual execution will work with Celery worker running

## Current Job Status

Your job "saadd" has been executed successfully (40 rows synced) using direct execution. It should now show as "Completed" in the UI.

