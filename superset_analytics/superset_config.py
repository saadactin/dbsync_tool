"""
Superset Configuration File
Custom configuration for DB Sync Tool analytics
"""
import os
from celery.schedules import crontab

# Database connection
SQLALCHEMY_DATABASE_URI = (
    f"postgresql://{os.getenv('DATABASE_USER', 'superset')}:"
    f"{os.getenv('DATABASE_PASSWORD', 'superset')}@"
    f"{os.getenv('DATABASE_HOST', 'superset_db')}:"
    f"{os.getenv('DATABASE_PORT', '5432')}/"
    f"{os.getenv('DATABASE_DB', 'superset')}"
)

# Secret key for signing session cookies
SECRET_KEY = os.getenv('SUPERSET_SECRET_KEY', 'CHANGE_THIS_TO_A_RANDOM_SECRET_KEY')

# Redis for caching
REDIS_HOST = os.getenv('REDIS_HOST', 'superset_cache')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')

# Cache configuration
CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_DEFAULT_TIMEOUT': 300,
    'CACHE_KEY_PREFIX': 'superset_',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
}

# Celery configuration for async queries
class CeleryConfig:
    broker_url = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'
    imports = ('superset.sql_lab',)
    result_backend = f'redis://{REDIS_HOST}:{REDIS_PORT}/1'
    worker_prefetch_multiplier = 1
    task_acks_late = False
    beat_schedule = {
        'reports.scheduler': {
            'task': 'reports.scheduler',
            'schedule': crontab(minute='*', hour='*'),
        },
        'reports.prune_log': {
            'task': 'reports.prune_log',
            'schedule': crontab(minute=10, hour=0),
        },
    }

CELERY_CONFIG = CeleryConfig

# Feature flags
FEATURE_FLAGS = {
    'ENABLE_TEMPLATE_PROCESSING': True,
    'DASHBOARD_NATIVE_FILTERS': True,
    'DASHBOARD_CROSS_FILTERS': True,
    'DASHBOARD_FILTERS_EXPERIMENTAL': True,
    'ENABLE_EXPLORE_DRAG_AND_DROP': True,
    'VERSIONED_EXPORT': True,
}

# Webserver configuration
SUPERSET_WEBSERVER_PORT = 8088
SUPERSET_WEBSERVER_TIMEOUT = 120

# SQL Lab configuration
SQLLAB_TIMEOUT = 300
SUPERSET_WEBSERVER_WORKERS = 4

# Upload folder for file-based uploads
UPLOAD_FOLDER = '/app/superset_home/uploads/'

# Session configuration
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
SESSION_COOKIE_SAMESITE = 'Lax'

# Enable CORS if needed (for API access)
ENABLE_CORS = False
CORS_OPTIONS = {}

# Row limit for SQL Lab
ROW_LIMIT = 5000
SQL_MAX_ROW = 10000

# Public role permissions
PUBLIC_ROLE_LIKE = 'Gamma'

# Enable time-range filter
ENABLE_TIME_RANGE_FILTER = True
