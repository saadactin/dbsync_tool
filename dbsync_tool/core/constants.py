"""
Constants used throughout the application
"""

# Database type choices
DB_TYPES = [
    ('postgres', 'PostgreSQL'),
    ('mysql', 'MySQL'),
    ('sqlserver', 'SQL Server'),
]

DB_TYPE_CHOICES = DB_TYPES

# Default ports for each database type
DEFAULT_PORTS = {
    'postgres': 5432,
    'mysql': 3306,
    'sqlserver': 1433,
}

# Connection string templates (for reference, not used directly)
CONNECTION_STRING_TEMPLATES = {
    'postgres': 'postgresql://{username}:{password}@{host}:{port}/{database}',
    'mysql': 'mysql+connector://{username}:{password}@{host}:{port}/{database}',
    'sqlserver': 'mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server',
}

# Sync job status choices
SYNC_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('running', 'Running'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
    ('paused', 'Paused'),
]

# Sync type choices
SYNC_TYPE_CHOICES = [
    ('full', 'Full Sync'),
    ('incremental', 'Incremental Sync'),
]

# Execution status choices
EXECUTION_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('running', 'Running'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
    ('cancelled', 'Cancelled'),
]

# Schedule type choices
SCHEDULE_TYPE_CHOICES = [
    ('once', 'Once'),
    ('hourly', 'Hourly'),
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('custom', 'Custom Cron'),
]

# Batch processing constants
DEFAULT_BATCH_SIZE = 5000  # Rows per batch
MAX_BATCH_SIZE = 10000
MIN_BATCH_SIZE = 100

# Type mapping reference (actual implementation in type_mapping.py)
TYPE_MAPPING_MODULE = 'core.type_mapping'

