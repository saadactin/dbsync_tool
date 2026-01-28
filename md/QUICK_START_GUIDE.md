# Quick Start Guide - DB Sync Tool

## Initial Setup

### 1. Database Migrations

Run migrations to set up the database schema:

```bash
python manage.py migrate
```

### 2. Create Super Admin User

After initial setup, create the Super Admin user (required for RBAC system):

#### Using Management Command
```bash
python manage.py create_super_admin --username root --email root@example.com --password YourSecurePassword123
```

#### Using Environment Variable
```bash
# Linux/Mac
export SUPER_ADMIN_PASSWORD=YourSecurePassword123
python manage.py create_super_admin --username root

# Windows PowerShell
$env:SUPER_ADMIN_PASSWORD='YourSecurePassword123'
python manage.py create_super_admin --username root
```

**Security Note:** Never commit passwords to version control. Use environment variables or secure secret management.

### 3. Create Admin Users (Tenant Owners)

After creating Super Admin, you can create Admin users (tenant owners) via:

#### Using Management Command
```bash
python manage.py create_admin --username admin1 --email admin1@example.com --password AdminPassword123
```

#### Using Web Interface
1. Login as Super Admin
2. Navigate to User Management
3. Click "Create User"
4. Select "Admin" role
5. Fill in user details and save

**Note**: Admin users are tenant owners. Each Admin manages their own tenant and can create Operator/Viewer users.

### 3. Start Development Server

```bash
python manage.py runserver 8005
```

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

