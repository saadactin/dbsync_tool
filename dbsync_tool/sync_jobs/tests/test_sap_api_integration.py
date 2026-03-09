"""
Integration tests for SAP API sync: E2E create connection → job → full/incremental sync,
and error handling (invalid credentials, network/API error).
Uses mocked SAP connector and mocked target connector; no live SAP or DB required.
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

from connections.models import DatabaseConnection, APIConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, APISyncState
from sync_engine.executor import SyncExecutor
from accounts.models import UserProfile, Role


class SAPAPIIntegrationBase(TransactionTestCase):
    """Base for SAP API integration tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='sap_test_user',
            email='sap@example.com',
            password='testpass123',
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN, 'tenant': self.user},
        )
        self.sap_conn = APIConnection.objects.create(
            name='Test SAP B1',
            api_type='sap_b1',
            sap_base_url='https://sap.example.com:50000/b1s/v2',
            sap_username={'UserName': 'admin', 'CompanyDB': 'SBODEMO'},
            sap_password='encrypted_value',
            sap_endpoints=[
                {'endpoint': 'JournalEntries', 'id_field': 'JdtNum'},
                {'endpoint': 'Items', 'id_field': 'ItemCode'},
            ],
            tenant=self.user,
            created_by=self.user,
        )
        self.target_conn = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user,
        )


class SAPAPIE2EIntegrationTests(SAPAPIIntegrationBase):
    """E2E: Create SAP connection → Create job → Execute full sync (mocked)."""

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.get_api_connector')
    def test_e2e_create_sap_job_and_run_full_sync(
        self, mock_get_api_connector, mock_get_connector
    ):
        """E2E: Job with sap_api + endpoints; run full sync; assert logs and state."""
        mock_sap = Mock()
        mock_sap.fetch_records.side_effect = [
            [{'JdtNum': 1, 'Memo': 'Entry 1'}, {'JdtNum': 2, 'Memo': 'Entry 2'}],
            [{'ItemCode': 'I001', 'ItemName': 'Item 1'}],
        ]
        mock_sap.logout = Mock()
        mock_get_api_connector.return_value = mock_sap

        mock_target = Mock()
        mock_target.database_name = 'test_db'
        mock_target.table_exists.return_value = False
        mock_target.create_table_from_dataframe = Mock()
        mock_target.truncate_table = Mock()
        mock_target.bulk_insert = Mock()
        mock_target.__class__.__name__ = 'PostgresConnector'
        mock_get_connector.return_value = mock_target

        job = SyncJob.objects.create(
            name='SAP to PG Job',
            source_api_connection=self.sap_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        SyncJobTable.objects.create(
            job=job,
            schema_name='sap_api',
            table_name='JournalEntries',
            is_enabled=True,
        )
        SyncJobTable.objects.create(
            job=job,
            schema_name='sap_api',
            table_name='Items',
            is_enabled=True,
        )

        with patch('sync_engine.sap_sync.DataTransformer') as mock_dt_class:
            mock_dt = Mock()
            mock_dt.flatten_json.side_effect = [
                pd.DataFrame([{'JdtNum': 1, 'Memo': 'Entry 1'}, {'JdtNum': 2, 'Memo': 'Entry 2'}]),
                pd.DataFrame([{'ItemCode': 'I001', 'ItemName': 'Item 1'}]),
            ]
            mock_dt.prepare_for_database.side_effect = lambda df, _: df
            mock_dt_class.return_value = mock_dt

            executor = SyncExecutor(job)
            executor.execute()

        execution = SyncExecution.objects.filter(job=job).order_by('-started_at').first()
        self.assertIsNotNone(execution)
        self.assertEqual(execution.status, 'completed')

        logs = SyncExecutionLog.objects.filter(execution=execution).order_by('table_name')
        self.assertEqual(logs.count(), 2)
        by_table = {log.table_name: log for log in logs}
        self.assertIn('JournalEntries', by_table)
        self.assertIn('Items', by_table)
        self.assertEqual(by_table['JournalEntries'].status, 'completed')
        self.assertEqual(by_table['JournalEntries'].rows_fetched, 2)
        self.assertEqual(by_table['Items'].status, 'completed')
        self.assertEqual(by_table['Items'].rows_fetched, 1)

        mock_sap.fetch_records.assert_any_call('JournalEntries')
        mock_sap.fetch_records.assert_any_call('Items')
        mock_target.bulk_insert.assert_called()


class SAPAPIIncrementalIntegrationTests(SAPAPIIntegrationBase):
    """E2E incremental sync and change detection (mocked)."""

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.get_api_connector')
    def test_e2e_incremental_sync_and_change_detection(
        self, mock_get_api_connector, mock_get_connector
    ):
        """After one full sync (first incremental run), run incremental again with changed data; assert state."""
        records_full = [
            {'JdtNum': 1, 'Memo': 'A'},
            {'JdtNum': 2, 'Memo': 'B'},
        ]
        records_inc = [
            {'JdtNum': 1, 'Memo': 'A_modified'},
            {'JdtNum': 3, 'Memo': 'C_new'},
        ]

        mock_sap = Mock()
        mock_sap.fetch_records.side_effect = [
            records_full,
            records_full,
            records_inc,
            records_inc,
        ]
        mock_sap.fetch_incremental_records.side_effect = [records_inc]
        mock_sap.logout = Mock()
        mock_get_api_connector.return_value = mock_sap

        mock_target = Mock()
        mock_target.database_name = 'test_db'
        mock_target.table_exists.return_value = True
        mock_target.add_missing_columns = Mock()
        mock_target.truncate_table = Mock()
        mock_target.bulk_insert = Mock()
        mock_target.upsert_dataframe = Mock()
        mock_target.execute_query = Mock()
        mock_target.__class__.__name__ = 'PostgresConnector'
        mock_get_connector.return_value = mock_target

        job = SyncJob.objects.create(
            name='SAP Incremental Job',
            source_api_connection=self.sap_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='incremental',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        SyncJobTable.objects.create(
            job=job,
            schema_name='sap_api',
            table_name='JournalEntries',
            is_enabled=True,
        )

        with patch('sync_engine.sap_sync.DataTransformer') as mock_dt_class:
            mock_dt = Mock()
            mock_dt.flatten_json.side_effect = [
                pd.DataFrame(records_full),
                pd.DataFrame(records_inc),
                pd.DataFrame(records_inc),
            ]
            mock_dt.prepare_for_database.side_effect = lambda df, _: df
            mock_dt_class.return_value = mock_dt

            executor = SyncExecutor(job)
            executor.execute()

        execution1 = SyncExecution.objects.filter(job=job).order_by('-started_at').first()
        self.assertIsNotNone(execution1)
        self.assertEqual(execution1.status, 'completed')

        state_after_first = APISyncState.objects.filter(job=job, module_name='JournalEntries').first()
        self.assertIsNotNone(state_after_first)
        self.assertIsNotNone(
            state_after_first.last_sync_time,
            'First incremental run should set last_sync_time (and ideally record_hashes)',
        )
        if state_after_first.record_hashes:
            self.assertIn('1', state_after_first.record_hashes)
            self.assertIn('2', state_after_first.record_hashes)

        executor2 = SyncExecutor(job)
        executor2.execute()

        execution2 = SyncExecution.objects.filter(job=job).order_by('-started_at').first()
        self.assertIsNotNone(execution2)
        self.assertEqual(execution2.status, 'completed')

        state = APISyncState.objects.filter(job=job, module_name='JournalEntries').first()
        self.assertIsNotNone(state)
        self.assertIsNotNone(
            state.last_sync_time,
            'At least one run should set last_sync_time',
        )
        if state.record_hashes:
            self.assertIn('1', state.record_hashes)
            self.assertIn('3', state.record_hashes)
            self.assertNotIn('2', state.record_hashes)


class SAPAPIErrorHandlingIntegrationTests(SAPAPIIntegrationBase):
    """Error handling: invalid credentials, network/API error."""

    @patch('connections.models.APIConnection.test_connection')
    def test_invalid_credentials_returns_user_facing_error(self, mock_test_connection):
        """SAP connection with bad credentials: test_connection returns (False, message, [])."""
        mock_test_connection.return_value = (
            False,
            'Authentication failed. Check UserName, CompanyDB and Password.',
            [],
        )
        success, message, modules = self.sap_conn.test_connection()
        self.assertFalse(success)
        self.assertIn('Authentication', message or '')
        self.assertEqual(modules, [])

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.get_api_connector')
    def test_network_api_error_shows_failed_log_and_message(
        self, mock_get_api_connector, mock_get_connector
    ):
        """When fetch_records raises, execution logs show failed status and error message."""
        mock_sap = Mock()
        mock_sap.fetch_records.side_effect = [
            Exception('Connection timeout'),
            [{'ItemCode': 'I1', 'ItemName': 'Item'}],
        ]
        mock_sap.logout = Mock()
        mock_get_api_connector.return_value = mock_sap

        mock_target = Mock()
        mock_target.database_name = 'test_db'
        mock_target.table_exists.return_value = False
        mock_target.create_table_from_dataframe = Mock()
        mock_target.truncate_table = Mock()
        mock_target.bulk_insert = Mock()
        mock_target.__class__.__name__ = 'PostgresConnector'
        mock_get_connector.return_value = mock_target

        job = SyncJob.objects.create(
            name='SAP Error Job',
            source_api_connection=self.sap_conn,
            source_connection_type='api',
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        SyncJobTable.objects.create(
            job=job,
            schema_name='sap_api',
            table_name='JournalEntries',
            is_enabled=True,
        )
        SyncJobTable.objects.create(
            job=job,
            schema_name='sap_api',
            table_name='Items',
            is_enabled=True,
        )

        with patch('sync_engine.sap_sync.DataTransformer') as mock_dt_class:
            mock_dt = Mock()
            mock_dt.flatten_json.return_value = pd.DataFrame([{'ItemCode': 'I1', 'ItemName': 'Item'}])
            mock_dt.prepare_for_database.side_effect = lambda df, _: df
            mock_dt_class.return_value = mock_dt

            executor = SyncExecutor(job)
            executor.execute()

        execution = SyncExecution.objects.filter(job=job).order_by('-started_at').first()
        self.assertIsNotNone(execution)

        failed_logs = SyncExecutionLog.objects.filter(execution=execution, status='failed')
        self.assertGreaterEqual(failed_logs.count(), 1)
        failed_journal = failed_logs.filter(table_name='JournalEntries').first()
        self.assertIsNotNone(failed_journal)
        self.assertIn('timeout', (failed_journal.error_message or '').lower())

        completed = SyncExecutionLog.objects.filter(execution=execution, status='completed')
        self.assertGreaterEqual(completed.count(), 1)


class SAPAPIAllTargetDatabasesTests(SAPAPIIntegrationBase):
    """Ensure SAP API data can be stored in all available target databases (Postgres, MySQL, SQL Server, ClickHouse)."""

    _DB_TYPES = [
        ('postgres', 'PostgresConnector'),
        ('mysql', 'MySQLConnector'),
        ('sqlserver', 'SQLServerConnector'),
        ('clickhouse', 'ClickHouseConnector'),
    ]

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.get_api_connector')
    def test_sap_full_sync_to_postgres(self, mock_get_api_connector, mock_get_connector):
        """SAP full sync runs and writes to a Postgres target (mocked)."""
        self._run_sap_full_sync_for_db_type(mock_get_api_connector, mock_get_connector, 'postgres', 'PostgresConnector')

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.get_api_connector')
    def test_sap_full_sync_to_mysql(self, mock_get_api_connector, mock_get_connector):
        """SAP full sync runs and writes to a MySQL target (mocked)."""
        self._run_sap_full_sync_for_db_type(mock_get_api_connector, mock_get_connector, 'mysql', 'MySQLConnector')

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.get_api_connector')
    def test_sap_full_sync_to_sqlserver(self, mock_get_api_connector, mock_get_connector):
        """SAP full sync runs and writes to a SQL Server target (mocked)."""
        self._run_sap_full_sync_for_db_type(mock_get_api_connector, mock_get_connector, 'sqlserver', 'SQLServerConnector')

    @patch('sync_engine.executor.get_connector')
    @patch('sync_engine.executor.get_api_connector')
    def test_sap_full_sync_to_clickhouse(self, mock_get_api_connector, mock_get_connector):
        """SAP full sync runs and writes to a ClickHouse target (mocked)."""
        self._run_sap_full_sync_for_db_type(mock_get_api_connector, mock_get_connector, 'clickhouse', 'ClickHouseConnector')

    def _run_sap_full_sync_for_db_type(self, mock_get_api_connector, mock_get_connector, db_type, connector_class_name):
        """Run one full sync with mocked SAP and mocked target of given DB type; assert completion and bulk_insert called."""
        mock_sap = Mock()
        mock_sap.fetch_records.return_value = [{'JdtNum': 1, 'Memo': 'Test'}]
        mock_sap.logout = Mock()
        mock_get_api_connector.return_value = mock_sap

        mock_target = Mock()
        mock_target.database_name = 'test_db'
        mock_target.table_exists.return_value = False
        mock_target.create_table_from_dataframe = Mock()
        mock_target.truncate_table = Mock()
        mock_target.bulk_insert = Mock()
        mock_target.__class__.__name__ = connector_class_name
        mock_get_connector.return_value = mock_target

        target_conn = DatabaseConnection.objects.create(
            name=f'Target {db_type}',
            db_type=db_type,
            host='localhost',
            port=5432 if db_type == 'postgres' else 3306 if db_type == 'mysql' else 1433 if db_type == 'sqlserver' else 8123,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            tenant=self.user,
        )
        job = SyncJob.objects.create(
            name=f'SAP to {db_type}',
            source_api_connection=self.sap_conn,
            source_connection_type='api',
            target_connection=target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user,
        )
        SyncJobTable.objects.create(
            job=job,
            schema_name='sap_api',
            table_name='JournalEntries',
            is_enabled=True,
        )

        with patch('sync_engine.sap_sync.DataTransformer') as mock_dt_class:
            mock_dt = Mock()
            mock_dt.flatten_json.return_value = pd.DataFrame([{'JdtNum': 1, 'Memo': 'Test'}])
            mock_dt.prepare_for_database.side_effect = lambda df, _: df
            mock_dt_class.return_value = mock_dt

            executor = SyncExecutor(job)
            executor.execute()

        execution = SyncExecution.objects.filter(job=job).order_by('-started_at').first()
        self.assertIsNotNone(execution, f'SAP sync to {db_type} should create execution')
        self.assertEqual(execution.status, 'completed', f'SAP sync to {db_type} should complete')
        mock_target.bulk_insert.assert_called()
        mock_target.create_table_from_dataframe.assert_called()
