# Check PostgreSQL Startup Logs
# Find out why PostgreSQL won't start

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PostgreSQL Startup Error Diagnosis" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$dataDir = "C:\Program Files\PostgreSQL\17\data"
$logDir = "$dataDir\log"

# Check if log directory exists
if (Test-Path $logDir) {
    Write-Host "Found log directory: $logDir" -ForegroundColor Green
    Write-Host ""

    # Get the most recent log file
    $latestLog = Get-ChildItem $logDir -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

    if ($latestLog) {
        Write-Host "Latest log file: $($latestLog.Name)" -ForegroundColor Yellow
        Write-Host "Last modified: $($latestLog.LastWriteTime)" -ForegroundColor Gray
        Write-Host ""
        Write-Host "Last 50 lines of log:" -ForegroundColor Yellow
        Write-Host "----------------------------------------" -ForegroundColor Gray

        Get-Content $latestLog.FullName -Tail 50 | ForEach-Object {
            if ($_ -match "FATAL|ERROR") {
                Write-Host $_ -ForegroundColor Red
            } elseif ($_ -match "WARNING") {
                Write-Host $_ -ForegroundColor Yellow
            } else {
                Write-Host $_ -ForegroundColor White
            }
        }

        Write-Host "----------------------------------------" -ForegroundColor Gray
    } else {
        Write-Host "No log files found in $logDir" -ForegroundColor Yellow
    }
} else {
    Write-Host "Log directory not found: $logDir" -ForegroundColor Red
}

Write-Host ""
Write-Host "Checking for common issues..." -ForegroundColor Yellow
Write-Host ""

# Check if port 5432 is already in use
Write-Host "1. Checking if port 5432 is in use..." -ForegroundColor Yellow
$portInUse = netstat -ano | Select-String ":5432"
if ($portInUse) {
    Write-Host "   Port 5432 is in use by:" -ForegroundColor Red
    $portInUse | ForEach-Object {
        $line = $_.ToString().Trim()
        if ($line -match '\s+(\d+)\s*$') {
            $pid = $matches[1]
            $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($process) {
                Write-Host "   PID $pid - $($process.ProcessName)" -ForegroundColor Red
            }
        }
    }
    Write-Host "   [ISSUE FOUND] Another process is using port 5432" -ForegroundColor Red
} else {
    Write-Host "   [OK] Port 5432 is available" -ForegroundColor Green
}
Write-Host ""

# Check data directory permissions
Write-Host "2. Checking data directory permissions..." -ForegroundColor Yellow
if (Test-Path $dataDir) {
    $acl = Get-Acl $dataDir
    Write-Host "   [OK] Data directory exists and is accessible" -ForegroundColor Green
} else {
    Write-Host "   [ISSUE] Data directory not found: $dataDir" -ForegroundColor Red
}
Write-Host ""

# Check postgresql.conf syntax
Write-Host "3. Checking postgresql.conf..." -ForegroundColor Yellow
$postgresqlConf = "$dataDir\postgresql.conf"
if (Test-Path $postgresqlConf) {
    $content = Get-Content $postgresqlConf
    $listenLine = $content | Where-Object { $_ -match "^\s*listen_addresses\s*=" } | Select-Object -First 1

    if ($listenLine) {
        Write-Host "   listen_addresses: $listenLine" -ForegroundColor White

        # Check for syntax errors
        if ($listenLine -match "listen_addresses\s*=\s*'[^']*'\s*$|listen_addresses\s*=\s*`"[^`"]*`"\s*$") {
            Write-Host "   [OK] Syntax looks correct" -ForegroundColor Green
        } else {
            Write-Host "   [WARNING] Possible syntax issue" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "   [ISSUE] postgresql.conf not found" -ForegroundColor Red
}
Write-Host ""

# Check pg_hba.conf syntax
Write-Host "4. Checking pg_hba.conf..." -ForegroundColor Yellow
$pgHbaConf = "$dataDir\pg_hba.conf"
if (Test-Path $pgHbaConf) {
    $lines = Get-Content $pgHbaConf
    $invalidLines = $lines | Where-Object { $_ -match "^\s*host" } | Where-Object { ($_ -split "\s+").Count -lt 5 }

    if ($invalidLines) {
        Write-Host "   [WARNING] Possible syntax issues:" -ForegroundColor Yellow
        $invalidLines | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }
    } else {
        Write-Host "   [OK] No obvious syntax errors" -ForegroundColor Green
    }
} else {
    Write-Host "   [ISSUE] pg_hba.conf not found" -ForegroundColor Red
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Recommended Actions:" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Based on the diagnosis above:" -ForegroundColor White
Write-Host ""
Write-Host "If port 5432 is in use by another process:" -ForegroundColor Cyan
Write-Host "  1. Kill that process or change PostgreSQL port" -ForegroundColor White
Write-Host "  2. To kill: Stop-Process -Id [PID] -Force" -ForegroundColor Gray
Write-Host ""

Write-Host "If configuration files have errors:" -ForegroundColor Cyan
Write-Host "  1. Restore from backup:" -ForegroundColor White
Write-Host "     Copy-Item '$dataDir\backup_*\postgresql.conf.backup' '$dataDir\postgresql.conf'" -ForegroundColor Gray
Write-Host "     Copy-Item '$dataDir\backup_*\pg_hba.conf.backup' '$dataDir\pg_hba.conf'" -ForegroundColor Gray
Write-Host "  2. Then re-run .\fix_postgres_for_docker_v2.ps1" -ForegroundColor Gray
Write-Host ""

Write-Host "Try starting manually to see error:" -ForegroundColor Cyan
Write-Host "  cd 'C:\Program Files\PostgreSQL\17\bin'" -ForegroundColor White
Write-Host "  .\pg_ctl.exe start -D 'C:\Program Files\PostgreSQL\17\data'" -ForegroundColor White
Write-Host ""
