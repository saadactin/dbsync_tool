"""
Unit tests for API sync executor
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import Mock, patch, MagicMock
from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, APISyncState
from sync_engine.api_sync import APISyncExecutor
from connections.connectors.zoho import ZohoConnector
from connections.connectors.postgres import PostgresConnector
from accounts.models import UserProfile, Role
import pandas as pd
from datetime import datetime, timedelta
from sync_engine.exceptions import TableSyncError


class APISyncExecutorTests(TestCase):
    """Test cases for APISyncExecutor"""
    
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
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create SyncJobTable entries for modules
        SyncJobTable.objects.create(
            job=self.job,
            schema_name='api',
            table_name='Leads',
            is_enabled=True
        )
        
        SyncJobTable.objects.create(
            job=self.job,
            schema_name='api',
            table_name='Contacts',
            is_enabled=True
        )
        
        # Create execution
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status='pending',
            total_tables=2
        )
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.PostgresConnector')
    def test_get_modules_from_job(self, mock_postgres, mock_zoho):
        """Test getting modules from job"""
        # Create mock connectors
        api_connector = Mock(spec=ZohoConnector)
        target_connector = Mock(spec=PostgresConnector)
        target_connector.database_name = 'test_db'
        
        executor = APISyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        
        modules = executor._get_modules_from_job()
        self.assertEqual(len(modules), 2)
        self.assertIn('Leads', modules)
        self.assertIn('Contacts', modules)
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.PostgresConnector')
    @patch('sync_engine.api_sync.DataTransformer')
    def test_sync_module_full(self, mock_transformer, mock_postgres, mock_zoho):
        """Test full sync for a module"""
        # Create mock connectors
        api_connector = Mock(spec=ZohoConnector)
        target_connector = Mock(spec=PostgresConnector)
        target_connector.database_name = 'test_db'
        target_connector.truncate_table = Mock()
        target_connector.bulk_insert = Mock()
        target_connector.table_exists = Mock(return_value=False)
        target_connector.create_table_from_dataframe = Mock()
        
        # Mock API connector to return test data
        test_records = [
            {'id': '1', 'Name': 'Lead 1', 'Email': 'lead1@test.com', 'Modified_Time': '2024-01-01T10:00:00+05:30'},
            {'id': '2', 'Name': 'Lead 2', 'Email': 'lead2@test.com', 'Modified_Time': '2024-01-01T11:00:00+05:30'}
        ]
        api_connector.fetch_records = Mock(return_value=test_records)
        
        # Mock transformer
        mock_transformer_instance = Mock()
        mock_transformer.return_value = mock_transformer_instance
        
        test_df = pd.DataFrame([
            {'id': '1', 'Name': 'Lead 1', 'Email': 'lead1@test.com', '_ingestion_timestamp': datetime.now()},
            {'id': '2', 'Name': 'Lead 2', 'Email': 'lead2@test.com', '_ingestion_timestamp': datetime.now()}
        ])
        mock_transformer_instance.flatten_json = Mock(return_value=test_df)
        mock_transformer_instance.prepare_for_database = Mock(return_value=test_df)
        
        executor = APISyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor.transformer = mock_transformer_instance
        
        # Execute full sync for one module
        executor._sync_module_full('Leads')
        
        # Verify API connector was called
        api_connector.fetch_records.assert_called_once_with('Leads')
        
        # Verify transformer was called
        mock_transformer_instance.flatten_json.assert_called_once()
        mock_transformer_instance.prepare_for_database.assert_called_once()
        
        # Verify target connector methods were called
        target_connector.create_table_from_dataframe.assert_called_once()
        target_connector.truncate_table.assert_called_once()
        target_connector.bulk_insert.assert_called()
        
        # Verify execution log was created
        log = SyncExecutionLog.objects.get(execution=self.execution, table_name='Leads')
        self.assertEqual(log.status, 'completed')
        self.assertEqual(log.rows_fetched, 2)
        self.assertEqual(log.rows_inserted, 2)
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.PostgresConnector')
    @patch('sync_engine.api_sync.DataTransformer')
    def test_sync_module_incremental(self, mock_transformer, mock_postgres, mock_zoho):
        """Test incremental sync for a module"""
        # Create mock connectors
        api_connector = Mock(spec=ZohoConnector)
        target_connector = Mock(spec=PostgresConnector)
        target_connector.database_name = 'test_db'
        target_connector.table_exists = Mock(return_value=True)
        target_connector.add_missing_columns = Mock()
        target_connector.bulk_insert = Mock()
        
        # Mock API connector to return test data
        test_records = [
            {'id': '3', 'Name': 'Lead 3', 'Email': 'lead3@test.com', 'Modified_Time': '2024-01-02T10:00:00+05:30'}
        ]
        api_connector.fetch_incremental_records = Mock(return_value=test_records)
        
        # Mock transformer
        mock_transformer_instance = Mock()
        mock_transformer.return_value = mock_transformer_instance
        
        test_df = pd.DataFrame([
            {'id': '3', 'Name': 'Lead 3', 'Email': 'lead3@test.com', '_ingestion_timestamp': datetime.now()}
        ])
        mock_transformer_instance.flatten_json = Mock(return_value=test_df)
        mock_transformer_instance.prepare_for_database = Mock(return_value=test_df)
        
        executor = APISyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor.transformer = mock_transformer_instance
        
        # Create existing sync state
        sync_state = APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            last_sync_time=timezone.now(),
            last_modified_time=datetime(2024, 1, 1, 12, 0, 0)
        )
        
        # Execute incremental sync
        executor._sync_module_incremental('Leads')
        
        # Verify API connector was called with since parameter
        api_connector.fetch_incremental_records.assert_called_once()
        call_args = api_connector.fetch_incremental_records.call_args
        self.assertEqual(call_args[0][0], 'Leads')  # module name
        
        # Verify transformer was called
        mock_transformer_instance.flatten_json.assert_called_once()
        mock_transformer_instance.prepare_for_database.assert_called_once()
        
        # Verify target connector methods were called
        target_connector.add_missing_columns.assert_called_once()
        target_connector.bulk_insert.assert_called()
        
        # Verify sync state was updated
        sync_state.refresh_from_db()
        self.assertIsNotNone(sync_state.last_sync_time)
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.PostgresConnector')
    def test_get_target_db_type(self, mock_postgres, mock_zoho):
        """Test getting target database type"""
        api_connector = Mock(spec=ZohoConnector)
        target_connector = Mock(spec=PostgresConnector)
        target_connector.__class__.__name__ = 'PostgresConnector'
        target_connector.database_name = 'test_db'
        
        executor = APISyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        
        db_type = executor._get_target_db_type()
        self.assertEqual(db_type, 'postgres')
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.PostgresConnector')
    def test_ensure_table_exists_new_table(self, mock_postgres, mock_zoho):
        """Test _ensure_table_exists for new table"""
        api_connector = Mock(spec=ZohoConnector)
        target_connector = Mock(spec=PostgresConnector)
        target_connector.database_name = 'test_db'
        target_connector.table_exists = Mock(return_value=False)
        target_connector.create_table_from_dataframe = Mock()
        
        executor = APISyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        
        test_df = pd.DataFrame({'id': [1], 'name': ['Test']})
        executor._ensure_table_exists(test_df, 'test_schema', 'test_table')
        
        target_connector.table_exists.assert_called_once_with('test_schema', 'test_table')
        target_connector.create_table_from_dataframe.assert_called_once_with('test_schema', 'test_table', test_df)
        target_connector.add_missing_columns.assert_not_called()
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.PostgresConnector')
    def test_ensure_table_exists_existing_table(self, mock_postgres, mock_zoho):
        """Test _ensure_table_exists for existing table"""
        api_connector = Mock(spec=ZohoConnector)
        target_connector = Mock(spec=PostgresConnector)
        target_connector.database_name = 'test_db'
        target_connector.table_exists = Mock(return_value=True)
        target_connector.add_missing_columns = Mock()
        
        executor = APISyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        
        test_df = pd.DataFrame({'id': [1], 'name': ['Test'], 'new_col': ['New']})
        executor._ensure_table_exists(test_df, 'test_schema', 'test_table')
        
        target_connector.table_exists.assert_called_once_with('test_schema', 'test_table')
        target_connector.add_missing_columns.assert_called_once_with('test_schema', 'test_table', test_df)
        target_connector.create_table_from_dataframe.assert_not_called()
    
    @patch('sync_engine.api_sync.ZohoConnector')
    @patch('sync_engine.api_sync.PostgresConnector')
    @patch('sync_engine.api_sync.DataTransformer')
    def test_sync_module_incremental_with_upsert(self, mock_transformer, mock_postgres, mock_zoho):
        """Test incremental sync with upsert_dataframe"""
        api_connector = Mock(spec=ZohoConnector)
        target_connector = Mock(spec=PostgresConnector)
        target_connector.database_name = 'test_db'
        target_connector.table_exists = Mock(return_value=True)
        target_connector.add_missing_columns = Mock()
        target_connector.upsert_dataframe = Mock()
        
        # Mock API connector
        test_records = [
            {'id': '1', 'Name': 'Updated Lead', 'Email': 'updated@test.com', 'Modified_Time': '2024-01-02T10:00:00+05:30'}
        ]
        api_connector.fetch_incremental_records = Mock(return_value=test_records)
        
        # Mock transformer
        mock_transformer_instance = Mock()
        mock_transformer.return_value = mock_transformer_instance
        
        test_df = pd.DataFrame([
            {'id': '1', 'Name': 'Updated Lead', 'Email': 'updated@test.com', '_ingestion_timestamp': datetime.now()}
        ])
        mock_transformer_instance.flatten_json = Mock(return_value=test_df)
        mock_transformer_instance.prepare_for_database = Mock(return_value=test_df)
        
        executor = APISyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor.transformer = mock_transformer_instance
        
        # Create existing sync state
        APISyncState.objects.create(
            job=self.job,
            module_name='Leads',
            last_sync_time=timezone.now() - timedelta(hours=1),
            last_modified_time=datetime(2024, 1, 1, 12, 0, 0)
        )
        
        # Execute incremental sync
        executor._sync_module_incremental('Leads')
        
        # Verify upsert was called (not bulk_insert)
        target_connector.upsert_dataframe.assert_called()
        # bulk_insert should not be called when upsert is available
        if hasattr(target_connector, 'bulk_insert'):
            self.assertFalse(hasattr(target_connector.bulk_insert, 'call_count') or 
                           not target_connector.bulk_insert.called)
