"""
Unit tests for SAP sync executor (SAPSyncExecutor).
Uses mocked API connector, target connector, and DataTransformer.
"""
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
import pandas as pd
from datetime import datetime

from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, APISyncState
from sync_engine.sap_sync import SAPSyncExecutor
from accounts.models import UserProfile, Role


class SAPSyncExecutorTests(TestCase):
    """Test cases for SAPSyncExecutor"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        UserProfile.objects.get_or_create(user=self.user, defaults={'role': Role.ADMIN})
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
        self.api_conn = APIConnection.objects.create(
            name='Test SAP API',
            api_type='sap_b1',
            sap_base_url='https://sap.example.com/b1s/v2',
            sap_username={'UserName': 'U', 'CompanyDB': 'DB'},
            sap_password='encrypted',
            sap_endpoints=[{'endpoint': 'JournalEntries', 'id_field': 'JdtNum'}],
            tenant=self.user,
            created_by=self.user
        )
        self.job = SyncJob.objects.create(
            name='Test SAP Job',
            source_api_connection=self.api_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        SyncJobTable.objects.create(
            job=self.job,
            schema_name='sap_api',
            table_name='JournalEntries',
            is_enabled=True
        )
        SyncJobTable.objects.create(
            job=self.job,
            schema_name='sap_api',
            table_name='Items',
            is_enabled=True
        )
        self.execution = SyncExecution.objects.create(
            job=self.job,
            status='pending',
            total_tables=2
        )

    def test_get_endpoints_from_job(self):
        """_get_endpoints_from_job returns unique endpoint names from job.tables."""
        api_connector = Mock()
        target_connector = Mock()
        target_connector.database_name = 'test_db'
        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        endpoints = executor._get_endpoints_from_job()
        self.assertEqual(len(endpoints), 2)
        self.assertIn('JournalEntries', endpoints)
        self.assertIn('Items', endpoints)

    def test_execute_full_sync_type(self):
        """execute() calls execute_full_sync when job.sync_type is 'full'."""
        api_connector = Mock()
        target_connector = Mock()
        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        with patch.object(executor, 'execute_full_sync') as mock_full:
            executor.execute()
            mock_full.assert_called_once()

    def test_execute_incremental_sync_type(self):
        """execute() calls execute_incremental_sync when job.sync_type is 'incremental'."""
        self.job.sync_type = 'incremental'
        self.job.save()
        api_connector = Mock()
        target_connector = Mock()
        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        with patch.object(executor, 'execute_incremental_sync') as mock_inc:
            executor.execute()
            mock_inc.assert_called_once()

    def test_execute_unknown_sync_type_raises(self):
        """execute() raises ValueError for unknown sync_type."""
        self.job.sync_type = 'unknown'
        self.job.save()
        api_connector = Mock()
        target_connector = Mock()
        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        with self.assertRaises(ValueError):
            executor.execute()

    @patch('sync_engine.sap_sync.DataTransformer')
    def test_sync_endpoint_full_happy_path(self, mock_transformer_class):
        """execute_full_sync: fetch_records, flatten, prepare, ensure_table, truncate, bulk_insert, update state."""
        api_connector = Mock()
        api_connector.fetch_records.return_value = [
            {'JdtNum': 1, 'RefDate': '2024-01-01'},
            {'JdtNum': 2, 'RefDate': '2024-01-02'},
        ]
        target_connector = Mock()
        target_connector.database_name = 'test_db'
        target_connector.table_exists.return_value = False
        target_connector.create_table_from_dataframe = Mock()
        target_connector.truncate_table = Mock()
        target_connector.bulk_insert = Mock()
        target_connector.__class__.__name__ = 'PostgresConnector'

        mock_transformer = Mock()
        mock_transformer_class.return_value = mock_transformer
        test_df = pd.DataFrame([{'JdtNum': 1, 'RefDate': '2024-01-01'}, {'JdtNum': 2, 'RefDate': '2024-01-02'}])
        mock_transformer.flatten_json.return_value = test_df
        mock_transformer.prepare_for_database.return_value = test_df

        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor.transformer = mock_transformer
        executor.execute_full_sync()

        api_connector.fetch_records.assert_any_call('JournalEntries')
        api_connector.fetch_records.assert_any_call('Items')
        logs = SyncExecutionLog.objects.filter(execution=self.execution, status='completed')
        self.assertEqual(logs.count(), 2)
        state = APISyncState.objects.filter(job=self.job, module_name='JournalEntries').first()
        self.assertIsNotNone(state)
        self.assertIsNotNone(state.last_sync_time)

    @patch('sync_engine.sap_sync.DataTransformer')
    def test_sync_endpoint_full_one_endpoint_fails(self, mock_transformer_class):
        """When one endpoint raises, error log is created and other endpoints still run."""
        api_connector = Mock()
        api_connector.fetch_records.side_effect = [Exception('API error'), [{'ItemCode': 'I1'}]]
        target_connector = Mock()
        target_connector.database_name = 'test_db'
        target_connector.table_exists.return_value = False
        target_connector.create_table_from_dataframe = Mock()
        target_connector.truncate_table = Mock()
        target_connector.bulk_insert = Mock()
        target_connector.__class__.__name__ = 'PostgresConnector'
        mock_transformer = Mock()
        mock_transformer_class.return_value = mock_transformer
        mock_transformer.flatten_json.return_value = pd.DataFrame([{'ItemCode': 'I1'}])
        mock_transformer.prepare_for_database.return_value = pd.DataFrame([{'ItemCode': 'I1'}])

        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor.transformer = mock_transformer
        executor.execute_full_sync()

        failed_logs = SyncExecutionLog.objects.filter(execution=self.execution, status='failed')
        self.assertGreaterEqual(failed_logs.count(), 1)
        failed_table_names = list(failed_logs.values_list('table_name', flat=True))
        self.assertIn('JournalEntries', failed_table_names)
        completed_logs = SyncExecutionLog.objects.filter(execution=self.execution, status='completed')
        self.assertEqual(completed_logs.count(), 1)
        self.assertEqual(completed_logs.first().table_name, 'Items')

    @patch('sync_engine.sap_sync.sap_sync_state')
    @patch('sync_engine.sap_sync.DataTransformer')
    def test_sync_endpoint_incremental_first_run_runs_full(self, mock_transformer_class, mock_sap_state):
        """First incremental (no state/hashes) runs full sync for endpoint."""
        mock_sap_state.get_hashes.return_value = {}
        mock_sap_state.get_or_create_state.return_value = Mock(last_sync_time=None, records_synced=0, save=Mock())
        mock_sap_state.save_hashes = Mock()

        api_connector = Mock()
        api_connector.fetch_records.return_value = [{'JdtNum': 1}]
        api_connector.fetch_incremental_records.return_value = [{'JdtNum': 1}]
        target_connector = Mock()
        target_connector.database_name = 'test_db'
        target_connector.table_exists.return_value = False
        target_connector.create_table_from_dataframe = Mock()
        target_connector.truncate_table = Mock()
        target_connector.bulk_insert = Mock()
        target_connector.__class__.__name__ = 'PostgresConnector'
        mock_transformer = Mock()
        mock_transformer_class.return_value = mock_transformer
        mock_transformer.flatten_json.return_value = pd.DataFrame([{'JdtNum': 1}])
        mock_transformer.prepare_for_database.return_value = pd.DataFrame([{'JdtNum': 1}])

        self.job.sync_type = 'incremental'
        self.job.save()
        state_obj = APISyncState.objects.create(
            job=self.job,
            module_name='JournalEntries',
            last_sync_time=None,
        )
        mock_sap_state.get_or_create_state.return_value = state_obj

        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor.transformer = mock_transformer
        executor.execute_incremental_sync()

        api_connector.fetch_records.assert_called()
        mock_sap_state.get_hashes.assert_called()

    @patch('sync_engine.sap_sync.sap_sync_state')
    @patch('sync_engine.sap_sync.DataTransformer')
    def test_sync_endpoint_incremental_missing_target_table_skips(self, mock_transformer_class, mock_sap_state):
        """Incremental SAP sync should skip endpoint when target table is missing."""
        mock_sap_state.get_hashes.return_value = {"1": "oldhash"}
        state_obj = APISyncState.objects.create(
            job=self.job,
            module_name='JournalEntries',
            last_sync_time=timezone.now(),
        )
        mock_sap_state.get_or_create_state.return_value = state_obj
        mock_sap_state.save_hashes = Mock()

        api_connector = Mock()
        api_connector.fetch_incremental_records.return_value = [{'JdtNum': 1, 'RefDate': '2024-01-03'}]

        target_connector = Mock()
        target_connector.database_name = 'test_db'
        target_connector.table_exists.return_value = False
        target_connector.add_missing_columns = Mock()
        target_connector.upsert_dataframe = Mock()
        target_connector.__class__.__name__ = 'PostgresConnector'

        mock_transformer = Mock()
        mock_transformer_class.return_value = mock_transformer
        df = pd.DataFrame([{'JdtNum': 1, 'RefDate': '2024-01-03'}])
        mock_transformer.flatten_json.return_value = df
        mock_transformer.prepare_for_database.return_value = df

        self.job.sync_type = 'incremental'
        self.job.save()

        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor.transformer = mock_transformer
        executor._sync_endpoint_incremental('JournalEntries')

        target_connector.add_missing_columns.assert_not_called()
        target_connector.upsert_dataframe.assert_not_called()
        log = SyncExecutionLog.objects.filter(execution=self.execution, table_name='JournalEntries').latest('id')
        self.assertEqual(log.status, 'completed')
        self.assertIn('does not exist', (log.error_message or '').lower())

    def test_create_error_log(self):
        """_create_error_log creates SyncExecutionLog with status failed."""
        api_connector = Mock()
        target_connector = Mock()
        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        executor._create_error_log('JournalEntries', 'Test error message')
        log = SyncExecutionLog.objects.get(execution=self.execution, table_name='JournalEntries', status='failed')
        self.assertEqual(log.error_message, 'Test error message')

    def test_get_id_field_for_endpoint(self):
        """_get_id_field_for_endpoint returns id_field from SAP_DOCUMENT_TYPES."""
        api_connector = Mock()
        target_connector = Mock()
        executor = SAPSyncExecutor(
            job=self.job,
            execution=self.execution,
            api_connector=api_connector,
            target_connector=target_connector
        )
        self.assertEqual(executor._get_id_field_for_endpoint('JournalEntries'), 'JdtNum')
        self.assertEqual(executor._get_id_field_for_endpoint('Items'), 'ItemCode')
        self.assertIsNone(executor._get_id_field_for_endpoint('NonExistent'))
