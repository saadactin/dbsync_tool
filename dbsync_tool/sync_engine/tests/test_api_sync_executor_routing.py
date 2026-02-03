"""
Tests for API sync executor routing in SyncExecutor
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import Mock, patch, MagicMock
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from accounts.models import UserProfile, Role


class APISyncExecutorRoutingTests(TestCase):
    """Test cases for API sync executor routing"""
    
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
            selected_modules=['Leads'],
            tenant=self.user,
            created_by=self.user
        )
        
        # Create sync job with API source
        self.api_job = SyncJob.objects.create(
            name='Test API Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create sync job with database source
        self.db_job = SyncJob.objects.create(
            name='Test DB Job',
            source_connection=self.target_conn,
            source_connection_type='database',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
    
    @patch('sync_engine.executor.ZohoConnector')
    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.APISyncExecutor')
    def test_executor_routes_to_api_sync_for_api_source(self, mock_api_executor, mock_get_connector, mock_zoho):
        """Test executor routes to APISyncExecutor for API source"""
        # Mock API connector
        mock_api_connector = Mock()
        mock_zoho.return_value = mock_api_connector
        
        # Mock target connector
        mock_target_connector = Mock()
        mock_get_connector.return_value = mock_target_connector
        
        # Mock API executor
        mock_executor_instance = Mock()
        mock_api_executor.return_value = mock_executor_instance
        
        # Create executor and execute
        executor = SyncExecutor(self.api_job)
        executor.execute()
        
        # Verify ZohoConnector was created
        mock_zoho.assert_called_once_with(self.api_conn)
        
        # Verify APISyncExecutor was created and executed
        mock_api_executor.assert_called_once()
        mock_executor_instance.execute.assert_called_once()
    
    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.FullSyncExecutor')
    def test_executor_routes_to_full_sync_for_database_source(self, mock_full_executor, mock_get_connector):
        """Test executor routes to FullSyncExecutor for database source"""
        # Mock connectors
        mock_source_connector = Mock()
        mock_target_connector = Mock()
        mock_get_connector.side_effect = [mock_source_connector, mock_target_connector]
        
        # Mock full executor
        mock_executor_instance = Mock()
        mock_full_executor.return_value = mock_executor_instance
        
        # Create executor and execute
        executor = SyncExecutor(self.db_job)
        executor.execute()
        
        # Verify FullSyncExecutor was created and executed
        mock_full_executor.assert_called_once()
        mock_executor_instance.execute.assert_called_once()
