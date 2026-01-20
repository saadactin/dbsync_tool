"""
End-to-end flow testing script
Tests: Connection → Job Creation → Table Fetching → Migration (Full & Incremental)
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from connections.connectors.postgres import PostgresConnector
from connections.connectors.mysql import MySQLConnector
from metadata.services import load_schemas_lazy, load_tables_lazy
from sync_jobs.models import SyncJob, SyncJobTable
from sync_engine.executor import SyncExecutor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_postgres_connection():
    """Test PostgreSQL connection"""
    print("\n" + "="*60)
    print("TEST 1: PostgreSQL Connection")
    print("="*60)
    
    config = {
        'host': 'localhost',
        'port': 5432,
        'username': 'migration_user',
        'password': 'StrongPassword123',
        'database_name': 'Tor2'
    }
    
    try:
        connector = PostgresConnector(**config)
        connector.connect()
        print("[OK] PostgreSQL connection successful")
        
        # Test get_schemas
        schemas = connector.get_schemas()
        print(f"[OK] Found {len(schemas)} schemas: {schemas[:5]}")
        
        # Test get_tables for first schema
        if schemas:
            tables = connector.get_tables(schemas[0])
            print(f"[OK] Found {len(tables)} tables in schema '{schemas[0]}': {tables[:5]}")
        
        connector.close()
        return True, config
    except Exception as e:
        print(f"[ERROR] PostgreSQL connection failed: {str(e)}")
        return False, None

def test_mysql_connection():
    """Test MySQL connection"""
    print("\n" + "="*60)
    print("TEST 2: MySQL Connection")
    print("="*60)
    
    # First connect without database to list databases
    config = {
        'host': 'localhost',
        'port': 3306,
        'username': 'root',
        'password': 'root',
        'database_name': None  # Connect without database first
    }
    
    try:
        # Try to connect to MySQL server (without specifying database)
        from connections.connectors.mysql import MySQLConnector
        import pymysql
        
        # Connect to MySQL server directly
        connection = pymysql.connect(
            host='localhost',
            port=3306,
            user='root',
            password='root'
        )
        cursor = connection.cursor()
        cursor.execute("SHOW DATABASES")
        databases = [row[0] for row in cursor.fetchall()]
        cursor.close()
        connection.close()
        
        print(f"[OK] MySQL server connection successful")
        print(f"[OK] Found {len(databases)} databases: {databases}")
        
        # Use first non-system database
        system_dbs = {'information_schema', 'performance_schema', 'mysql', 'sys'}
        user_databases = [db for db in databases if db not in system_dbs]
        
        if not user_databases:
            print("[WARNING] No user databases found, creating test database")
            # Create a test database
            connection = pymysql.connect(
                host='localhost',
                port=3306,
                user='root',
                password='root'
            )
            cursor = connection.cursor()
            cursor.execute("CREATE DATABASE IF NOT EXISTS test_sync")
            cursor.close()
            connection.close()
            db_name = 'test_sync'
        else:
            db_name = user_databases[0]
        
        print(f"[INFO] Using database: {db_name}")
        
        # Now connect with database
        config['database_name'] = db_name
        connector = MySQLConnector(**config)
        connector.connect()
        print("[OK] MySQL connection to database successful")
        
        # Test get_schemas (databases in MySQL)
        schemas = connector.get_schemas()
        print(f"[OK] Found {len(schemas)} databases: {schemas[:5]}")
        
        # Test get_tables for selected database
        tables = connector.get_tables(db_name)
        print(f"[OK] Found {len(tables)} tables in database '{db_name}': {tables[:5]}")
        
        connector.close()
        return True, config
    except Exception as e:
        print(f"[ERROR] MySQL connection failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, None

def test_metadata_api():
    """Test metadata API endpoints"""
    print("\n" + "="*60)
    print("TEST 3: Metadata API Endpoints")
    print("="*60)
    
    # Get or create test user
    user, _ = User.objects.get_or_create(
        username='test_user',
        defaults={'email': 'test@example.com'}
    )
    
    # Test PostgreSQL connection
    pg_conn = DatabaseConnection.objects.filter(
        db_type='postgres',
        host='localhost',
        database_name='Tor2'
    ).first()
    
    if not pg_conn:
        print("[ERROR] PostgreSQL connection not found in database")
        print("  Please create connection in UI first")
        return False
    
    try:
        print(f"Testing metadata API for connection: {pg_conn.name} ({pg_conn.id})")
        
        # Test load_schemas_lazy
        print("\n  Testing load_schemas_lazy...")
        schemas = load_schemas_lazy(str(pg_conn.id), user, use_cache=False)
        print(f"  [OK] Loaded {len(schemas)} schemas: {[s['name'] for s in schemas[:5]]}")
        
        # Test load_tables_lazy
        if schemas:
            schema_name = schemas[0]['name']
            print(f"\n  Testing load_tables_lazy for schema '{schema_name}'...")
            tables = load_tables_lazy(str(pg_conn.id), schema_name, user, use_cache=False)
            print(f"  [OK] Loaded {len(tables)} tables: {[t['name'] for t in tables[:5]]}")
        
        return True
    except Exception as e:
        print(f"  [ERROR] Metadata API failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_create_connections():
    """Create or get database connections"""
    print("\n" + "="*60)
    print("TEST 4: Creating/Verifying Database Connections")
    print("="*60)
    
    user, _ = User.objects.get_or_create(
        username='test_user',
        defaults={'email': 'test@example.com'}
    )
    
    # Ensure user has a profile
    from accounts.models import UserProfile
    profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={'role': 'admin'}
    )
    
    from accounts.services.tenant_service import TenantService
    tenant = TenantService.get_user_tenant(user)
    
    # If no tenant, we can't create connections - use existing connections instead
    if tenant is None:
        print("[WARNING] User has no tenant. Will use existing connections.")
        # Try to get existing connections
        pg_conn = DatabaseConnection.objects.filter(
            db_type='postgres',
            host='localhost',
            database_name='Tor2'
        ).first()
        mysql_conn = DatabaseConnection.objects.filter(
            db_type='mysql',
            host='localhost'
        ).first()
        
        if pg_conn and mysql_conn:
            print(f"[INFO] Using existing PostgreSQL connection: {pg_conn.name}")
            print(f"[INFO] Using existing MySQL connection: {mysql_conn.name}")
            return pg_conn, mysql_conn, user
        else:
            print("[ERROR] No tenant and no existing connections found.")
            print("  Please create connections through the UI first.")
            return None, None, user
    
    # PostgreSQL connection
    pg_conn, created = DatabaseConnection.objects.get_or_create(
        name='Test PostgreSQL (Tor2)',
        defaults={
            'db_type': 'postgres',
            'host': 'localhost',
            'port': 5432,
            'username': 'migration_user',
            'password': 'StrongPassword123',
            'database_name': 'Tor2',
            'created_by': user,
            'tenant': tenant,
            'is_active': True
        }
    )
    if not created:
        # Update if exists
        pg_conn.password = 'StrongPassword123'
        pg_conn.host = 'localhost'
        pg_conn.port = 5432
        pg_conn.database_name = 'Tor2'
        pg_conn.username = 'migration_user'
        pg_conn.is_active = True
        pg_conn.save()
    
    print(f"{'Created' if created else 'Found'} PostgreSQL connection: {pg_conn.id}")
    
    # MySQL connection
    mysql_conn, created = DatabaseConnection.objects.get_or_create(
        name='Test MySQL (root)',
        defaults={
            'db_type': 'mysql',
            'host': 'localhost',
            'port': 3306,
            'username': 'root',
            'password': 'root',
            'database_name': 'test',
            'created_by': user,
            'tenant': tenant,
            'is_active': True
        }
    )
    if not created:
        mysql_conn.password = 'root'
        mysql_conn.is_active = True
        mysql_conn.save()
    
    print(f"{'Created' if created else 'Found'} MySQL connection: {mysql_conn.id}")
    
    return pg_conn, mysql_conn, user

def test_table_loading():
    """Test table loading for both connections"""
    print("\n" + "="*60)
    print("TEST 5: Table Loading via Metadata API")
    print("="*60)
    
    pg_conn, mysql_conn, user = test_create_connections()
    
    # Test PostgreSQL
    print("\n  Testing PostgreSQL connection...")
    try:
        schemas = load_schemas_lazy(str(pg_conn.id), user, use_cache=False)
        print(f"  [OK] PostgreSQL schemas: {len(schemas)}")
        if schemas:
            schema_name = schemas[0]['name']
            tables = load_tables_lazy(str(pg_conn.id), schema_name, user, use_cache=False)
            print(f"  [OK] PostgreSQL tables in '{schema_name}': {len(tables)}")
            if tables:
                print(f"    Sample tables: {[t['name'] for t in tables[:3]]}")
    except Exception as e:
        print(f"  [ERROR] PostgreSQL metadata failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test MySQL
    print("\n  Testing MySQL connection...")
    try:
        schemas = load_schemas_lazy(str(mysql_conn.id), user, use_cache=False)
        print(f"  [OK] MySQL databases: {len(schemas)}")
        if schemas:
            schema_name = schemas[0]['name']
            tables = load_tables_lazy(str(mysql_conn.id), schema_name, user, use_cache=False)
            print(f"  [OK] MySQL tables in '{schema_name}': {len(tables)}")
            if tables:
                print(f"    Sample tables: {[t['name'] for t in tables[:3]]}")
    except Exception as e:
        print(f"  [ERROR] MySQL metadata failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == '__main__':
    print("\n" + "="*60)
    print("END-TO-END FLOW TESTING")
    print("="*60)
    
    # Test 1: Direct connections
    pg_ok, pg_config = test_postgres_connection()
    mysql_ok, mysql_config = test_mysql_connection()
    
    if not pg_ok or not mysql_ok:
        print("\n[ERROR] Direct connection tests failed. Please fix database connections first.")
        sys.exit(1)
    
    # Test 2: Create connections in database
    pg_conn, mysql_conn, user = test_create_connections()
    
    # Test 3: Metadata API
    test_table_loading()
    
    # Test 4: Metadata API endpoint
    test_metadata_api()
    
    print("\n" + "="*60)
    print("BASIC TESTS COMPLETE")
    print("="*60)
    print("\nNext: Test job creation and sync execution...")
