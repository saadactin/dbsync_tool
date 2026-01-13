# DB Sync Tool Health Check Script (Windows PowerShell)
# Usage: .\scripts\health_check.ps1

param(
    [string]$BaseUrl = "http://localhost:8000"
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

$allHealthy = $true

Write-Step "DB Sync Tool Health Check"
Write-Info "Base URL: $BaseUrl"

# Check 1: Health endpoint
Write-Step "Check 1: Application Health Endpoint"
try {
    $response = Invoke-WebRequest -Uri "$BaseUrl/health/" -Method GET -UseBasicParsing -ErrorAction Stop
    if ($response.StatusCode -eq 200) {
        $healthData = $response.Content | ConvertFrom-Json
        Write-Success "Health endpoint accessible"
        Write-Info "Overall Status: $($healthData.overall_status)"
        
        foreach ($check in $healthData.checks.PSObject.Properties) {
            $status = $check.Value.status
            if ($status -eq "healthy") {
                Write-Success "$($check.Name): $status"
            } else {
                Write-Error "$($check.Name): $status - $($check.Value.message)"
                $allHealthy = $false
            }
        }
    } else {
        Write-Error "Health endpoint returned status code: $($response.StatusCode)"
        $allHealthy = $false
    }
} catch {
    Write-Error "Cannot connect to health endpoint: $_"
    $allHealthy = $false
}

# Check 2: Database connectivity (if Python available)
Write-Step "Check 2: Database Connectivity"
try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $projectDir = Join-Path (Split-Path -Parent $scriptDir) "dbsync_tool"
    Push-Location $projectDir
    
    $venvPath = Join-Path $projectDir "venv"
    if (Test-Path $venvPath) {
        & "$venvPath\Scripts\python.exe" -c "from django.core.management import execute_from_command_line; import os; import django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings'); django.setup(); from django.db import connection; connection.ensure_connection(); print('OK')" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Database connection successful"
        } else {
            Write-Error "Database connection failed"
            $allHealthy = $false
        }
    } else {
        Write-Info "Virtual environment not found, skipping database check"
    }
    Pop-Location
} catch {
    Write-Info "Cannot check database connectivity: $_"
}

# Check 3: Redis connectivity (if redis-cli available)
Write-Step "Check 3: Redis Connectivity"
try {
    $redisTest = redis-cli ping 2>&1
    if ($redisTest -eq "PONG") {
        Write-Success "Redis connection successful"
    } else {
        Write-Error "Redis connection failed: $redisTest"
        $allHealthy = $false
    }
} catch {
    Write-Info "redis-cli not found, skipping Redis check"
}

# Check 4: Application accessibility
Write-Step "Check 4: Application Accessibility"
try {
    $response = Invoke-WebRequest -Uri "$BaseUrl/" -Method GET -UseBasicParsing -ErrorAction Stop
    if ($response.StatusCode -eq 200 -or $response.StatusCode -eq 302) {
        Write-Success "Application is accessible"
    } else {
        Write-Error "Application returned status code: $($response.StatusCode)"
        $allHealthy = $false
    }
} catch {
    Write-Error "Cannot access application: $_"
    $allHealthy = $false
}

# Summary
Write-Step "Health Check Summary"
if ($allHealthy) {
    Write-Success "All health checks passed!"
    exit 0
} else {
    Write-Error "Some health checks failed!"
    exit 1
}

