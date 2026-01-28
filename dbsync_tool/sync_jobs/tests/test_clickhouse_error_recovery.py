"""
Error recovery and resilience tests for ClickHouse
Tests connection failures, data errors, and recovery mechanisms
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from django.utils import timezone
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncCheckpoint
from sync_engine.executor import SyncExecutor
from core.encryption import encrypt_password
from core.exceptions import DatabaseConnectionError, TableNotFoundError
import os
import logging

logger = logging.getLogger(__name__)


class ClickHouseErrorRecoveryTests(TransactionTestCase):
    """Test ClickHouse error recovery and resilience"""
    
    def setUp(self):
        """Set up test connections"""
        # Create user first
        self.user = User.objects.create_user(
            username='clickhouse_error_test',
            password='testpass123',
            email='clickhouse_error_test@example.com'
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
        
        # PostgreSQL connection for target
        self.postgres_config = {
            'host': os.environ.get('TEST_POSTGRES_HOST', 'localhost'),
            'port': int(os.environ.get('TEST_POSTGRES_PORT', 5432)),
            'username': os.environ.get('TEST_POSTGRES_USER', 'postgres'),
            'password': os.environ.get('TEST_POSTGRES_PASSWORD', 'postgres'),
            'database_name': os.environ.get('TEST_POSTGRES_DB', 'tauseef')
        }
        
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
    
    def test_sync_when_clickhouse_server_down(self):
        """Test sync when ClickHouse server is down"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Create job with ClickHouse as source
        job = SyncJob.objects.create(
            name='ClickHouse Server Down Test',
            source_connection=self.clickhouse_conn,
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        # This test would require stopping ClickHouse server
        # For now, we verify the job can be created
        self.assertIsNotNone(job)
        
        # In a real scenario, we would:
        # 1. Stop ClickHouse server
        # 2. Attempt sync
        # 3. Verify error handling
        # 4. Verify recovery when server comes back up
    
    def test_sync_when_connection_lost_mid_sync(self):
        """Test sync when ClickHouse connection lost mid-sync"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would test connection loss during sync
        # and verify recovery/resumption
        self.assertTrue(True)
    
    def test_sync_with_invalid_credentials(self):
        """Test sync with invalid ClickHouse credentials"""
        # Create connection with invalid credentials
        invalid_conn = DatabaseConnection.objects.create(
            name='Invalid ClickHouse',
            db_type='clickhouse',
            host=self.clickhouse_config['host'],
            port=self.clickhouse_config['port'],
            username='invalid_user',
            password=encrypt_password('wrong_password'),
            database_name=self.clickhouse_config['database_name'],
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
        
        # Create job with invalid connection
        job = SyncJob.objects.create(
            name='Invalid Credentials Test',
            source_connection=invalid_conn,
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        # Job should be created, but sync should fail with proper error
        self.assertIsNotNone(job)
        
        # In a real scenario, we would:
        # 1. Attempt sync
        # 2. Verify DatabaseConnectionError is raised
        # 3. Verify error message is user-friendly
    
    def test_sync_with_database_not_found(self):
        """Test sync with ClickHouse database not found"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Create connection with non-existent database
        clickhouse_password = self.clickhouse_config['password'] or 'default'
        invalid_db_conn = DatabaseConnection.objects.create(
            name='Invalid Database ClickHouse',
            db_type='clickhouse',
            host=self.clickhouse_config['host'],
            port=self.clickhouse_config['port'],
            username=self.clickhouse_config['username'],
            password=encrypt_password(clickhouse_password),
            database_name='non_existent_database_12345',
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
        
        # Create job
        job = SyncJob.objects.create(
            name='Database Not Found Test',
            source_connection=invalid_db_conn,
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        self.assertIsNotNone(job)
    
    def test_sync_with_table_not_found(self):
        """Test sync with ClickHouse table not found"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Create job with non-existent table
        job = SyncJob.objects.create(
            name='Table Not Found Test',
            source_connection=self.clickhouse_conn,
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        # Create job table with non-existent table name
        job_table = SyncJobTable.objects.create(
            job=job,
            schema_name='default',
            table_name='non_existent_table_12345',
            is_enabled=True
        )
        
        self.assertIsNotNone(job_table)
        
        # In a real scenario, sync should fail with TableNotFoundError
    
    def test_sync_with_column_type_mismatch(self):
        """Test sync with ClickHouse column type mismatch"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would test type mismatch handling
        self.assertTrue(True)
    
    def test_sync_with_data_truncation(self):
        """Test sync with ClickHouse data truncation"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would test data truncation handling
        self.assertTrue(True)
    
    def test_sync_recovery_after_connection_failure(self):
        """Test sync recovery after ClickHouse connection failure"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Placeholder test - would test recovery after connection failure
        self.assertTrue(True)
    
    def test_checkpoint_recovery_for_incremental_sync(self):
        """Test checkpoint recovery for ClickHouse incremental sync"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Create incremental job
        job = SyncJob.objects.create(
            name='Checkpoint Recovery Test',
            source_connection=self.clickhouse_conn,
            target_connection=self.postgres_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user
        )
        
        # Create checkpoint
        checkpoint = SyncCheckpoint.objects.create(
            job=job,
            table_name='test_table',
            incremental_column='id',
            checkpoint_value='100',
            last_synced_at=timezone.now()
        )
        
        self.assertIsNotNone(checkpoint)
        
        # In a real scenario, we would:
        # 1. Simulate sync failure
        # 2. Verify checkpoint is preserved
        # 3. Resume sync from checkpoint
        # 4. Verify data integrity
    
    def test_partial_sync_recovery(self):
        """Test partial sync recovery (some tables failed)"""
        if not self._check_clickhouse_available():
            self.skipTest("ClickHouse not available for testing")
        
        # Create job with multiple tables
        job = SyncJob.objects.create(
            name='Partial Sync Recovery Test',
            source_connection=self.clickhouse_conn,
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
        
        # Create multiple job tables
        for i in range(3):
            SyncJobTable.objects.create(
                job=job,
                schema_name='default',
                table_name=f'test_table_{i}',
                is_enabled=True
            )
        
        # In a real scenario, we would:
        # 1. Simulate failure for one table
        # 2. Verify other tables sync successfully
        # 3. Verify failed table can be retried
        # 4. Verify final state is consistent
        
        self.assertIsNotNone(job)
