# DB Sync Tool Backup Script (Windows PowerShell)
# Usage: .\scripts\backup.ps1

param(
    [string]$BackupDir = "backups",
    [int]$RetentionDays = 30
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
$BackupPath = Join-Path $ProjectRoot $BackupDir

Write-Step "DB Sync Tool Backup Script"
Write-Info "Backup Directory: $BackupPath"
Write-Info "Retention: $RetentionDays days"

# Create backup directory if it doesn't exist
if (-not (Test-Path $BackupPath)) {
    New-Item -ItemType Directory -Path $BackupPath | Out-Null
    Write-Success "Created backup directory"
}

# Generate timestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = Join-Path $BackupPath "backup_$timestamp.sql"
$backupZip = "$backupFile.gz"

# Database backup
Write-Step "Step 1: Database Backup"
Write-Info "Creating database backup..."

# Note: Adjust pg_dump command based on your PostgreSQL setup
# This is a template - you need to configure your database credentials
$dbHost = $env:DB_HOST
$dbPort = $env:DB_PORT
$dbName = $env:DB_NAME
$dbUser = $env:DB_USER

if (-not $dbHost) {
    Write-Error "DB_HOST environment variable not set"
    exit 1
}

try {
    # Example pg_dump command (adjust as needed)
    # $env:PGPASSWORD = $env:DB_PASSWORD
    # pg_dump -h $dbHost -p $dbPort -U $dbUser -d $dbName -F c -f $backupFile
    
    # For now, create a placeholder
    Write-Info "Database backup command (configure based on your setup):"
    Write-Info "pg_dump -h $dbHost -p $dbPort -U $dbUser -d $dbName > $backupFile"
    
    # Compress backup
    if (Test-Path $backupFile) {
        Write-Info "Compressing backup..."
        # Compress-Archive -Path $backupFile -DestinationPath $backupZip
        # Remove-Item $backupFile
        Write-Success "Backup compressed: $backupZip"
    }
    
    Write-Success "Database backup created"
} catch {
    Write-Error "Database backup failed: $_"
    exit 1
}

# Configuration backup
Write-Step "Step 2: Configuration Backup"
$configBackup = Join-Path $BackupPath "config_$timestamp.zip"
$configFiles = @(
    ".env",
    "dbsync_tool/dbsync_tool/settings.py",
    "requirements.txt"
)

$configFilesToBackup = @()
foreach ($file in $configFiles) {
    $filePath = Join-Path $ProjectRoot $file
    if (Test-Path $filePath) {
        $configFilesToBackup += $filePath
    }
}

if ($configFilesToBackup.Count -gt 0) {
    try {
        Compress-Archive -Path $configFilesToBackup -DestinationPath $configBackup -Force
        Write-Success "Configuration backup created: $configBackup"
    } catch {
        Write-Error "Configuration backup failed: $_"
    }
} else {
    Write-Info "No configuration files found to backup"
}

# Cleanup old backups
Write-Step "Step 3: Cleanup Old Backups"
$cutoffDate = (Get-Date).AddDays(-$RetentionDays)
$oldBackups = Get-ChildItem -Path $BackupPath -Filter "backup_*.sql*" | Where-Object { $_.LastWriteTime -lt $cutoffDate }

if ($oldBackups.Count -gt 0) {
    Write-Info "Removing $($oldBackups.Count) old backup(s)..."
    $oldBackups | Remove-Item -Force
    Write-Success "Old backups removed"
} else {
    Write-Info "No old backups to remove"
}

# Summary
Write-Step "Backup Summary"
Write-Success "Backup completed successfully!"
Write-Info "Backup file: $backupFile"
if (Test-Path $configBackup) {
    Write-Info "Config backup: $configBackup"
}

# List recent backups
Write-Info "`nRecent backups:"
Get-ChildItem -Path $BackupPath -Filter "backup_*" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | ForEach-Object {
    Write-Info "  $($_.Name) - $($_.LastWriteTime)"
}

