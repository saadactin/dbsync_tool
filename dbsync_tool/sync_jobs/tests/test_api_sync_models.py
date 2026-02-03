"""
Unit tests for API sync models (APISyncState and SyncJob extensions)
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, APISyncState
from accounts.models import UserProfile, Role
from accounts.services.tenant_service import TenantService


class APISyncStateModelTests(TestCase):
    """Test cases for APISyncState model"""
    
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
        
        # Create database connection
        self.target_conn = DatabaseConnection.objects.create(
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
        
        # Create API connection
        self.api_conn = APIConnection.objects.create(
            name='Test Zoho API',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            selected_modules=['Leads', 'Contacts'],
            tenant=self.user,
            created_by=self.user
        )
        
        # Create sync job with API source
        self.job = SyncJob.objects.create(
            name='Test API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
    
    def test_apisyncstate_creation(self):
        """Test creating APISyncState"""
        sync_state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        
        self.assertIsNotNone(sync_state.id)
        self.assertEqual(sync_state.job, self.job)
        self.assertEqual(sync_state.module_name, 'Leads')
        self.assertEqual(sync_state.records_synced, 100)
        self.assertIsNone(sync_state.last_sync_time)
        self.assertIsNone(sync_state.last_modified_time)
    
    def test_apisyncstate_unique_constraint(self):
        """Test unique constraint on job and module_name"""
        APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        
        # Try to create duplicate
        with self.assertRaises(Exception):  # IntegrityError or ValidationError
            APISyncState.objects.create(
                job=self.job,
                module_name='Leads',
                records_synced=200
            )
    
    def test_apisyncstate_string_representation(self):
        """Test APISyncState string representation"""
        sync_state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads'
        )
        
        expected = f"Sync state for {self.job.name} - Leads"
        self.assertEqual(str(sync_state), expected)


class SyncJobAPISourceTests(TestCase):
    """Test cases for SyncJob model with API sources"""
    
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
        
        # Create database connection
        self.db_conn = DatabaseConnection.objects.create(
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
        
        # Create API connection
        self.api_conn = APIConnection.objects.create(
            name='Test Zoho API',
            api_type='zoho_crm',
            client_id='test_client_id',
            client_secret='test_secret',
            refresh_token='test_token',
            api_domain='https://www.zohoapis.in',
            token_url='https://accounts.zoho.in/oauth/v2/token',
            selected_modules=['Leads', 'Contacts'],
            tenant=self.user,
            created_by=self.user
        )
    
    def test_syncjob_with_api_source(self):
        """Test creating SyncJob with API source"""
        job = SyncJob.objects.create(
            name='Test API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.db_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        self.assertIsNone(job.source_connection)
        self.assertEqual(job.source_api_connection, self.api_conn)
        self.assertEqual(job.source_connection_type, 'api')
        self.assertTrue(job.is_api_source())
    
    def test_syncjob_with_database_source(self):
        """Test creating SyncJob with database source (backward compatibility)"""
        job = SyncJob.objects.create(
            name='Test DB Job',
            source_connection=self.db_conn,
            source_connection_type='database',
            target_connection=self.db_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        self.assertEqual(job.source_connection, self.db_conn)
        self.assertIsNone(job.source_api_connection)
        self.assertEqual(job.source_connection_type, 'database')
        self.assertFalse(job.is_api_source())
    
    def test_get_source_connection_api(self):
        """Test get_source_connection() for API source"""
        job = SyncJob.objects.create(
            name='Test API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.db_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        source = job.get_source_connection()
        self.assertEqual(source, self.api_conn)
    
    def test_get_source_connection_database(self):
        """Test get_source_connection() for database source"""
        job = SyncJob.objects.create(
            name='Test DB Job',
            source_connection=self.db_conn,
            source_connection_type='database',
            target_connection=self.db_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        source = job.get_source_connection()
        self.assertEqual(source, self.db_conn)
    
    def test_syncjob_validation_api_source(self):
        """Test SyncJob validation for API source"""
        job = SyncJob(
            name='Test API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            source_connection=self.db_conn,  # Should be None for API source
            target_connection=self.db_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        with self.assertRaises(ValidationError):
            job.clean()
            job.save()
    
    def test_syncjob_validation_database_source(self):
        """Test SyncJob validation for database source"""
        job = SyncJob(
            name='Test DB Job',
            source_connection=self.db_conn,
            source_connection_type='database',
            source_api_connection=self.api_conn,  # Should be None for DB source
            target_connection=self.db_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        with self.assertRaises(ValidationError):
            job.clean()
            job.save()
    
    def test_syncjob_backward_compatibility(self):
        """Test backward compatibility - existing jobs without source_connection_type"""
        # Create job without setting source_connection_type (simulating old data)
        job = SyncJob.objects.create(
            name='Old Job',
            source_connection=self.db_conn,
            target_connection=self.db_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Should still work (source_connection_type can be None for backward compatibility)
        self.assertIsNotNone(job.id)
        # get_source_connection should return source_connection if type is None
        source = job.get_source_connection()
        self.assertEqual(source, self.db_conn)
