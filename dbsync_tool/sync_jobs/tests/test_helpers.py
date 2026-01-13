"""
Helper utilities for integration testing
"""
from typing import List, Any
from datetime import datetime, timedelta
from connections.connectors.factory import get_connector
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)

def create_test_connections(user, source_type, target_type, source_config, target_config):
    """
    Create test database connections
    
    Args:
        user: User instance
        source_type: Source database type ('postgres', 'mysql', 'sqlserver')
        target_type: Target database type
        source_config: Source database configuration dict
        target_config: Target database configuration dict
    
    Returns:
        Tuple of (source_conn, target_conn) DatabaseConnection instances
    """
    source_conn = DatabaseConnection.objects.create(
        name=f'Test Source {source_type}',
        db_type=source_type,
        host=source_config['host'],
        port=source_config['port'],
        username=source_config['username'],
        password=source_config['password'],
        database_name=source_config['database'],
        created_by=user
    )
    
    target_conn = DatabaseConnection.objects.create(
        name=f'Test Target {target_type}',
        db_type=target_type,
        host=target_config['host'],
        port=target_config['port'],
        username=target_config['username'],
        password=target_config['password'],
        database_name=target_config['target_database'],
        created_by=user
    )
    
    return source_conn, target_conn

def setup_test_tables(connector, schema, tables_config):
    """
    Setup test tables in source database
    
    Args:
        connector: DBConnector instance
        schema: Schema/database name
        tables_config: Dict mapping table names to column definitions
    """
    from connections.connectors.base import ColumnInfo
    
    connector.connect()
    
    try:
        # Ensure schema exists
        connector.ensure_schema_exists(schema)
        
        for table_name, column_defs in tables_config.items():
            # Drop table if exists (for clean test)
            try:
                if connector.table_exists(schema, table_name):
                    # Truncate instead of drop to avoid issues
                    connector.truncate_table(schema, table_name)
            except Exception:
                pass  # Table might not exist or truncate might fail
            
            # Convert column definitions to ColumnInfo objects
            column_infos = []
            for col_def in column_defs:
                col_info = ColumnInfo(
                    name=col_def['name'],
                    data_type=col_def['type'],
                    is_nullable=not col_def.get('primary_key', False),
                    is_primary_key=col_def.get('primary_key', False),
                    max_length=None
                )
                column_infos.append(col_info)
            
            # Create table if it doesn't exist
            if not connector.table_exists(schema, table_name):
                connector.create_table(schema, table_name, column_infos)
            
            # Insert test data
            insert_test_data(connector, schema, table_name, column_defs)
    finally:
        connector.close()

def insert_test_data(connector, schema, table_name, columns):
    """
    Insert test data into a table
    
    Args:
        connector: DBConnector instance
        schema: Schema/database name
        table_name: Table name
        columns: Column definitions
    """
    import random
    from datetime import datetime, timedelta
    
    # Get column names
    column_names = [col['name'] for col in columns]
    
    # Generate test data based on table name
    rows = []
    if table_name == 'users':
        # Insert 100 test users
        for i in range(1, 101):
            username = f'testuser{i}'
            email = f'{username}@example.com'
            created_at = datetime.now() - timedelta(days=random.randint(1, 365))
            row = (i, username, email, created_at)
            rows.append(row)
    
    elif table_name == 'products':
        # Insert 50 test products
        for i in range(1, 51):
            name = f'Product {i}'
            price = round(random.uniform(10.0, 1000.0), 2)
            description = f'Description for {name}'
            row = (i, name, price, description)
            rows.append(row)
    
    # Bulk insert using connector's bulk_insert method
    if rows:
        connector.bulk_insert(schema, table_name, column_names, rows)

def create_test_job(user, source_conn, target_conn, tables):
    """
    Create a test sync job
    
    Args:
        user: User instance
        source_conn: Source DatabaseConnection
        target_conn: Target DatabaseConnection
        tables: List of (schema, table_name) tuples
    
    Returns:
        SyncJob instance
    """
    job = SyncJob.objects.create(
        name=f'Test Job {source_conn.db_type} -> {target_conn.db_type}',
        source_connection=source_conn,
        target_connection=target_conn,
        sync_type='full',
        status='pending',
        created_by=user
    )
    
    for schema, table_name in tables:
        SyncJobTable.objects.create(
            job=job,
            schema_name=schema,
            table_name=table_name,
            is_enabled=True
        )
    
    return job

def verify_sync_results(source_connector, target_connector, schema, table_name):
    """
    Verify that data was synced correctly
    
    Args:
        source_connector: Source DBConnector instance
        target_connector: Target DBConnector instance
        schema: Schema/database name
        table_name: Table name
    
    Raises:
        AssertionError: If verification fails
    """
    source_connector.connect()
    target_connector.connect()
    
    try:
        # Get row counts
        source_count = source_connector.get_query_row_count(
            f'SELECT COUNT(*) FROM {schema}.{table_name}'
        )
        target_count = target_connector.get_query_row_count(
            f'SELECT COUNT(*) FROM {schema}.{table_name}'
        )
        
        assert source_count == target_count, \
            f"Row count mismatch for {schema}.{table_name}: source={source_count}, target={target_count}"
        
        # Verify data integrity (sample first 10 rows)
        # Use fetch_batch to get sample rows
        source_rows = source_connector.fetch_batch(
            f'SELECT * FROM {schema}.{table_name} ORDER BY id',
            batch_size=10,
            offset=0
        )
        target_rows = target_connector.fetch_batch(
            f'SELECT * FROM {schema}.{table_name} ORDER BY id',
            batch_size=10,
            offset=0
        )
        
        assert len(source_rows) == len(target_rows), \
            f"Row count mismatch in sample data for {schema}.{table_name}"
        
        # Compare row data (basic check - compare first column which should be id)
        for i, (source_row, target_row) in enumerate(zip(source_rows, target_rows)):
            # Compare first column (id)
            if len(source_row) > 0 and len(target_row) > 0:
                assert source_row[0] == target_row[0], \
                    f"ID mismatch at row {i} for {schema}.{table_name}: source={source_row[0]}, target={target_row[0]}"
    finally:
        source_connector.close()
        target_connector.close()

def create_test_data_with_timestamps(
    connector,
    schema: str,
    table: str,
    count: int,
    start_time: datetime,
    interval_minutes: int = 1
) -> List[dict]:
    """
    Create test data with timestamps for incremental sync testing
    
    Args:
        connector: Database connector
        schema: Schema name
        table: Table name
        count: Number of rows to create
        start_time: Starting timestamp
        interval_minutes: Minutes between each row
        
    Returns:
        List of created data dictionaries
    """
    data = []
    current_time = start_time
    for i in range(count):
        data.append({
            'id': i + 1,
            'name': f'Test Record {i + 1}',
            'updated_at': current_time,
            'created_at': current_time
        })
        current_time += timedelta(minutes=interval_minutes)
    return data

def simulate_incremental_updates(
    connector,
    schema: str,
    table: str,
    new_data: List[dict]
):
    """
    Simulate incremental updates by inserting new data
    
    Args:
        connector: Database connector
        schema: Schema name
        table: Table name
        new_data: New data to insert
    """
    connector.connect()
    try:
        # Get column names from first row
        if new_data:
            column_names = list(new_data[0].keys())
            rows = [tuple(row[col] for col in column_names) for row in new_data]
            connector.bulk_insert(schema, table, column_names, rows)
    finally:
        connector.close()

def verify_checkpoint_value(
    job: SyncJob,
    schema: str,
    table: str,
    expected_value: Any
) -> bool:
    """
    Verify checkpoint value matches expected value
    
    Args:
        job: SyncJob instance
        schema: Schema name
        table: Table name
        expected_value: Expected checkpoint value
        
    Returns:
        True if checkpoint matches expected value
    """
    from sync_engine.checkpoint_manager import CheckpointManager
    manager = CheckpointManager(job)
    checkpoint_value = manager.get_checkpoint_value(schema, table)
    return checkpoint_value == str(expected_value) if expected_value else checkpoint_value is None

