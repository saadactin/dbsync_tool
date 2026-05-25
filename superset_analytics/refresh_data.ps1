# Refresh Superset Analytics Data (Windows PowerShell)
# Run with: .\refresh_data.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Refreshing Superset Analytics Data" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Started: $(Get-Date)" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Docker is not running. Please start Docker Desktop." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

# Check if containers are running
$containersRunning = docker-compose ps -q | Measure-Object | Select-Object -ExpandProperty Count

if ($containersRunning -eq 0) {
    Write-Host "📦 Starting Docker containers..." -ForegroundColor Yellow
    docker-compose up -d

    Write-Host "⏳ Waiting for Postgres to be ready..." -ForegroundColor Yellow
    for ($i = 1; $i -le 30; $i++) {
        $result = docker-compose exec -T superset_db pg_isready -U superset 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Postgres is ready" -ForegroundColor Green
            break
        }
        Write-Host "   Waiting... ($i/30)" -ForegroundColor Gray
        Start-Sleep -Seconds 2
    }
}

# Run sync script
Write-Host ""
Write-Host "📊 Syncing data from Django SQLite to Postgres..." -ForegroundColor Yellow
python sync_to_postgres.py

Write-Host ""
Write-Host "✅ Data refresh complete!" -ForegroundColor Green
Write-Host "🌐 Open Superset: http://localhost:8088" -ForegroundColor Cyan
Write-Host "   Login: admin / admin" -ForegroundColor White
Write-Host ""
