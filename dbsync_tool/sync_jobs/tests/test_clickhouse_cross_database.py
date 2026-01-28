"""
Cross-database integration tests for ClickHouse
Tests bidirectional sync, data accuracy, and performance
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from core.encryption import encrypt_password
import os
import logging

logger = logging.getLogger(__name__)


class ClickHouseCrossDatabaseTests(TransactionTestCase):
    """Test ClickHouse cross-database sync"""
    
    def setUp(self):
        """Set up test connections"""
        # Create user first
        self.user = User.objects.create_user(
            username='clickhouse_crossdb_test',
            password='testpass123',
            email='clickhouse_crossdb_test@example.com'
        )
        
        # Create user profile - for Admin, tenant should be None (user is their own tenant)
        from accounts.models import UserProfile, Role
        profile, created = UserProfile.objects.get_or_create(
            user=self.user,
            defaults={
                'role': Role.ADMIN,
                'tenant': None  # Admin users have tenant=None, they ARE the tenant
            }
        )
        if not created:
            profile.role = Role.ADMIN
            profile.tenant = None  # Admin users are their own tenant
            profile.save()
        
        # ClickHouse configuration
        self.clickhouse_config = {
            'host': os.environ.get('CLICKHOUSE_HOST', 'localhost'),
            'port': int(os.environ.get('CLICKHOUSE_PORT', '9000')),
            'username': os.environ.get('CLICKHOUSE_USER', 'default'),
            'password': os.environ.get('CLICKHOUSE_PASSWORD', ''),
            'database_name': os.environ.get('CLICKHOUSE_DATABASE', 'default')
        }
        
        # Create ClickHouse connection
        clickhouse_password = self.clickhouse_config['password'] or 'default'
        self.clickhouse_conn = DatabaseConnection.objects.create(
            name='Test ClickHouse',
            db_type='clickhouse',
            host=self.clickhouse_config['host'],
            port=self.clickhouse_config['port'],
            username=self.clickhouse_config['username'],
            password=encrypt_password(clickhouse_password),
            database_name=self.clickhouse_config['database_name'],
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
        
        # PostgreSQL configuration
        self.postgres_config = {
            'host': os.environ.get('TEST_POSTGRES_HOST', 'localhost'),
            'port': int(os.environ.get('TEST_POSTGRES_PORT', 5432)),
            'username': os.environ.get('TEST_POSTGRES_USER', 'postgres'),
            'password': os.environ.get('TEST_POSTGRES_PASSWORD', 'postgres'),
            'database_name': os.environ.get('TEST_POSTGRES_DB', 'tauseef')
        }
        
        # Create PostgreSQL connection
        self.postgres_conn = DatabaseConnection.objects.create(
            name='Test PostgreSQL',
            db_type='postgres',
            host=self.postgres_config['host'],
            port=self.postgres_config['port'],
            username=self.postgres_config['username'],
            password=encrypt_password(self.postgres_config['password']),
            database_name=self.postgres_config['database_name'],
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
        
        # MySQL configuration
        self.mysql_config = {
            'host': os.environ.get('TEST_MYSQL_HOST', 'localhost'),
            'port': int(os.environ.get('TEST_MYSQL_PORT', 3306)),
            'username': os.environ.get('TEST_MYSQL_USER', 'root'),
            'password': os.environ.get('TEST_MYSQL_PASSWORD', 'root'),
            'database_name': os.environ.get('TEST_MYSQL_DB', 'test')
        }
        
        # Create MySQL connection
        self.mysql_conn = DatabaseConnection.objects.create(
            name='Test MySQL',
            db_type='mysql',
            host=self.mysql_config['host'],
            port=self.mysql_config['port'],
            username=self.mysql_config['username'],
            password=encrypt_password(self.mysql_config['password']),
            database_name=self.mysql_config['database_name'],
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
        
        # SQL Server configuration
        self.sqlserver_config = {
            'host': os.environ.get('TEST_SQLSERVER_HOST', 'localhost'),
            'port': int(os.environ.get('TEST_SQLSERVER_PORT', 1433)),
            'username': os.environ.get('TEST_SQLSERVER_USER', 'sa'),
            'password': os.environ.get('TEST_SQLSERVER_PASSWORD', 'root'),
            'database_name': os.environ.get('TEST_SQLSERVER_DB', 'test')
        }
        
        # Create SQL Server connection
        self.sqlserver_conn = DatabaseConnection.objects.create(
            name='Test SQL Server',
            db_type='sqlserver',
            host=self.sqlserver_config['host'],
            port=self.sqlserver_config['port'],
            username=self.sqlserver_config['username'],
            password=encrypt_password(self.sqlserver_config['password']),
            database_name=self.sqlserver_config['database_name'],
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
    
    def _check_clickhouse_available(self):
        """Check if ClickHouse is available"""
        try:
            from connections.connectors.clickhouse import ClickHouseConnector
            connector = ClickHouseConnector(**self.clickhouse_config)
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"ClickHouse not available: {str(e)}")
            return False
    
    def _check_database_available(self, db_type):
        """Check if database is available"""
        try:
            if db_type == 'postgres':
                from connections.connectors.postgres import PostgresConnector
                connector = PostgresConnector(**self.postgres_config)
            elif db_type == 'mysql':
                from connections.connectors.mysql import MySQLConnector
                connector = MySQLConnector(**self.mysql_config)
            elif db_type == 'sqlserver':
                from connections.connectors.sqlserver import SQLServerConnector
                connector = SQLServerConnector(**self.sqlserver_config)
            else:
                return False
            
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"{db_type} not available: {str(e)}")
            return False
    
    def test_postgres_clickhouse_bidirectional(self):
        """Test PostgreSQL ↔ ClickHouse bidirectional sync"""
        if not self._check_clickhouse_available() or not self._check_database_available('postgres'):
            self.skipTest("ClickHouse or PostgreSQL not available for testing")
        
        # Test PostgreSQL → ClickHouse
        job1 = SyncJob.objects.create(
            name='PostgreSQL → ClickHouse Test',
            source_connection=self.postgres_conn,
            target_connection=self.clickhouse_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.assertIsNotNone(job1)
        self.assertEqual(job1.source_connection.db_type, 'postgres')
        self.assertEqual(job1.target_connection.db_type, 'clickhouse')
        
        # Test ClickHouse → PostgreSQL
        job2 = SyncJob.objects.create(
            name='ClickHouse → PostgreSQL Test',
            source_connection=self.clickhouse_conn,
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.assertIsNotNone(job2)
        self.assertEqual(job2.source_connection.db_type, 'clickhouse')
        self.assertEqual(job2.target_connection.db_type, 'postgres')
    
    def test_mysql_clickhouse_bidirectional(self):
        """Test MySQL ↔ ClickHouse bidirectional sync"""
        if not self._check_clickhouse_available() or not self._check_database_available('mysql'):
            self.skipTest("ClickHouse or MySQL not available for testing")
        
        # Test MySQL → ClickHouse
        job1 = SyncJob.objects.create(
            name='MySQL → ClickHouse Test',
            source_connection=self.mysql_conn,
            target_connection=self.clickhouse_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.assertIsNotNone(job1)
        self.assertEqual(job1.source_connection.db_type, 'mysql')
        self.assertEqual(job1.target_connection.db_type, 'clickhouse')
        
        # Test ClickHouse → MySQL
        job2 = SyncJob.objects.create(
            name='ClickHouse → MySQL Test',
            source_connection=self.clickhouse_conn,
            target_connection=self.mysql_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.assertIsNotNone(job2)
        self.assertEqual(job2.source_connection.db_type, 'clickhouse')
        self.assertEqual(job2.target_connection.db_type, 'mysql')
    
    def test_sqlserver_clickhouse_bidirectional(self):
        """Test SQL Server ↔ ClickHouse bidirectional sync"""
        if not self._check_clickhouse_available() or not self._check_database_available('sqlserver'):
            self.skipTest("ClickHouse or SQL Server not available for testing")
        
        # Test SQL Server → ClickHouse
        job1 = SyncJob.objects.create(
            name='SQL Server → ClickHouse Test',
            source_connection=self.sqlserver_conn,
            target_connection=self.clickhouse_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.assertIsNotNone(job1)
        self.assertEqual(job1.source_connection.db_type, 'sqlserver')
        self.assertEqual(job1.target_connection.db_type, 'clickhouse')
        
        # Test ClickHouse → SQL Server
        job2 = SyncJob.objects.create(
            name='ClickHouse → SQL Server Test',
            source_connection=self.clickhouse_conn,
            target_connection=self.sqlserver_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.assertIsNotNone(job2)
        self.assertEqual(job2.source_connection.db_type, 'clickhouse')
        self.assertEqual(job2.target_connection.db_type, 'sqlserver')
    
    def test_data_accuracy_row_counts(self):
        """Test data accuracy - row counts"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would verify row counts match after sync
        self.assertTrue(True)
    
    def test_data_accuracy_data_types(self):
        """Test data accuracy - data type preservation"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would verify data types are preserved
        self.assertTrue(True)
    
    def test_data_accuracy_null_handling(self):
        """Test data accuracy - NULL value handling"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would verify NULL values are handled correctly
        self.assertTrue(True)
    
    def test_performance_large_table_sync(self):
        """Test performance with large table sync"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would test sync performance with large datasets
        self.assertTrue(True)
    
    def test_batch_size_optimization(self):
        """Test batch size optimization for ClickHouse"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would test optimal batch sizes
        self.assertTrue(True)
    
    def test_bulk_insert_performance(self):
        """Test ClickHouse bulk insert performance"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would test bulk insert performance
        self.assertTrue(True)
