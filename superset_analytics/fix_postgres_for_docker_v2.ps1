# PostgreSQL Configuration Script for Docker Access - Version 2
# This script stops PostgreSQL, configures it, then restarts it

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PostgreSQL Docker Access Configuration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Requires Administrator privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script requires Administrator privileges" -ForegroundColor Red
    Write-Host "Please right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

$dataDir = "C:\Program Files\PostgreSQL\17\data"

Write-Host "Using PostgreSQL data directory: $dataDir" -ForegroundColor Green
Write-Host ""

# Step 1: Stop PostgreSQL service
Write-Host "Step 1: Stopping PostgreSQL service..." -ForegroundColor Yellow

$service = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1

if ($service) {
    Write-Host "Found service: $($service.Name)" -ForegroundColor Gray
    try {
        Stop-Service $service.Name -Force
        Start-Sleep -Seconds 2
        Write-Host "PostgreSQL service stopped" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to stop service: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "WARNING: Could not find PostgreSQL service" -ForegroundColor Yellow
}
Write-Host ""

# Step 2: Modify pg_hba.conf
Write-Host "Step 2: Configuring pg_hba.conf..." -ForegroundColor Yellow

$pgHbaConf = "$dataDir\pg_hba.conf"

try {
    $hbaContent = Get-Content $pgHbaConf

    # Check if our rules already exist
    $hasDockerRule = $hbaContent | Where-Object { $_ -match "172\.20\.0\.0/16" }

    if (-not $hasDockerRule) {
        # Add our rules
        $hbaContent += ""
        $hbaContent += "# Added by fix_postgres_for_docker.ps1 on $(Get-Date)"
        $hbaContent += "# Allow Docker containers to connect"
        $hbaContent += "host    all             all             172.20.0.0/16           md5"
        $hbaContent += "host    all             all             172.24.0.0/16           md5"
        $hbaContent += "# Allow local network connections"
        $hbaContent += "host    all             all             192.168.0.0/16          md5"

        $hbaContent | Set-Content $pgHbaConf -Encoding UTF8
        Write-Host "  - Added Docker network rules (172.20.0.0/16, 172.24.0.0/16)" -ForegroundColor Gray
        Write-Host "  - Added local network rules (192.168.0.0/16)" -ForegroundColor Gray
        Write-Host "pg_hba.conf updated successfully" -ForegroundColor Green
    } else {
        Write-Host "Rules already exist in pg_hba.conf" -ForegroundColor Green
    }
} catch {
    Write-Host "ERROR: Failed to update pg_hba.conf: $_" -ForegroundColor Red
    Write-Host "Restarting PostgreSQL service..." -ForegroundColor Yellow
    Start-Service $service.Name
    exit 1
}
Write-Host ""

# Step 3: Start PostgreSQL service
Write-Host "Step 3: Starting PostgreSQL service..." -ForegroundColor Yellow

if ($service) {
    try {
        Start-Service $service.Name
        Start-Sleep -Seconds 3

        $status = (Get-Service $service.Name).Status
        if ($status -eq "Running") {
            Write-Host "PostgreSQL service started successfully" -ForegroundColor Green
        } else {
            Write-Host "WARNING: PostgreSQL service status: $status" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "ERROR: Failed to start service: $_" -ForegroundColor Red
        exit 1
    }
}
Write-Host ""

# Step 4: Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Configuration Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "What was changed:" -ForegroundColor Yellow
Write-Host "  1. postgresql.conf: listen_addresses = '*' (already done)" -ForegroundColor White
Write-Host "  2. pg_hba.conf: Added Docker and local network access" -ForegroundColor White
Write-Host "  3. PostgreSQL service restarted" -ForegroundColor White
Write-Host ""
Write-Host "Now try connecting from Superset:" -ForegroundColor Yellow
Write-Host ""
Write-Host "Option 1 - Docker Gateway (RECOMMENDED):" -ForegroundColor Cyan
Write-Host "  Host: 172.24.0.1" -ForegroundColor White
Write-Host "  Port: 5432" -ForegroundColor White
Write-Host "  Database: tauseef" -ForegroundColor White
Write-Host "  Username: migration_user" -ForegroundColor White
Write-Host "  Password: StrongPassword123" -ForegroundColor White
Write-Host ""
Write-Host "Option 2 - Windows IP:" -ForegroundColor Cyan
Write-Host "  Host: 192.168.5.105" -ForegroundColor White
Write-Host "  Port: 5432" -ForegroundColor White
Write-Host ""
Write-Host "Option 3 - SQLAlchemy URI (Advanced tab):" -ForegroundColor Cyan
Write-Host "  postgresql://migration_user:StrongPassword123@172.24.0.1:5432/tauseef?options=-c search_path=analytics" -ForegroundColor White
Write-Host ""
Write-Host "If connection still fails, check Windows Firewall:" -ForegroundColor Yellow
Write-Host "  Allow port 5432 for PostgreSQL" -ForegroundColor White
Write-Host ""
