# Superset Analytics Setup Script (Windows PowerShell)
# Run with: .\init_superset.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DB Sync Tool - Superset Analytics Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Started: $(Get-Date)" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
Write-Host "Checking Docker..." -ForegroundColor Yellow
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Docker is not running. Please start Docker Desktop and try again." -ForegroundColor Red
        exit 1
    }
    Write-Host "Docker is running" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Docker is not installed or not running." -ForegroundColor Red
    Write-Host "Please install Docker Desktop: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
    exit 1
}

# Check if .env exists
if (-not (Test-Path .env)) {
    Write-Host "No .env file found. Copying from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "Created .env file" -ForegroundColor Green
    Write-Host "Review and update credentials if needed" -ForegroundColor Cyan
    Write-Host ""
}

# Load environment variables
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.+)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

# Pull Docker images
Write-Host ""
Write-Host "Pulling Docker images..." -ForegroundColor Yellow
docker-compose pull

# Start containers
Write-Host ""
Write-Host "Starting Docker containers..." -ForegroundColor Yellow
docker-compose up -d

# Wait for Postgres
Write-Host ""
Write-Host "Waiting for Postgres to be ready..." -ForegroundColor Yellow
$postgresReady = $false
for ($i = 1; $i -le 30; $i++) {
    $result = docker-compose exec -T superset_db pg_isready -U superset 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Postgres is ready" -ForegroundColor Green
        $postgresReady = $true
        break
    }
    Write-Host "Waiting... ($i/30)" -ForegroundColor Gray
    Start-Sleep -Seconds 2
}

if (-not $postgresReady) {
    Write-Host "ERROR: Timeout waiting for Postgres" -ForegroundColor Red
    Write-Host "Check logs: docker-compose logs superset_db" -ForegroundColor Yellow
    exit 1
}

# Wait for Superset
Write-Host ""
Write-Host "Waiting for Superset to be ready..." -ForegroundColor Yellow
$supersetReady = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8088/health" -TimeoutSec 2 -UseBasicParsing 2>$null
        if ($response.StatusCode -eq 200) {
            Write-Host "Superset is ready" -ForegroundColor Green
            $supersetReady = $true
            break
        }
    } catch {
        # Ignore errors, keep trying
    }
    Write-Host "Waiting... ($i/60)" -ForegroundColor Gray
    Start-Sleep -Seconds 3
}

if (-not $supersetReady) {
    Write-Host "WARNING: Superset might still be initializing..." -ForegroundColor Yellow
    Write-Host "Check status: docker-compose logs superset" -ForegroundColor Yellow
}

# Install Python dependencies
Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
pip install -q -r requirements_sync.txt

# Run initial data sync
Write-Host ""
Write-Host "Running initial data sync..." -ForegroundColor Yellow
python sync_to_postgres.py

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Superset is running at: http://localhost:8088" -ForegroundColor Cyan
Write-Host ""
Write-Host "Login credentials:" -ForegroundColor Yellow
Write-Host "Username: $env:ADMIN_USERNAME" -ForegroundColor White
Write-Host "Password: $env:ADMIN_PASSWORD" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Open http://localhost:8088 in your browser" -ForegroundColor White
Write-Host "2. Log in with the credentials above" -ForegroundColor White
Write-Host "3. Configure database connection:" -ForegroundColor White
Write-Host "   - Go to: Settings -> Database Connections" -ForegroundColor Gray
Write-Host "   - Add Database" -ForegroundColor Gray
Write-Host "   - Name: DB Sync Analytics" -ForegroundColor Gray
Write-Host "   - SQLAlchemy URI: postgresql://superset:superset@superset_db:5432/superset?options=-c%20search_path=analytics" -ForegroundColor Gray
Write-Host "   - Test Connection -> Connect" -ForegroundColor Gray
Write-Host "4. Create datasets from analytics schema tables" -ForegroundColor White
Write-Host "5. Build dashboards from the datasets" -ForegroundColor White
Write-Host ""
Write-Host "To refresh data from Django SQLite:" -ForegroundColor Yellow
Write-Host ".\refresh_data.ps1" -ForegroundColor White
Write-Host ""
Write-Host "To stop Superset:" -ForegroundColor Yellow
Write-Host "docker-compose down" -ForegroundColor White
Write-Host ""
Write-Host "To wipe all data and start fresh:" -ForegroundColor Yellow
Write-Host "docker-compose down -v" -ForegroundColor White
Write-Host ".\init_superset.ps1" -ForegroundColor White
Write-Host ""
