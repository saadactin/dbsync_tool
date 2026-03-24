"""
Tests for API sync executor routing in SyncExecutor
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import Mock, patch, MagicMock
from connections.models import DatabaseConnection, APIConnection, FileSourceConnection
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
        # Create Azure DevOps API connection
        self.azure_api_conn = APIConnection.objects.create(
            name='Test Azure DevOps API',
            api_type='azure_devops',
            azure_tenant_id='00000000-0000-0000-0000-000000000000',
            azure_client_id='azure-client-id',
            azure_client_secret='azure-client-secret',
            organization='TORAI',
            tenant=self.user,
            created_by=self.user,
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
        
        # Create sync job with API source (Zoho) - full sync
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
        # Zoho incremental job should be routed to zoho_increment.py runner
        self.zoho_incremental_job = SyncJob.objects.create(
            name='Test Zoho Incremental Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        # Create sync job with Azure DevOps API source
        self.azure_job = SyncJob.objects.create(
            name='Test Azure DevOps Job',
            source_api_connection=self.azure_api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        # Create incremental Azure DevOps job
        self.azure_incremental_job = SyncJob.objects.create(
            name='Test Azure DevOps Incremental Job',
            source_api_connection=self.azure_api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user,
            tenant=self.user,
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
        self.file_source_conn = FileSourceConnection.objects.create(
            name='Flat File Source',
            relative_path='orders.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            created_by=self.user,
            tenant=self.user,
            is_active=True,
        )
        self.flat_file_job = SyncJob.objects.create(
            name='Test Flat File Job',
            source_file_connection=self.file_source_conn,
            source_connection_type='flat_file',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
    
    @patch('sync_engine.executor.run_zoho_sync')
    @patch('sync_engine.executor.get_api_connector')
    @patch('sync_engine.executor.get_connector')
    def test_executor_routes_zoho_full_job_to_zoho_runner(
        self,
        mock_get_connector,
        mock_get_api_connector,
        mock_run_zoho_runner,
    ):
        """Zoho full API jobs should be routed to Zoho runner"""
        executor = SyncExecutor(self.api_job)
        executor.execute()

        # For Zoho full we should not go through generic API connector path
        mock_get_api_connector.assert_not_called()
        mock_get_connector.assert_not_called()

        mock_run_zoho_runner.assert_called_once()
        call_args, call_kwargs = mock_run_zoho_runner.call_args
        # Job passed as kwarg, mode should be 'full'
        self.assertEqual(call_kwargs.get('job'), self.api_job)
        self.assertEqual(call_kwargs.get('mode'), 'full')

    @patch('sync_engine.executor.run_azure_devops_sync')
    @patch('sync_engine.executor.get_api_connector')
    @patch('sync_engine.executor.get_connector')
    def test_executor_routes_to_azure_runner_for_azure_devops_api_source(
        self,
        mock_get_connector,
        mock_get_api_connector,
        mock_run_azure_runner,
    ):
        """Test executor routes to AzureDevOpsRunner for Azure DevOps API source"""
        executor = SyncExecutor(self.azure_job)
        executor.execute()

        # For Azure DevOps we should not go through generic API connector path
        mock_get_api_connector.assert_not_called()
        mock_get_connector.assert_not_called()

        mock_run_azure_runner.assert_called_once()
        call_args, call_kwargs = mock_run_azure_runner.call_args
        self.assertEqual(call_kwargs.get('job'), self.azure_job)
        # mode should be taken from job.sync_type
        self.assertEqual(call_kwargs.get('mode'), self.azure_job.sync_type)

    @patch('sync_engine.executor.run_azure_devops_sync')
    @patch('sync_engine.executor.get_api_connector')
    @patch('sync_engine.executor.get_connector')
    def test_executor_routes_incremental_azure_job_with_incremental_mode(
        self,
        mock_get_connector,
        mock_get_api_connector,
        mock_run_azure_runner,
    ):
        """Test executor passes incremental mode for incremental Azure DevOps job"""
        executor = SyncExecutor(self.azure_incremental_job)
        executor.execute()

        mock_get_api_connector.assert_not_called()
        mock_get_connector.assert_not_called()

        mock_run_azure_runner.assert_called_once()
        call_args, call_kwargs = mock_run_azure_runner.call_args
        self.assertEqual(call_kwargs.get('job'), self.azure_incremental_job)
        self.assertEqual(call_kwargs.get('mode'), 'incremental')

    @patch('sync_engine.executor.run_zoho_sync')
    @patch('sync_engine.executor.get_api_connector')
    @patch('sync_engine.executor.get_connector')
    def test_executor_routes_zoho_incremental_job_to_zoho_runner(
        self,
        mock_get_connector,
        mock_get_api_connector,
        mock_run_zoho_runner,
    ):
        """Zoho incremental API jobs should be routed to Zoho runner"""
        executor = SyncExecutor(self.zoho_incremental_job)
        executor.execute()

        # For Zoho incremental we should not go through generic API connector path
        mock_get_api_connector.assert_not_called()
        mock_get_connector.assert_not_called()

        mock_run_zoho_runner.assert_called_once()
        call_args, call_kwargs = mock_run_zoho_runner.call_args
        # Job passed as kwarg, mode should be 'incremental'
        self.assertEqual(call_kwargs.get('job'), self.zoho_incremental_job)
        self.assertEqual(call_kwargs.get('mode'), 'incremental')
    
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

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.FlatFileSyncExecutor')
    def test_executor_routes_to_flat_file_executor_for_flat_file_source(self, mock_flat_executor, mock_get_connector):
        """Test executor routes to FlatFileSyncExecutor for flat-file source"""
        mock_target_connector = Mock()
        mock_get_connector.return_value = mock_target_connector
        mock_executor_instance = Mock()
        mock_flat_executor.return_value = mock_executor_instance

        executor = SyncExecutor(self.flat_file_job)
        executor.execute()

        mock_flat_executor.assert_called_once()
        mock_executor_instance.execute.assert_called_once()
