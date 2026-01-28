# SQL Server Connection Troubleshooting Guide

## Error Message
```
Connection failed: Unexpected error listing databases: Failed to connect to SQL Server: 
('08001', '[08001] [Microsoft][ODBC Driver 17 for SQL Server]TCP Provider: The wait operation timed out.\r\n (258) (SQLDriverConnect); 
[08001] [Microsoft][ODBC Driver 17 for SQL Server]Login timeout expired (0); 
[08001] [Microsoft][ODBC Driver 17 for SQL Server]A network-related or instance-specific error has occurred while establishing a connection to SQL Server. 
Server is not found or not accessible. Check if instance name is correct and if SQL Server is configured to allow remote connections. 
For more information see SQL Server Books Online. (258)')
```

## Problem Analysis

This error indicates three main issues:
1. **TCP Provider Timeout** - Connection attempt timed out
2. **Login Timeout Expired** - Authentication timeout
3. **Server Not Found/Accessible** - Network or configuration issue

---

## Solution Steps

### 1. **Verify SQL Server is Running**

**On the SQL Server machine:**
```powershell
# Check if SQL Server service is running
Get-Service -Name "MSSQLSERVER" -ErrorAction SilentlyContinue
Get-Service -Name "MSSQL*" | Select-Object Name, Status

# Or check via SQL Server Configuration Manager
# Start -> SQL Server Configuration Manager -> SQL Server Services
```

**Check if SQL Server is listening:**
```powershell
# Check if SQL Server is listening on default port 1433
netstat -an | findstr 1433

# Should show: TCP    0.0.0.0:1433    LISTENING
```

---

### 2. **Verify Network Connectivity**

**From your application server, test connection:**

```powershell
# Test TCP connection to SQL Server
Test-NetConnection -ComputerName <SQL_SERVER_HOST> -Port 1433

# Or using telnet (if available)
telnet <SQL_SERVER_HOST> 1433

# Or using PowerShell
(New-Object System.Net.Sockets.TcpClient).ConnectAsync("<SQL_SERVER_HOST>", 1433)
```

**If connection fails:**
- Firewall is blocking port 1433
- SQL Server is not configured to accept remote connections
- Network routing issue

---

### 3. **Check SQL Server Configuration**

#### A. Enable TCP/IP Protocol

**On SQL Server machine:**

1. Open **SQL Server Configuration Manager**
2. Navigate to: **SQL Server Network Configuration** → **Protocols for MSSQLSERVER**
3. Right-click **TCP/IP** → **Enable**
4. Right-click **TCP/IP** → **Properties**
5. Go to **IP Addresses** tab
6. Scroll to **IPAll** section
7. Set **TCP Port** to `1433` (or your custom port)
8. Clear **TCP Dynamic Ports** (set to blank)
9. Click **OK**
10. **Restart SQL Server service**

#### B. Enable SQL Server Authentication (if using SQL Auth)

1. Open **SQL Server Management Studio (SSMS)**
2. Connect to SQL Server
3. Right-click server → **Properties**
4. Go to **Security** tab
5. Select **SQL Server and Windows Authentication mode**
6. Click **OK**
7. **Restart SQL Server service**

---

### 4. **Configure Windows Firewall**

**On SQL Server machine:**

#### Option A: Using PowerShell (Run as Administrator)
```powershell
# Allow SQL Server port 1433
New-NetFirewallRule -DisplayName "SQL Server" -Direction Inbound -Protocol TCP -LocalPort 1433 -Action Allow

# Or if SQL Server Browser is used
New-NetFirewallRule -DisplayName "SQL Server Browser" -Direction Inbound -Protocol UDP -LocalPort 1434 -Action Allow
```

#### Option B: Using Windows Firewall GUI
1. Open **Windows Defender Firewall with Advanced Security**
2. Click **Inbound Rules** → **New Rule**
3. Select **Port** → **Next**
4. Select **TCP** → Enter port `1433` → **Next**
5. Select **Allow the connection** → **Next**
6. Select all profiles (Domain, Private, Public) → **Next**
7. Name: "SQL Server Port 1433" → **Finish**

---

### 5. **Check SQL Server Instance Name**

**Common Connection String Formats:**

```python
# Default instance
host: "localhost" or "server-name"
port: 1433 (optional for default)
database_name: "your_database"

# Named instance
host: "server-name\INSTANCENAME"
port: (usually dynamic, but can be configured)
database_name: "your_database"

# With specific port
host: "server-name,1433"
port: 1433
database_name: "your_database"
```

**To find instance name:**
```sql
SELECT @@SERVERNAME, @@SERVICENAME;
-- Or
SELECT SERVERPROPERTY('ServerName') AS ServerName,
       SERVERPROPERTY('InstanceName') AS InstanceName;
```

---

### 6. **Update Connection Configuration in Application**

**In DB Sync Tool:**

1. Go to **Connections** page
2. Edit your SQL Server connection
3. Verify connection details:

**Connection Settings:**
- **Host**: 
  - Default instance: `server-name` or `IP_ADDRESS`
  - Named instance: `server-name\INSTANCENAME`
  - With port: `server-name,1433` or `IP_ADDRESS,1433`
  
- **Port**: 
  - Default: `1433`
  - Custom: Your configured port
  - Named instance: Usually blank (uses dynamic port)

- **Username**: SQL Server login name
- **Password**: SQL Server password
- **Database Name**: Target database name

**Example Configurations:**

```
Default Instance:
Host: 192.168.1.100
Port: 1433
Username: sa
Password: YourPassword
Database: MyDatabase

Named Instance (MSSQLSERVER\SQL2019):
Host: 192.168.1.100\SQL2019
Port: (leave blank or use specific port)
Username: sa
Password: YourPassword
Database: MyDatabase

With Custom Port:
Host: 192.168.1.100
Port: 14330
Username: sa
Password: YourPassword
Database: MyDatabase
```

---

### 7. **Test Connection Directly**

**Using Python (test from your machine):**

```python
import pyodbc

# Test connection
try:
    # Default instance
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"TrustServerCertificate=yes;"
        f"Connection Timeout=30;"
    )
    
    conn = pyodbc.connect(conn_str, timeout=30)
    print("✓ Connection successful!")
    conn.close()
except Exception as e:
    print(f"✗ Connection failed: {e}")
```

**Using SQL Server Management Studio:**
- Try connecting with the same credentials
- If SSMS works, issue is in application configuration
- If SSMS fails, issue is with SQL Server or network

---

### 8. **Common Connection String Patterns**

**For Named Instances:**
```
Host: SERVER\INSTANCENAME
Port: (blank or specific port)
```

**For Default Instance:**
```
Host: SERVER or IP_ADDRESS
Port: 1433
```

**For Dynamic Ports (Named Instances):**
- SQL Server Browser must be running
- UDP port 1434 must be open
- Or specify explicit port in configuration

---

### 9. **Enable SQL Server Browser (For Named Instances)**

If using named instances without explicit ports:

1. Open **SQL Server Configuration Manager**
2. Navigate to **SQL Server Services**
3. Find **SQL Server Browser**
4. Right-click → **Properties** → **Service** tab
5. Set **Start Mode** to **Automatic**
6. Right-click → **Start** (if not running)
7. **Ensure UDP port 1434 is open in firewall**

---

### 10. **Check SQL Server Error Logs**

**Location**: `C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Log\ERRORLOG`

Or via SQL:
```sql
EXEC sp_readerrorlog 0, 1, 'error'
```

Look for:
- Connection attempts
- Authentication failures
- Network errors

---

### 11. **Increase Connection Timeout (Temporary Fix)**

If connection works but times out too quickly, you can increase timeout in the connection configuration.

**In SQL Server connector code**, timeout is typically set during connection. Default is usually 30 seconds.

---

### 12. **Verify ODBC Driver**

**Check if ODBC Driver 17 is installed:**

```powershell
# List installed ODBC drivers
Get-OdbcDriver | Where-Object {$_.Name -like "*SQL Server*"}
```

**If not installed:**
- Download and install: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
- Or use ODBC Driver 13, 18, or 19 (adjust connection string accordingly)

---

## Quick Diagnostic Checklist

- [ ] SQL Server service is running
- [ ] SQL Server is listening on port 1433 (or configured port)
- [ ] TCP/IP protocol is enabled in SQL Server Configuration Manager
- [ ] Windows Firewall allows port 1433 (and 1434 if using Browser)
- [ ] SQL Server allows remote connections (Security settings)
- [ ] SQL Server Authentication is enabled (if using SQL auth)
- [ ] Network connectivity test succeeds (Test-NetConnection)
- [ ] Connection credentials are correct
- [ ] Instance name is correct (for named instances)
- [ ] SQL Server Browser is running (for named instances)
- [ ] ODBC Driver 17 for SQL Server is installed

---

## Quick Fix Commands (Run as Administrator)

```powershell
# 1. Enable TCP/IP (requires SQL Server Configuration Manager)
# Manually via GUI

# 2. Open Firewall Port
New-NetFirewallRule -DisplayName "SQL Server" -Direction Inbound -Protocol TCP -LocalPort 1433 -Action Allow

# 3. Restart SQL Server Service
Restart-Service MSSQLSERVER

# 4. Test Connection
Test-NetConnection -ComputerName localhost -Port 1433
```

---

## Still Not Working?

### Additional Checks:

1. **Check if SQL Server is listening on correct IP:**
   ```sql
   -- In SSMS, run:
   EXEC xp_readerrorlog 0, 1, "listening";
   ```

2. **Verify SQL Server is configured to accept connections:**
   ```sql
   -- Check remote access
   EXEC sp_configure 'remote access', 1;
   RECONFIGURE;
   ```

3. **Test with SQL Server authentication directly:**
   ```sql
   -- Create a test login
   CREATE LOGIN testuser WITH PASSWORD = 'TestPassword123!';
   GRANT CONNECT SQL TO testuser;
   ```

4. **Check for IP restrictions in SQL Server:**
   - SQL Server Configuration Manager → TCP/IP Properties → IP Addresses tab
   - Ensure all IP addresses are enabled (Active = Yes, Enabled = Yes)

---

## Connection String Examples

**Default Instance:**
```
DRIVER={ODBC Driver 17 for SQL Server};
SERVER=192.168.1.100,1433;
DATABASE=MyDB;
UID=sa;
PWD=Password123;
TrustServerCertificate=yes;
Connection Timeout=60;
```

**Named Instance:**
```
DRIVER={ODBC Driver 17 for SQL Server};
SERVER=192.168.1.100\SQL2019;
DATABASE=MyDB;
UID=sa;
PWD=Password123;
TrustServerCertificate=yes;
Connection Timeout=60;
```

**Windows Authentication (if supported):**
```
DRIVER={ODBC Driver 17 for SQL Server};
SERVER=192.168.1.100,1433;
DATABASE=MyDB;
Trusted_Connection=yes;
Connection Timeout=60;
```

---

## Contact Information

If the issue persists after trying all these steps:
1. Check SQL Server error logs
2. Verify network infrastructure (routers, switches)
3. Test from a different machine on the same network
4. Check with your network administrator for firewall rules
