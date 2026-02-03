"""
Tests for Day 6 APISyncState helper methods
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, APISyncState
from accounts.models import UserProfile, Role


class APISyncStateHelperMethodsTests(TestCase):
    """Test cases for APISyncState helper methods"""
    
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
    
    def test_get_for_job(self):
        """Test get_for_job class method"""
        # Create sync states
        state1 = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        state2 = APISyncState.objects.create(
            job=self.job,
            module_name='Contacts',
            records_synced=200
        )
        
        # Get all states for job
        states = APISyncState.get_for_job(self.job)
        
        self.assertEqual(states.count(), 2)
        self.assertIn(state1, states)
        self.assertIn(state2, states)
    
    def test_get_for_module(self):
        """Test get_for_module class method"""
        # Create sync state
        state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        
        # Get state for module
        retrieved_state = APISyncState.get_for_module(self.job, 'Leads')
        
        self.assertIsNotNone(retrieved_state)
        self.assertEqual(retrieved_state, state)
        self.assertEqual(retrieved_state.module_name, 'Leads')
    
    def test_get_for_module_not_found(self):
        """Test get_for_module when module doesn't exist"""
        retrieved_state = APISyncState.get_for_module(self.job, 'Nonexistent')
        
        self.assertIsNone(retrieved_state)
    
    def test_update_sync_time(self):
        """Test update_sync_time method"""
        state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        
        initial_sync_time = state.last_sync_time
        initial_records = state.records_synced
        
        # Update sync time
        last_modified = timezone.now() - timedelta(hours=1)
        state.update_sync_time(50, last_modified)
        
        # Refresh from database
        state.refresh_from_db()
        
        self.assertIsNotNone(state.last_sync_time)
        self.assertEqual(state.last_modified_time, last_modified)
        self.assertEqual(state.records_synced, initial_records + 50)
    
    def test_update_sync_time_without_last_modified(self):
        """Test update_sync_time without last_modified"""
        state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=100
        )
        
        initial_records = state.records_synced
        
        # Update sync time without last_modified
        state.update_sync_time(50)
        
        # Refresh from database
        state.refresh_from_db()
        
        self.assertIsNotNone(state.last_sync_time)
        self.assertEqual(state.records_synced, initial_records + 50)
    
    def test_get_data_freshness(self):
        """Test get_data_freshness method"""
        # Create state with sync time
        sync_time = timezone.now() - timedelta(hours=5)
        state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            last_sync_time=sync_time,
            records_synced=100
        )
        
        freshness = state.get_data_freshness()
        
        self.assertIsNotNone(freshness)
        self.assertIsInstance(freshness, timedelta)
        # Should be approximately 5 hours (within 1 minute tolerance)
        self.assertAlmostEqual(freshness.total_seconds(), 5 * 3600, delta=60)
    
    def test_get_data_freshness_no_sync(self):
        """Test get_data_freshness when never synced"""
        state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            records_synced=0
        )
        
        freshness = state.get_data_freshness()
        
        self.assertIsNone(freshness)
