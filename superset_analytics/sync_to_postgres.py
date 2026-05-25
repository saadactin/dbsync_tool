#!/usr/bin/env python3
"""
Data Sync Script: Django SQLite → Postgres Analytics Schema

Reads sync job data from Django's SQLite database and copies it to
Postgres analytics schema for Superset visualization.
"""
import os
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DJANGO_SQLITE_PATH = os.getenv('DJANGO_SQLITE_PATH', '../dbsync_tool/db.sqlite3')

# Use Analytics DB settings (your local Postgres with Django data)
POSTGRES_USER = os.getenv('ANALYTICS_DB_USER', 'migration_user')
POSTGRES_PASSWORD = os.getenv('ANALYTICS_DB_PASSWORD', 'StrongPassword123')
POSTGRES_DB = os.getenv('ANALYTICS_DB_NAME', 'tauseef')
POSTGRES_HOST = os.getenv('ANALYTICS_DB_HOST', 'localhost')
POSTGRES_PORT = os.getenv('ANALYTICS_DB_PORT', '5432')
ANALYTICS_SCHEMA = 'analytics'

# Tables to sync from SQLite (Django table names)
TABLES_TO_SYNC = [
    'sync_jobs',
    'sync_executions',
    'sync_execution_logs',
    'database_connections',
    'api_connections',
    'sync_schedules',
    'sync_checkpoints',
    'connection_test_logs',
    'connection_health_check_log',
    'notification_logs',
    'sync_verification_reports',
]


def get_sqlite_path():
    """Get absolute path to Django SQLite database."""
    base_dir = Path(__file__).parent
    sqlite_path = base_dir / DJANGO_SQLITE_PATH
    if not sqlite_path.exists():
        print(f"[ERROR] ERROR: Django SQLite database not found at: {sqlite_path}")
        print(f"   Please check DJANGO_SQLITE_PATH in .env")
        sys.exit(1)
    return sqlite_path


def create_analytics_schema(pg_engine):
    """Create analytics schema if it doesn't exist."""
    with pg_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {ANALYTICS_SCHEMA}"))
        conn.commit()
    print(f"[OK] Analytics schema '{ANALYTICS_SCHEMA}' ready")


def sync_table(sqlite_engine, pg_engine, table_name):
    """
    Sync a single table from SQLite to Postgres analytics schema.

    Args:
        sqlite_engine: SQLAlchemy engine for SQLite
        pg_engine: SQLAlchemy engine for Postgres
        table_name: Name of table to sync
    """
    try:
        # Check if table exists in SQLite
        inspector = inspect(sqlite_engine)
        if table_name not in inspector.get_table_names():
            print(f"[WARNING]  Table '{table_name}' not found in SQLite - skipping")
            return

        # Read data from SQLite
        df = pd.read_sql_table(table_name, sqlite_engine)
        row_count = len(df)

        if row_count == 0:
            print(f"[WARNING]  Table '{table_name}': 0 rows - skipping")
            return

        # Write to Postgres analytics schema (replace existing data)
        target_table = f"{ANALYTICS_SCHEMA}.{table_name}"
        df.to_sql(
            table_name,
            pg_engine,
            schema=ANALYTICS_SCHEMA,
            if_exists='replace',
            index=False,
            method='multi',
            chunksize=1000
        )

        print(f"[OK] Synced '{table_name}': {row_count} rows")

    except Exception as e:
        print(f"[ERROR] Failed to sync '{table_name}': {str(e)}")
        raise


def main():
    """Main sync process."""
    print("=" * 60)
    print("DB Sync Tool -> Postgres Analytics Data Pipeline")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Get SQLite database path
    sqlite_path = get_sqlite_path()
    print(f"Django SQLite: {sqlite_path}")

    # Create database connections
    try:
        # SQLite connection
        sqlite_engine = create_engine(f'sqlite:///{sqlite_path}')
        print(f"[OK] Connected to SQLite: {sqlite_path.name}")

        # Postgres connection
        postgres_url = (
            f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@'
            f'{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'
        )
        pg_engine = create_engine(postgres_url)

        # Test Postgres connection
        with pg_engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print(f"[OK] Connected to Postgres: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")

    except Exception as e:
        print(f"[ERROR] Database connection failed: {str(e)}")
        print()
        print("Make sure Docker containers are running:")
        print("  cd superset_analytics && docker-compose up -d")
        sys.exit(1)

    print()
    print(f" Syncing {len(TABLES_TO_SYNC)} tables to '{ANALYTICS_SCHEMA}' schema...")
    print("-" * 60)

    # Create analytics schema
    create_analytics_schema(pg_engine)
    print()

    # Sync each table
    total_synced = 0
    failed_tables = []

    for table_name in TABLES_TO_SYNC:
        try:
            sync_table(sqlite_engine, pg_engine, table_name)
            total_synced += 1
        except Exception as e:
            failed_tables.append((table_name, str(e)))
            continue

    # Summary
    print()
    print("=" * 60)
    print("Sync Summary")
    print("=" * 60)
    print(f"[OK] Successfully synced: {total_synced}/{len(TABLES_TO_SYNC)} tables")

    if failed_tables:
        print(f"[ERROR] Failed: {len(failed_tables)} tables")
        for table, error in failed_tables:
            print(f"   - {table}: {error}")

    print()
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == '__main__':
    main()
