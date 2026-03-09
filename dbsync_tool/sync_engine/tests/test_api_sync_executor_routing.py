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
        
        # Create user profile (get_or_create in case signal already created one)
        UserProfile.objects.get_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN}
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
        
        # Create API connection (Zoho)
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
        # Create SAP API connection for SAP routing test
        self.sap_api_conn = APIConnection.objects.create(
            name='Test SAP API',
            api_type='sap_b1',
            sap_base_url='https://sap.example.com/b1s/v1',
            sap_username={'UserName': 'test', 'CompanyDB': 'SBODEMO'},
            sap_password='test',
            sap_endpoints=['JournalEntries'],
            tenant=self.user,
            created_by=self.user
        )
        
        # Create sync job with API source (Zoho)
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
        # Create sync job with SAP API source
        self.sap_job = SyncJob.objects.create(
            name='Test SAP Job',
            source_api_connection=self.sap_api_conn,
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
    
    @patch('sync_engine.executor.get_api_connector')
    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.APISyncExecutor')
    def test_executor_routes_to_api_sync_for_api_source(self, mock_api_executor, mock_get_connector, mock_get_api_connector):
        """Test executor routes to APISyncExecutor for Zoho API source"""
        mock_api_connector = Mock()
        mock_get_api_connector.return_value = mock_api_connector
        mock_target_connector = Mock()
        mock_get_connector.return_value = mock_target_connector
        mock_executor_instance = Mock()
        mock_api_executor.return_value = mock_executor_instance

        executor = SyncExecutor(self.api_job)
        executor.execute()

        mock_get_api_connector.assert_called_once_with(self.api_conn)
        mock_api_executor.assert_called_once()
        mock_executor_instance.execute.assert_called_once()
    
    @patch('sync_engine.executor.get_api_connector')
    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.SAPSyncExecutor')
    def test_executor_routes_to_sap_sync_for_sap_api_source(self, mock_sap_executor, mock_get_connector, mock_get_api_connector):
        """Test executor routes to SAPSyncExecutor for SAP B1 API source"""
        mock_api_connector = Mock()
        mock_get_api_connector.return_value = mock_api_connector
        mock_target_connector = Mock()
        mock_get_connector.return_value = mock_target_connector
        mock_executor_instance = Mock()
        mock_sap_executor.return_value = mock_executor_instance

        executor = SyncExecutor(self.sap_job)
        executor.execute()

        mock_get_api_connector.assert_called_once_with(self.sap_api_conn)
        mock_sap_executor.assert_called_once()
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
