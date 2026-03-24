import pyodbc
import time

host = '4.224.86.200'
port = '33890'
user = 'ssh110346'
pw = 'x0Fs039b'
db = 'master'

# Driver name found on the system
driver = 'ODBC Driver 17 for SQL Server'

test_configs = [
    {"Encrypt": "yes", "TrustServerCertificate": "yes"},
    {"Encrypt": "no", "TrustServerCertificate": "yes"},
    {"Protocol": "tcp"},
    {"MultiSubnetFailover": "No"},
]

print(f"Testing different configurations for {driver} to {host},{port}...")

for config in test_configs:
    kv_pairs = ";".join([f"{k}={v}" for k, v in config.items()])
    conn_str = f"DRIVER={{{driver}}};SERVER={host},{port};DATABASE={db};UID={user};PWD={pw};{kv_pairs};Login Timeout=10;"
    
    print(f"Testing Config: {kv_pairs}")
    try:
        start = time.time()
        conn = pyodbc.connect(conn_str, timeout=10)
        print(f"  SUCCESS in {time.time() - start:.2f}s")
        conn.close()
        print("  !!! THIS CONFIG WORKS !!!")
        break
    except Exception as e:
        print(f"  FAILED: {str(e).split(';')[0]}") # Show first part of error
        print("-" * 10)

# Also try without the comma (using colon or just host)
print("Testing with different SERVER formats...")
formats = [f"{host},{port}", f"tcp:{host},{port}"]
for fmt in formats:
    conn_str = f"DRIVER={{{driver}}};SERVER={fmt};DATABASE={db};UID={user};PWD={pw};TrustServerCertificate=yes;Login Timeout=10;"
    print(f"Testing SERVER={fmt}")
    try:
        start = time.time()
        conn = pyodbc.connect(conn_str, timeout=10)
        print(f"  SUCCESS in {time.time() - start:.2f}s")
        conn.close()
        break
    except Exception as e:
        print(f"  FAILED: {str(e).split(';')[0]}")
