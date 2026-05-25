# Add Windows Firewall rule for PostgreSQL
# Run as Administrator

Write-Host "Adding Windows Firewall rule for PostgreSQL..." -ForegroundColor Yellow

try {
    # Remove old rule if exists
    Remove-NetFirewallRule -DisplayName "PostgreSQL Port 5432" -ErrorAction SilentlyContinue

    # Add new rule
    New-NetFirewallRule -DisplayName "PostgreSQL Port 5432" `
                        -Direction Inbound `
                        -LocalPort 5432 `
                        -Protocol TCP `
                        -Action Allow `
                        -Profile Any

    Write-Host "Firewall rule added successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "PostgreSQL port 5432 is now open for incoming connections" -ForegroundColor Green
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
