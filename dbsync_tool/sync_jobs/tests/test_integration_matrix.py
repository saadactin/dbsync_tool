"""
Comprehensive integration tests for all database combinations
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from sync_jobs.tests.test_helpers import (
    create_test_connections,
    setup_test_tables,
    create_test_job,
    verify_sync_results
)
import os
import logging

logger = logging.getLogger(__name__)

# Test database configurations
TEST_DATABASES = {
    'postgres': {
        'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
        'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
        'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
        'database': os.getenv('TEST_POSTGRES_DB', 'test_sync_source'),
        'target_database': os.getenv('TEST_POSTGRES_TARGET_DB', 'test_sync_target'),
    },
    'mysql': {
        'host': os.getenv('TEST_MYSQL_HOST', 'localhost'),
        'port': int(os.getenv('TEST_MYSQL_PORT', 3306)),
        'username': os.getenv('TEST_MYSQL_USER', 'root'),
        'password': os.getenv('TEST_MYSQL_PASSWORD', 'root'),
        'database': os.getenv('TEST_MYSQL_DB', 'test_sync_source'),
        'target_database': os.getenv('TEST_MYSQL_TARGET_DB', 'test_sync_target'),
    },
    'sqlserver': {
        'host': os.getenv('TEST_SQLSERVER_HOST', 'localhost'),
        'port': int(os.getenv('TEST_SQLSERVER_PORT', 1433)),
        'username': os.getenv('TEST_SQLSERVER_USER', 'sa'),
        'password': os.getenv('TEST_SQLSERVER_PASSWORD', 'YourPassword123'),
        'database': os.getenv('TEST_SQLSERVER_DB', 'test_sync_source'),
        'target_database': os.getenv('TEST_SQLSERVER_TARGET_DB', 'test_sync_target'),
    },
}

# All 9 combinations: (source, target)
DATABASE_COMBINATIONS = [
    ('postgres', 'postgres'),
    ('postgres', 'mysql'),
    ('postgres', 'sqlserver'),
    ('mysql', 'postgres'),
    ('mysql', 'mysql'),
    ('mysql', 'sqlserver'),
    ('sqlserver', 'postgres'),
    ('sqlserver', 'mysql'),
    ('sqlserver', 'sqlserver'),
]

class BaseIntegrationTest(TransactionTestCase):
    """Base class for integration tests"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
    
    def setUp(self):
        """Set up test data for each test"""
        self.test_tables_config = {
            'users': [
                {'name': 'id', 'type': 'INTEGER', 'primary_key': True},
                {'name': 'username', 'type': 'VARCHAR(255)'},
                {'name': 'email', 'type': 'VARCHAR(255)'},
                {'name': 'created_at', 'type': 'TIMESTAMP'},
            ],
            'products': [
                {'name': 'id', 'type': 'INTEGER', 'primary_key': True},
                {'name': 'name', 'type': 'VARCHAR(255)'},
                {'name': 'price', 'type': 'DECIMAL(10,2)'},
                {'name': 'description', 'type': 'TEXT'},
            ],
        }
    
    def _check_database_available(self, db_type):
        """
        Check if test database is available
        
        Args:
            db_type: Database type to check
        
        Returns:
            bool: True if database is available
        """
        try:
            config = TEST_DATABASES[db_type]
            connector_class = None
            
            if db_type == 'postgres':
                from connections.connectors.postgres import PostgresConnector
                connector_class = PostgresConnector
            elif db_type == 'mysql':
                from connections.connectors.mysql import MySQLConnector
                connector_class = MySQLConnector
            elif db_type == 'sqlserver':
                from connections.connectors.sqlserver import SQLServerConnector
                connector_class = SQLServerConnector
            
            if connector_class:
                connector = connector_class(
                    host=config['host'],
                    port=config['port'],
                    username=config['username'],
                    password=config['password'],
                    database_name=config['database']
                )
                connector.connect()
                connector.close()
                return True
        except Exception as e:
            logger.warning(f"Database {db_type} not available: {str(e)}")
            return False
        return False

# Generate test methods for each combination dynamically
for source_type, target_type in DATABASE_COMBINATIONS:
    test_name = f'test_{source_type}_to_{target_type}_sync'
    
    def make_test(source=source_type, target=target_type):
        def test_method(self):
            """Test sync from {source} to {target}"""
            # Skip if test databases not available
            if not self._check_database_available(source) or \
               not self._check_database_available(target):
                self.skipTest(f"Test databases not available: {source} -> {target}")
            
            # Create connections
            source_config = TEST_DATABASES[source]
            target_config = TEST_DATABASES[target]
            
            source_conn, target_conn = create_test_connections(
                self.user, source, target, source_config, target_config
            )
            
            # Setup source tables
            source_connector = get_connector(source_conn)
            schema = 'public' if source == 'postgres' else source_conn.database_name
            setup_test_tables(source_connector, schema, self.test_tables_config)
            
            # Create job
            tables = [(schema, table) for table in self.test_tables_config.keys()]
            job = create_test_job(self.user, source_conn, target_conn, tables)
            
            # Execute sync
            executor = SyncExecutor(job)
            executor.execute()
            
            # Verify results
            target_connector = get_connector(target_conn)
            target_schema = 'public' if target == 'postgres' else target_conn.database_name
            for table_name in self.test_tables_config.keys():
                verify_sync_results(
                    source_connector, target_connector, target_schema, table_name
                )
            
            # Verify execution record
            execution = SyncExecution.objects.filter(job=job).latest('started_at')
            self.assertEqual(execution.status, 'completed')
            self.assertEqual(execution.completed_tables, len(tables))
        
        test_method.__name__ = test_name
        test_method.__doc__ = f"Test sync from {source} to {target}"
        return test_method
    
    setattr(BaseIntegrationTest, test_name, make_test())

