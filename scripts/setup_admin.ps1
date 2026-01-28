# Setup admin user for DB Sync Tool
# Usage: .\scripts\setup_admin.ps1 -Password 'yourpassword'
# Or: $env:ADMIN_PASSWORD='yourpassword'; .\scripts\setup_admin.ps1

param(
    [Parameter(Mandatory=$false)]
    [string]$Password
)

$env:ADMIN_PASSWORD = if ($Password) { $Password } else { $env:ADMIN_PASSWORD }

if (-not $env:ADMIN_PASSWORD) {
    Write-Host "Error: ADMIN_PASSWORD environment variable not set" -ForegroundColor Red
    Write-Host "Usage: .\scripts\setup_admin.ps1 -Password 'yourpassword'" -ForegroundColor Yellow
    Write-Host "Or: `$env:ADMIN_PASSWORD='yourpassword'; .\scripts\setup_admin.ps1" -ForegroundColor Yellow
    exit 1
}

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ProjectDir = Join-Path $ProjectRoot "dbsync_tool"

Set-Location $ProjectDir

Write-Host "Setting up admin user..." -ForegroundColor Green
python manage.py create_admin_user --password $env:ADMIN_PASSWORD

Write-Host "Admin user setup complete!" -ForegroundColor Green

