import pyodbc
import time

drivers = [
    'ODBC Driver 17 for SQL Server',
    'ODBC Driver 13 for SQL Server',
    'SQL Server Native Client 11.0',
    'SQL Server'
]

host = '4.224.86.200'
port = '33890'
user = 'ssh110346'
pw = 'x0Fs039b'
db = 'master'

print(f"Testing connection to {host},{port}...")

for driver in pyodbc.drivers():
    if 'SQL Server' in driver:
        print(f"Checking driver: {driver}")
        conn_str = f"DRIVER={{{driver}}};SERVER={host},{port};DATABASE={db};UID={user};PWD={pw};TrustServerCertificate=yes;Login Timeout=10;"
        print(f"Conn string: {conn_str.replace(pw, '****')}")
        try:
            start = time.time()
            conn = pyodbc.connect(conn_str, timeout=10)
            print(f"SUCCESS with {driver} in {time.time() - start:.2f}s")
            conn.close()
            break
        except Exception as e:
            print(f"FAILED with {driver}: {str(e)}")
            print("-" * 20)
