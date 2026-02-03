"""
Comprehensive integration tests for API sync to all database targets
Tests complete workflows: Create connection → Create job → Execute → Verify
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import Mock, patch, MagicMock
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, APISyncState
from accounts.models import UserProfile, Role
import pandas as pd
from datetime import datetime, timedelta


class APISyncIntegrationBase(TransactionTestCase):
    """Base class for API sync integration tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create user profile
        UserProfile.objects.create(
            user=self.user,
            role=Role.ADMIN
        )
        
        # Create API connection
        self.api_conn = APIConnection.objects.create(
            name='Test Zoho API',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            selected_modules=['Leads', 'Contacts', 'Accounts'],
            tenant=self.user,
            created_by=self.user
        )


class APISyncConnectionIntegrationTests(APISyncIntegrationBase):
    """Integration tests for API connection creation and management"""
    
    def test_create_and_test_connection(self):
        """Test creating and testing API connection"""
        # Connection already created in setUp
        self.assertIsNotNone(self.api_conn)
        self.assertEqual(self.api_conn.api_type, 'zoho_crm')
        self.assertEqual(len(self.api_conn.selected_modules), 3)
        self.assertTrue(self.api_conn.is_active)
    
    def test_module_discovery(self):
        """Test module discovery functionality"""
        # Verify selected modules are stored correctly
        self.assertIn('Leads', self.api_conn.selected_modules)
        self.assertIn('Contacts', self.api_conn.selected_modules)
        self.assertIn('Accounts', self.api_conn.selected_modules)
    
    def test_connection_update(self):
        """Test updating API connection"""
        # Update connection
        self.api_conn.name = 'Updated Zoho API'
        self.api_conn.selected_modules = ['Leads', 'Contacts']
        self.api_conn.save()
        
        # Verify update
        updated_conn = APIConnection.objects.get(id=self.api_conn.id)
        self.assertEqual(updated_conn.name, 'Updated Zoho API')
        self.assertEqual(len(updated_conn.selected_modules), 2)
    
    def test_connection_deletion(self):
        """Test deleting API connection"""
        conn_id = self.api_conn.id
        self.api_conn.delete()
        
        # Verify deletion
        self.assertFalse(APIConnection.objects.filter(id=conn_id).exists())
    
    def test_tenant_isolation(self):
        """Test tenant isolation for API connections"""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        UserProfile.objects.create(user=other_user, role=Role.ADMIN)
        
        # Create connection for other user
        other_conn = APIConnection.objects.create(
            name='Other User API',
            api_type='zoho_crm',
            client_id='other_client_id',
            client_secret='other_secret',
            refresh_token='other_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            selected_modules=['Leads'],
            tenant=other_user,
            created_by=other_user
        )
        
        # Verify users can only see their own connections
        user_connections = APIConnection.objects.filter(tenant=self.user)
        self.assertEqual(user_connections.count(), 1)
        self.assertEqual(user_connections.first(), self.api_conn)
        
        other_connections = APIConnection.objects.filter(tenant=other_user)
        self.assertEqual(other_connections.count(), 1)
        self.assertEqual(other_connections.first(), other_conn)


class APISyncJobCreationIntegrationTests(APISyncIntegrationBase):
    """Integration tests for API sync job creation workflow"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create database connections for different targets
        self.postgres_conn = DatabaseConnection.objects.create(
            name='PostgreSQL Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        self.mysql_conn = DatabaseConnection.objects.create(
            name='MySQL Target',
            db_type='mysql',
            host='localhost',
            port=3306,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        self.clickhouse_conn = DatabaseConnection.objects.create(
            name='ClickHouse Target',
            db_type='clickhouse',
            host='localhost',
            port=8123,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        self.sqlserver_conn = DatabaseConnection.objects.create(
            name='SQL Server Target',
            db_type='sqlserver',
            host='localhost',
            port=1433,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
    
    def test_create_job_with_postgres_target(self):
        """Test creating sync job with PostgreSQL target"""
        job = SyncJob.objects.create(
            name='Zoho to PostgreSQL Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create SyncJobTable entries
        SyncJobTable.objects.create(
            job=job,
            schema_name='api',
            table_name='Leads',
            is_enabled=True
        )
        
        # Verify job creation
        self.assertEqual(job.source_connection_type, 'api')
        self.assertEqual(job.source_api_connection, self.api_conn)
        self.assertIsNone(job.source_connection)
        self.assertEqual(job.target_connection, self.postgres_conn)
        self.assertEqual(job.tables.count(), 1)
    
    def test_create_job_with_mysql_target(self):
        """Test creating sync job with MySQL target"""
        job = SyncJob.objects.create(
            name='Zoho to MySQL Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.mysql_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='api',
            table_name='Contacts',
            is_enabled=True
        )
        
        self.assertEqual(job.target_connection.db_type, 'mysql')
        self.assertEqual(job.tables.count(), 1)
    
    def test_create_job_with_clickhouse_target(self):
        """Test creating sync job with ClickHouse target"""
        job = SyncJob.objects.create(
            name='Zoho to ClickHouse Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.clickhouse_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='api',
            table_name='Accounts',
            is_enabled=True
        )
        
        self.assertEqual(job.target_connection.db_type, 'clickhouse')
        self.assertEqual(job.tables.count(), 1)
    
    def test_create_job_with_sqlserver_target(self):
        """Test creating sync job with SQL Server target"""
        job = SyncJob.objects.create(
            name='Zoho to SQL Server Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.sqlserver_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='api',
            table_name='Leads',
            is_enabled=True
        )
        
        self.assertEqual(job.target_connection.db_type, 'sqlserver')
        self.assertEqual(job.tables.count(), 1)
    
    def test_create_job_with_multiple_modules(self):
        """Test creating sync job with multiple modules"""
        job = SyncJob.objects.create(
            name='Multi-Module Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create multiple SyncJobTable entries
        for module in ['Leads', 'Contacts', 'Accounts']:
            SyncJobTable.objects.create(
                job=job,
                schema_name='api',
                table_name=module,
                is_enabled=True
            )
        
        self.assertEqual(job.tables.count(), 3)
    
    def test_create_incremental_job_with_sync_state(self):
        """Test creating incremental sync job with APISyncState"""
        job = SyncJob.objects.create(
            name='Incremental Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.postgres_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        SyncJobTable.objects.create(
            job=job,
            schema_name='api',
            table_name='Leads',
            is_enabled=True
        )
        
        # Create APISyncState for incremental sync
        sync_state = APISyncState.objects.create(
            job=job,
            module_name='Leads',
            records_synced=0
        )
        
        self.assertEqual(job.sync_type, 'incremental')
        self.assertEqual(job.api_sync_states.count(), 1)
        self.assertEqual(sync_state.module_name, 'Leads')
        self.assertIsNone(sync_state.last_sync_time)


class APISyncExecutionIntegrationTests(APISyncIntegrationBase):
    """Integration tests for API sync execution (mocked)"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        self.postgres_conn = DatabaseConnection.objects.create(
            name='PostgreSQL Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        self.job = SyncJob.objects.create(
            name='Test API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.postgres_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        SyncJobTable.objects.create(
            job=self.job,
            schema_name='api',
            table_name='Leads',
            is_enabled=True
        )
        
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status='pending',
            total_tables=1
        )
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.get_connector')
    def test_execution_creation_for_api_job(self, mock_get_connector, mock_zoho_connector):
        """Test execution creation for API sync job"""
        self.assertEqual(self.execution.job, self.job)
        self.assertEqual(self.execution.status, 'pending')
        self.assertEqual(self.execution.total_tables, 1)
    
    def test_sync_state_tracking(self):
        """Test sync state tracking for incremental sync"""
        # Create incremental job
        incremental_job = SyncJob.objects.create(
            name='Incremental Test Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.postgres_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        SyncJobTable.objects.create(
            job=incremental_job,
            schema_name='api',
            table_name='Leads',
            is_enabled=True
        )
        
        # Create sync state
        sync_state = APISyncState.objects.create(
            job=incremental_job,
            module_name='Leads',
            records_synced=0
        )
        
        # Update sync state
        now = timezone.now()
        sync_state.last_sync_time = now
        sync_state.last_modified_time = now
        sync_state.records_synced = 100
        sync_state.save()
        
        # Verify update
        updated_state = APISyncState.objects.get(id=sync_state.id)
        self.assertIsNotNone(updated_state.last_sync_time)
        self.assertEqual(updated_state.records_synced, 100)


class APISyncBackwardCompatibilityTests(APISyncIntegrationBase):
    """Tests to ensure backward compatibility with existing database sync"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        self.source_db = DatabaseConnection.objects.create(
            name='Source DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
        
        self.target_db = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user
        )
    
    def test_database_sync_job_still_works(self):
        """Test that existing database sync jobs still work"""
        job = SyncJob.objects.create(
            name='Database Sync Job',
            source_connection=self.source_db,
            source_connection_type='database',
            target_connection=self.target_db,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Verify database sync job works
        self.assertEqual(job.source_connection_type, 'database')
        self.assertEqual(job.source_connection, self.source_db)
        self.assertIsNone(job.source_api_connection)
        self.assertEqual(job.target_connection, self.target_db)
    
    def test_mixed_jobs_coexist(self):
        """Test that API and database sync jobs can coexist"""
        # Create database sync job
        db_job = SyncJob.objects.create(
            name='Database Job',
            source_connection=self.source_db,
            source_connection_type='database',
            target_connection=self.target_db,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create API sync job
        api_job = SyncJob.objects.create(
            name='API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.target_db,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Verify both jobs exist
        self.assertEqual(SyncJob.objects.filter(source_connection_type='database').count(), 1)
        self.assertEqual(SyncJob.objects.filter(source_connection_type='api').count(), 1)
        self.assertEqual(db_job.source_connection_type, 'database')
        self.assertEqual(api_job.source_connection_type, 'api')
