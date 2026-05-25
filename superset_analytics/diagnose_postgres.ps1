# PostgreSQL Connection Diagnostics Script
# Checks all aspects of PostgreSQL connectivity for Docker/Superset

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PostgreSQL Connection Diagnostics" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Test 1: PostgreSQL Service Status
Write-Host "[Test 1] Checking PostgreSQL Service..." -ForegroundColor Yellow
$service = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1

if ($service) {
    $status = $service.Status
    if ($status -eq "Running") {
        Write-Host "  Service: $($service.Name)" -ForegroundColor Green
        Write-Host "  Status: $status" -ForegroundColor Green
        Write-Host "  [PASS]" -ForegroundColor Green
    } else {
        Write-Host "  Service: $($service.Name)" -ForegroundColor Red
        Write-Host "  Status: $status" -ForegroundColor Red
        Write-Host "  [FAIL] PostgreSQL is not running!" -ForegroundColor Red
        Write-Host "  Action: Run 'Start-Service $($service.Name)'" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [FAIL] PostgreSQL service not found!" -ForegroundColor Red
}
Write-Host ""

# Test 2: Network Listening Status
Write-Host "[Test 2] Checking Network Listening..." -ForegroundColor Yellow
$listening = netstat -an | Select-String ":5432"

if ($listening) {
    Write-Host "  PostgreSQL is listening on:" -ForegroundColor Green
    $listening | ForEach-Object { Write-Host "    $_" -ForegroundColor White }

    $listeningAll = $listening | Select-String "0.0.0.0:5432"
    if ($listeningAll) {
        Write-Host "  [PASS] Listening on all interfaces (0.0.0.0)" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] Only listening on specific interfaces" -ForegroundColor Yellow
        Write-Host "  Check postgresql.conf: listen_addresses = '*'" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [FAIL] PostgreSQL is NOT listening on port 5432!" -ForegroundColor Red
    Write-Host "  Action: Check if PostgreSQL service is running" -ForegroundColor Yellow
}
Write-Host ""

# Test 3: Localhost Connection
Write-Host "[Test 3] Testing Localhost Connection..." -ForegroundColor Yellow
$env:PGPASSWORD = "StrongPassword123"
$localhostTest = psql -U migration_user -h localhost -d tauseef -c "SELECT 'Connection OK' as status;" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  [PASS] Can connect via localhost" -ForegroundColor Green
    Write-Host "  $localhostTest" -ForegroundColor Gray
} else {
    Write-Host "  [FAIL] Cannot connect via localhost" -ForegroundColor Red
    Write-Host "  Error: $localhostTest" -ForegroundColor Red
}
$env:PGPASSWORD = $null
Write-Host ""

# Test 4: Network Interfaces
Write-Host "[Test 4] Checking Network Interfaces..." -ForegroundColor Yellow
$interfaces = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne "127.0.0.1" }

Write-Host "  Available IP addresses:" -ForegroundColor Green
foreach ($ip in $interfaces) {
    Write-Host "    $($ip.IPAddress) ($($ip.InterfaceAlias))" -ForegroundColor White
}
Write-Host ""

# Test 5: Firewall Rules
Write-Host "[Test 5] Checking Windows Firewall..." -ForegroundColor Yellow
$firewallRule = Get-NetFirewallRule -DisplayName "PostgreSQL*" -ErrorAction SilentlyContinue

if ($firewallRule) {
    Write-Host "  Found firewall rule(s):" -ForegroundColor Green
    $firewallRule | ForEach-Object {
        $portFilter = $_ | Get-NetFirewallPortFilter
        Write-Host "    $($_.DisplayName) - $($_.Direction) - $($_.Action) - Port: $($portFilter.LocalPort)" -ForegroundColor White
    }
    Write-Host "  [PASS] Firewall rules exist" -ForegroundColor Green
} else {
    Write-Host "  [WARNING] No PostgreSQL firewall rules found" -ForegroundColor Yellow
    Write-Host "  Action: Run .\fix_firewall.ps1 to add firewall rule" -ForegroundColor Yellow
}
Write-Host ""

# Test 6: Docker Network
Write-Host "[Test 6] Checking Docker Network..." -ForegroundColor Yellow
$dockerNetwork = docker network inspect superset_analytics_superset_network 2>&1

if ($LASTEXITCODE -eq 0) {
    $networkJson = $dockerNetwork | ConvertFrom-Json
    $gateway = $networkJson.IPAM.Config[0].Gateway
    $subnet = $networkJson.IPAM.Config[0].Subnet

    Write-Host "  Docker Network: superset_analytics_superset_network" -ForegroundColor Green
    Write-Host "  Gateway: $gateway" -ForegroundColor White
    Write-Host "  Subnet: $subnet" -ForegroundColor White
    Write-Host "  [PASS] Docker network exists" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Docker network not found" -ForegroundColor Red
}
Write-Host ""

# Test 7: PostgreSQL Configuration Files
Write-Host "[Test 7] Checking PostgreSQL Configuration..." -ForegroundColor Yellow
$dataDir = "C:\Program Files\PostgreSQL\17\data"

if (Test-Path "$dataDir\postgresql.conf") {
    $postgresqlConf = Get-Content "$dataDir\postgresql.conf"
    $listenLine = $postgresqlConf | Where-Object { $_ -match "^\s*listen_addresses\s*=" } | Select-Object -First 1

    if ($listenLine) {
        Write-Host "  postgresql.conf found" -ForegroundColor Green
        Write-Host "  $listenLine" -ForegroundColor White

        if ($listenLine -match "'\*'|`"\*`"") {
            Write-Host "  [PASS] Configured to listen on all interfaces" -ForegroundColor Green
        } else {
            Write-Host "  [WARNING] Not configured to listen on all interfaces" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  [WARNING] postgresql.conf not found at expected location" -ForegroundColor Yellow
}

if (Test-Path "$dataDir\pg_hba.conf") {
    $pgHbaConf = Get-Content "$dataDir\pg_hba.conf"
    $dockerRules = $pgHbaConf | Where-Object { $_ -match "172\." }

    if ($dockerRules) {
        Write-Host "  pg_hba.conf: Docker network rules found" -ForegroundColor Green
        $dockerRules | ForEach-Object { Write-Host "    $_" -ForegroundColor White }
        Write-Host "  [PASS] pg_hba.conf configured for Docker" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] No Docker network rules in pg_hba.conf" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [WARNING] pg_hba.conf not found at expected location" -ForegroundColor Yellow
}
Write-Host ""

# Test 8: Test Connection from Docker IPs
Write-Host "[Test 8] Testing Connection from Various IPs..." -ForegroundColor Yellow
$testIPs = @("192.168.5.105", "192.168.31.1", "192.168.80.1", "172.24.0.1")
$env:PGPASSWORD = "StrongPassword123"

foreach ($ip in $testIPs) {
    Write-Host "  Testing: $ip..." -ForegroundColor Gray
    $result = psql -U migration_user -h $ip -d tauseef -c "SELECT 1;" 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "    [PASS] $ip - Connection successful!" -ForegroundColor Green
    } else {
        Write-Host "    [FAIL] $ip - Connection failed" -ForegroundColor Red
    }
}
$env:PGPASSWORD = $null
Write-Host ""

# Summary and Recommendations
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Summary & Recommendations" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Based on the tests above, try these in Superset:" -ForegroundColor Yellow
Write-Host ""

Write-Host "If localhost connection PASSED:" -ForegroundColor Cyan
Write-Host "  Problem: Docker cannot reach Windows PostgreSQL" -ForegroundColor White
Write-Host "  Solutions:" -ForegroundColor White
Write-Host "    1. Add firewall rule: .\fix_firewall.ps1" -ForegroundColor Gray
Write-Host "    2. Try each IP address from Test 8 that PASSED" -ForegroundColor Gray
Write-Host "    3. Use: postgresql://migration_user:StrongPassword123@[IP]:5432/tauseef" -ForegroundColor Gray
Write-Host ""

Write-Host "If localhost connection FAILED:" -ForegroundColor Cyan
Write-Host "  Problem: PostgreSQL not accepting connections" -ForegroundColor White
Write-Host "  Solutions:" -ForegroundColor White
Write-Host "    1. Restart PostgreSQL: Restart-Service postgresql-x64-17" -ForegroundColor Gray
Write-Host "    2. Check postgresql.conf: listen_addresses = '*'" -ForegroundColor Gray
Write-Host "    3. Check pg_hba.conf for proper authentication rules" -ForegroundColor Gray
Write-Host ""

Write-Host "If Docker network test FAILED:" -ForegroundColor Cyan
Write-Host "  Problem: Docker containers not running" -ForegroundColor White
Write-Host "  Solution: cd superset_analytics && docker-compose up -d" -ForegroundColor Gray
Write-Host ""

Write-Host "Quick fix commands:" -ForegroundColor Yellow
Write-Host "  .\fix_firewall.ps1              # Add firewall rule" -ForegroundColor White
Write-Host "  Restart-Service postgresql-x64-17   # Restart PostgreSQL" -ForegroundColor White
Write-Host "  docker-compose up -d                 # Start Docker containers" -ForegroundColor White
Write-Host ""
