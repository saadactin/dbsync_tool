# Health Check Script (Windows PowerShell)
# Run with: .\check_status.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Superset Analytics - Status Check" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Docker
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Docker: Not running" -ForegroundColor Red
        Write-Host "   Please start Docker Desktop" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "✅ Docker: Running" -ForegroundColor Green
} catch {
    Write-Host "❌ Docker: Not running" -ForegroundColor Red
    exit 1
}

# Check containers
Write-Host ""
Write-Host "Container Status:" -ForegroundColor Yellow
Write-Host "----------------" -ForegroundColor Yellow

$containers = @("superset", "superset_db", "superset_cache", "superset_worker")
$allRunning = $true

foreach ($container in $containers) {
    $status = docker inspect -f '{{.State.Status}}' $container 2>$null
    if ($LASTEXITCODE -eq 0) {
        $health = docker inspect -f '{{.State.Health.Status}}' $container 2>$null
        if ($status -eq "running") {
            if ($health -and $health -ne "healthy" -and $health -ne "") {
                Write-Host "⚠️  $container`: running (health: $health)" -ForegroundColor Yellow
                $allRunning = $false
            } else {
                Write-Host "✅ $container`: running" -ForegroundColor Green
            }
        } else {
            Write-Host "❌ $container`: $status" -ForegroundColor Red
            $allRunning = $false
        }
    } else {
        Write-Host "❌ $container`: not found" -ForegroundColor Red
        $allRunning = $false
    }
}

# Check services
Write-Host ""
Write-Host "Service Health:" -ForegroundColor Yellow
Write-Host "---------------" -ForegroundColor Yellow

# Postgres
$pgResult = docker-compose exec -T superset_db pg_isready -U superset 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ PostgreSQL: Ready" -ForegroundColor Green
} else {
    Write-Host "❌ PostgreSQL: Not ready" -ForegroundColor Red
    $allRunning = $false
}

# Redis
$redisResult = docker-compose exec -T superset_cache redis-cli ping 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Redis: Ready" -ForegroundColor Green
} else {
    Write-Host "❌ Redis: Not ready" -ForegroundColor Red
    $allRunning = $false
}

# Superset
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8088/health" -TimeoutSec 3 -UseBasicParsing 2>$null
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ Superset Web: Ready" -ForegroundColor Green
    } else {
        Write-Host "❌ Superset Web: Not ready" -ForegroundColor Red
        $allRunning = $false
    }
} catch {
    Write-Host "❌ Superset Web: Not ready" -ForegroundColor Red
    $allRunning = $false
}

# Django SQLite
Write-Host ""
Write-Host "Data Sources:" -ForegroundColor Yellow
Write-Host "-------------" -ForegroundColor Yellow

$sqlitePath = "..\dbsync_tool\db.sqlite3"
if (Test-Path $sqlitePath) {
    $size = (Get-Item $sqlitePath).Length / 1MB
    Write-Host "✅ Django SQLite: Found ($([math]::Round($size, 2)) MB)" -ForegroundColor Green
} else {
    Write-Host "❌ Django SQLite: Not found at $sqlitePath" -ForegroundColor Red
}

# Analytics schema
Write-Host ""
Write-Host "Analytics Schema:" -ForegroundColor Yellow
Write-Host "-----------------" -ForegroundColor Yellow

$tableCount = docker-compose exec -T superset_db psql -U superset -d superset -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'analytics'" 2>&1
if ($LASTEXITCODE -eq 0) {
    $count = $tableCount.Trim()
    if ([int]$count -gt 0) {
        Write-Host "✅ Analytics tables: $count tables found" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Analytics tables: 0 tables (run .\refresh_data.ps1)" -ForegroundColor Yellow
    }
} else {
    Write-Host "❌ Analytics schema: Cannot check" -ForegroundColor Red
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($allRunning) {
    Write-Host "✅ All systems operational" -ForegroundColor Green
    Write-Host ""
    Write-Host "🌐 Superset: http://localhost:8088" -ForegroundColor Cyan
    Write-Host "   Login: admin / admin" -ForegroundColor White
    Write-Host ""
    Write-Host "To refresh data: .\refresh_data.ps1" -ForegroundColor Yellow
} else {
    Write-Host "⚠️  Some services need attention" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Try:" -ForegroundColor Yellow
    Write-Host "  docker-compose down" -ForegroundColor White
    Write-Host "  docker-compose up -d" -ForegroundColor White
    Write-Host "  docker-compose logs -f" -ForegroundColor White
}
Write-Host "========================================" -ForegroundColor Cyan
