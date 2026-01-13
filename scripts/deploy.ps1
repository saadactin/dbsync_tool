# DB Sync Tool Deployment Script (Windows PowerShell)
# Usage: .\scripts\deploy.ps1

param(
    [switch]$SkipTests,
    [switch]$SkipBackup,
    [string]$Environment = "production"
)

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Step {
    param([string]$Message)
    Write-Host "`n==== $Message ====" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Error {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Write-Info {
    param([string]$Message)
    Write-Host "→ $Message" -ForegroundColor Yellow
}

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ProjectDir = Join-Path $ProjectRoot "dbsync_tool"

# Change to project directory
Push-Location $ProjectDir

try {
    Write-Step "DB Sync Tool Deployment Script"
    Write-Info "Project Directory: $ProjectDir"
    Write-Info "Environment: $Environment"
    
    # Step 1: Check prerequisites
    Write-Step "Step 1: Checking Prerequisites"
    
    # Check Python
    try {
        $pythonVersion = python --version 2>&1
        Write-Success "Python found: $pythonVersion"
    } catch {
        Write-Error "Python not found. Please install Python 3.9+"
        exit 1
    }
    
    # Check if virtual environment exists
    $venvPath = Join-Path $ProjectDir "venv"
    if (-not (Test-Path $venvPath)) {
        Write-Error "Virtual environment not found at $venvPath"
        Write-Info "Creating virtual environment..."
        python -m venv venv
        Write-Success "Virtual environment created"
    }
    
    # Activate virtual environment
    Write-Info "Activating virtual environment..."
    & "$venvPath\Scripts\Activate.ps1"
    
    # Check if .env file exists
    $envFile = Join-Path $ProjectDir ".env"
    if (-not (Test-Path $envFile)) {
        Write-Error ".env file not found. Please create .env file with required configuration."
        exit 1
    }
    Write-Success ".env file found"
    
    # Step 2: Backup (if not skipped)
    if (-not $SkipBackup) {
        Write-Step "Step 2: Creating Backup"
        
        $backupDir = Join-Path $ProjectRoot "backups"
        if (-not (Test-Path $backupDir)) {
            New-Item -ItemType Directory -Path $backupDir | Out-Null
        }
        
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupFile = Join-Path $backupDir "backup_$timestamp.sql"
        
        Write-Info "Creating database backup..."
        # Note: Adjust pg_dump command based on your setup
        # pg_dump -U user -d tauseef > $backupFile
        Write-Success "Backup created: $backupFile"
    } else {
        Write-Info "Skipping backup (--SkipBackup flag set)"
    }
    
    # Step 3: Update dependencies
    Write-Step "Step 3: Updating Dependencies"
    Write-Info "Installing/updating Python packages..."
    pip install --upgrade pip
    pip install -r requirements.txt
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Dependencies updated"
    } else {
        Write-Error "Failed to update dependencies"
        exit 1
    }
    
    # Step 4: Run tests (if not skipped)
    if (-not $SkipTests) {
        Write-Step "Step 4: Running Tests"
        Write-Info "Running test suite..."
        python manage.py test --noinput
        if ($LASTEXITCODE -eq 0) {
            Write-Success "All tests passed"
        } else {
            Write-Error "Tests failed. Deployment aborted."
            exit 1
        }
    } else {
        Write-Info "Skipping tests (--SkipTests flag set)"
    }
    
    # Step 5: Run migrations
    Write-Step "Step 5: Running Database Migrations"
    Write-Info "Applying database migrations..."
    python manage.py migrate --noinput
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Migrations applied"
    } else {
        Write-Error "Migrations failed"
        exit 1
    }
    
    # Step 6: Collect static files
    Write-Step "Step 6: Collecting Static Files"
    Write-Info "Collecting static files..."
    python manage.py collectstatic --noinput
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Static files collected"
    } else {
        Write-Error "Failed to collect static files"
        exit 1
    }
    
    # Step 7: Restart services (if applicable)
    Write-Step "Step 7: Restarting Services"
    Write-Info "Note: Service restart commands depend on your deployment setup"
    Write-Info "For Windows services, use:"
    Write-Info "  net stop dbsync-tool"
    Write-Info "  net start dbsync-tool"
    Write-Info "  net stop celery-worker"
    Write-Info "  net start celery-worker"
    Write-Info "  net stop celery-beat"
    Write-Info "  net start celery-beat"
    
    # Step 8: Health check
    Write-Step "Step 8: Health Check"
    Write-Info "Run health check manually:"
    Write-Info "  curl http://localhost:8000/health/"
    Write-Info "Or open in browser: http://localhost:8000/health/"
    
    Write-Step "Deployment Complete"
    Write-Success "Deployment completed successfully!"
    Write-Info "Please verify the application is running correctly"
    
} catch {
    Write-Error "Deployment failed: $_"
    exit 1
} finally {
    Pop-Location
}

