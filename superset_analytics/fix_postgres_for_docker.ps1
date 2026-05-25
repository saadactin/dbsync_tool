# PostgreSQL Configuration Script for Docker Access
# This script configures PostgreSQL to accept connections from Docker containers

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PostgreSQL Docker Access Configuration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Requires Administrator privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script requires Administrator privileges" -ForegroundColor Red
    Write-Host "Please right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Then run: .\fix_postgres_for_docker.ps1" -ForegroundColor White
    exit 1
}

# Step 1: Find PostgreSQL installation
Write-Host "Step 1: Finding PostgreSQL installation..." -ForegroundColor Yellow

$pgPaths = @(
    "C:\Program Files\PostgreSQL\16\data",
    "C:\Program Files\PostgreSQL\15\data",
    "C:\Program Files\PostgreSQL\14\data",
    "C:\Program Files\PostgreSQL\13\data",
    "C:\PostgreSQL\data"
)

$dataDir = $null
foreach ($path in $pgPaths) {
    if (Test-Path "$path\postgresql.conf") {
        $dataDir = $path
        break
    }
}

if (-not $dataDir) {
    Write-Host "Could not find PostgreSQL data directory automatically." -ForegroundColor Red
    Write-Host ""
    $customPath = Read-Host "Please enter the full path to your PostgreSQL data directory"
    if (Test-Path "$customPath\postgresql.conf") {
        $dataDir = $customPath
    } else {
        Write-Host "ERROR: postgresql.conf not found at: $customPath" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Found PostgreSQL at: $dataDir" -ForegroundColor Green
Write-Host ""

# Step 2: Backup configuration files
Write-Host "Step 2: Creating backups..." -ForegroundColor Yellow

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "$dataDir\backup_$timestamp"

try {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Copy-Item "$dataDir\postgresql.conf" "$backupDir\postgresql.conf.backup"
    Copy-Item "$dataDir\pg_hba.conf" "$backupDir\pg_hba.conf.backup"
    Write-Host "Backups created at: $backupDir" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to create backups: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Modify postgresql.conf
Write-Host "Step 3: Configuring postgresql.conf..." -ForegroundColor Yellow

$postgresqlConf = "$dataDir\postgresql.conf"
$content = Get-Content $postgresqlConf

$modified = $false
$newContent = @()

foreach ($line in $content) {
    if ($line -match "^\s*#?\s*listen_addresses\s*=") {
        # Replace with listen on all interfaces
        $newContent += "listen_addresses = '*'  # Modified by fix_postgres_for_docker.ps1"
        $modified = $true
        Write-Host "  - Set listen_addresses = '*'" -ForegroundColor Gray
    } else {
        $newContent += $line
    }
}

if (-not $modified) {
    # Add listen_addresses if not found
    $newContent += ""
    $newContent += "# Added by fix_postgres_for_docker.ps1"
    $newContent += "listen_addresses = '*'"
    Write-Host "  - Added listen_addresses = '*'" -ForegroundColor Gray
}

try {
    $newContent | Set-Content $postgresqlConf -Encoding UTF8
    Write-Host "postgresql.conf updated successfully" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to update postgresql.conf: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 4: Modify pg_hba.conf
Write-Host "Step 4: Configuring pg_hba.conf..." -ForegroundColor Yellow

$pgHbaConf = "$dataDir\pg_hba.conf"
$hbaContent = Get-Content $pgHbaConf

# Check if our rules already exist
$hasDockerRule = $hbaContent | Where-Object { $_ -match "172\.20\.0\.0/16" }
$hasLocalRule = $hbaContent | Where-Object { $_ -match "192\.168\.0\.0/16" }

if (-not $hasDockerRule -or -not $hasLocalRule) {
    # Add our rules
    $hbaContent += ""
    $hbaContent += "# Added by fix_postgres_for_docker.ps1 on $(Get-Date)"
    $hbaContent += "# Allow Docker containers to connect"
    $hbaContent += "host    all             all             172.20.0.0/16           md5"
    $hbaContent += "host    all             all             172.24.0.0/16           md5"
    $hbaContent += "# Allow local network connections"
    $hbaContent += "host    all             all             192.168.0.0/16          md5"

    try {
        $hbaContent | Set-Content $pgHbaConf -Encoding UTF8
        Write-Host "  - Added Docker network rules (172.20.0.0/16, 172.24.0.0/16)" -ForegroundColor Gray
        Write-Host "  - Added local network rules (192.168.0.0/16)" -ForegroundColor Gray
        Write-Host "pg_hba.conf updated successfully" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to update pg_hba.conf: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Rules already exist in pg_hba.conf" -ForegroundColor Green
}
Write-Host ""

# Step 5: Restart PostgreSQL service
Write-Host "Step 5: Restarting PostgreSQL service..." -ForegroundColor Yellow

$service = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1

if ($service) {
    Write-Host "Found service: $($service.Name)" -ForegroundColor Gray
    try {
        Restart-Service $service.Name -Force
        Start-Sleep -Seconds 3

        $status = (Get-Service $service.Name).Status
        if ($status -eq "Running") {
            Write-Host "PostgreSQL service restarted successfully" -ForegroundColor Green
        } else {
            Write-Host "WARNING: PostgreSQL service status: $status" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "ERROR: Failed to restart service: $_" -ForegroundColor Red
        Write-Host "Please restart PostgreSQL manually via services.msc" -ForegroundColor Yellow
    }
} else {
    Write-Host "WARNING: Could not find PostgreSQL service" -ForegroundColor Yellow
    Write-Host "Please restart PostgreSQL manually:" -ForegroundColor Yellow
    Write-Host "  1. Press Win+R" -ForegroundColor White
    Write-Host "  2. Type: services.msc" -ForegroundColor White
    Write-Host "  3. Find PostgreSQL service and restart it" -ForegroundColor White
}
Write-Host ""

# Step 6: Test connection
Write-Host "Step 6: Testing connection..." -ForegroundColor Yellow

Write-Host "Testing connection from localhost..." -ForegroundColor Gray
$testResult = psql -U migration_user -d tauseef -c "SELECT version();" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  - Localhost connection: OK" -ForegroundColor Green
} else {
    Write-Host "  - Localhost connection: FAILED" -ForegroundColor Red
}
Write-Host ""

# Step 7: Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Configuration Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "What was changed:" -ForegroundColor Yellow
Write-Host "  1. postgresql.conf: listen_addresses = '*'" -ForegroundColor White
Write-Host "  2. pg_hba.conf: Added Docker and local network access" -ForegroundColor White
Write-Host "  3. PostgreSQL service restarted" -ForegroundColor White
Write-Host ""
Write-Host "Backups saved at:" -ForegroundColor Yellow
Write-Host "  $backupDir" -ForegroundColor White
Write-Host ""
Write-Host "Now try connecting from Superset with these options:" -ForegroundColor Yellow
Write-Host ""
Write-Host "Option 1 - Docker Gateway (Recommended):" -ForegroundColor Cyan
Write-Host "  Host: 172.24.0.1" -ForegroundColor White
Write-Host "  Port: 5432" -ForegroundColor White
Write-Host "  Database: tauseef" -ForegroundColor White
Write-Host "  Username: migration_user" -ForegroundColor White
Write-Host "  Password: StrongPassword123" -ForegroundColor White
Write-Host ""
Write-Host "Option 2 - Windows IP:" -ForegroundColor Cyan
Write-Host "  Host: 192.168.5.105" -ForegroundColor White
Write-Host "  Port: 5432" -ForegroundColor White
Write-Host "  Database: tauseef" -ForegroundColor White
Write-Host "  Username: migration_user" -ForegroundColor White
Write-Host "  Password: StrongPassword123" -ForegroundColor White
Write-Host ""
Write-Host "Option 3 - SQLAlchemy URI (in Advanced tab):" -ForegroundColor Cyan
Write-Host "  postgresql://migration_user:StrongPassword123@172.24.0.1:5432/tauseef?options=-c search_path=analytics" -ForegroundColor White
Write-Host ""
Write-Host "If connection still fails:" -ForegroundColor Yellow
Write-Host "  1. Check Windows Firewall (allow PostgreSQL port 5432)" -ForegroundColor White
Write-Host "  2. Verify PostgreSQL service is running: services.msc" -ForegroundColor White
Write-Host "  3. Check Docker network: docker network inspect superset_analytics_superset_network" -ForegroundColor White
Write-Host ""
