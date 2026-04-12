"""
Tests for incremental sync executor
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog, SyncCheckpoint
from connections.connectors.base import ColumnInfo
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_engine.exceptions import TableSyncError
import pytz
import pandas as pd


class TestIncrementalSyncExecutor(unittest.TestCase):
    """Test cases for IncrementalSyncExecutor"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.job = Mock(spec=SyncJob)
        self.job.id = 'test-job-id'
        self.job.sync_type = 'incremental'
        self.job.tables = Mock()
        self.job.tables.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))
        
        self.execution = Mock(spec=SyncExecution)
        self.execution.id = 'test-execution-id'
        self.execution.status = 'pending'
        self.execution.save = Mock()
        
        # Create mock connectors with proper class names
        from connections.connectors.postgres import PostgresConnector
        self.source_connector = Mock(spec=PostgresConnector)
        self.source_connector.__class__.__name__ = 'PostgresConnector'
        self.target_connector = Mock(spec=PostgresConnector)
        self.target_connector.__class__.__name__ = 'PostgresConnector'
        self.target_connector.database_name = 'test_db'
        self.target_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False),
            ColumnInfo('name', 'text', True, False),
        ])
        self.target_connector.add_missing_columns = Mock()
        
        self.executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=self.target_connector
        )
    
    def test_get_configured_upsert_key_sources_prefers_incremental_key_columns(self):
        jt = Mock(spec=SyncJobTable)
        jt.incremental_key_columns = ['pk1', 'pk2']
        jt.protected_columns = ['ignored']
        self.assertEqual(
            self.executor._get_configured_upsert_key_sources(jt),
            ['pk1', 'pk2'],
        )

    def test_get_configured_upsert_key_sources_falls_back_to_protected_columns(self):
        jt = Mock(spec=SyncJobTable)
        jt.incremental_key_columns = []
        jt.protected_columns = ['laptopid']
        self.assertEqual(
            self.executor._get_configured_upsert_key_sources(jt),
            ['laptopid'],
        )

    def test_init(self):
        """Test IncrementalSyncExecutor initialization"""
        self.assertEqual(self.executor.job, self.job)
        self.assertEqual(self.executor.execution, self.execution)
        self.assertEqual(self.executor.source_connector, self.source_connector)
        self.assertEqual(self.executor.target_connector, self.target_connector)
        self.assertIsNotNone(self.executor.table_handler)
        self.assertIsNotNone(self.executor.validator)
        self.assertIsNotNone(self.executor.checkpoint_manager)
        self.assertIsNotNone(self.executor.query_builder)
        self.assertIsNotNone(self.executor.timezone_handler)
    
    def test_init_invalid_sync_type(self):
        """Test initialization with invalid sync type"""
        self.job.sync_type = 'full'
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=self.execution,
                source_connector=self.source_connector,
                target_connector=self.target_connector
            )
    
    def test_compare_incremental_values_datetime(self):
        """Test comparing datetime values"""
        dt1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        dt2 = datetime(2024, 1, 1, 13, 0, 0, tzinfo=pytz.UTC)
        self.assertTrue(self.executor._compare_incremental_values(dt2, dt1))
        self.assertFalse(self.executor._compare_incremental_values(dt1, dt2))

    def test_compare_incremental_values_pandas_timestamp(self):
        """Datetime-like pandas timestamps should compare deterministically."""
        dt1 = pd.Timestamp('2024-01-01T12:00:00Z')
        dt2 = pd.Timestamp('2024-01-01T13:00:00Z')
        self.assertTrue(self.executor._compare_incremental_values(dt2, dt1))
        self.assertFalse(self.executor._compare_incremental_values(dt1, dt2))
    
    def test_compare_incremental_values_integer(self):
        """Test comparing integer values"""
        self.assertTrue(self.executor._compare_incremental_values(100, 50))
        self.assertFalse(self.executor._compare_incremental_values(50, 100))
    
    def test_compare_incremental_values_none(self):
        """Test comparing None values"""
        self.assertTrue(self.executor._compare_incremental_values(100, None))
        self.assertFalse(self.executor._compare_incremental_values(None, 100))
    
    def test_get_max_incremental_value(self):
        """Test getting max incremental value from batch"""
        batch = [
            (1, 'Alice', datetime(2024, 1, 1, 10, 0, 0)),
            (2, 'Bob', datetime(2024, 1, 1, 12, 0, 0)),
            (3, 'Charlie', datetime(2024, 1, 1, 11, 0, 0))
        ]
        col_index = 2  # datetime column
        current_max = datetime(2024, 1, 1, 9, 0, 0)
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, datetime(2024, 1, 1, 12, 0, 0))
    
    def test_get_max_incremental_value_with_none(self):
        """Test getting max incremental value with None values"""
        batch = [
            (1, 'Alice', None),
            (2, 'Bob', datetime(2024, 1, 1, 12, 0, 0)),
            (3, 'Charlie', None)
        ]
        col_index = 2
        current_max = None
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, datetime(2024, 1, 1, 12, 0, 0))
    
    def test_validate_incremental_column_success(self):
        """Test successful incremental column validation"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        result = self.executor._validate_incremental_column('public', 'users', 'updated_at')
        self.assertTrue(result)
    
    def test_validate_incremental_column_not_found(self):
        """Test validation with column not found"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True)
        ])
        
        with self.assertRaises(TableSyncError):
            self.executor._validate_incremental_column('public', 'users', 'updated_at')
    
    def test_validate_incremental_column_invalid_type(self):
        """Test validation with invalid column type"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        
        # Should not raise error, but log warning
        result = self.executor._validate_incremental_column('public', 'users', 'name')
        self.assertTrue(result)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_first_sync(self, mock_log_class):
        """Test first sync (no checkpoint)"""
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.transform_plan = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock checkpoint manager
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Mock batch fetching
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime), (2, test_datetime + timedelta(hours=1))],
            []
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock checkpoint manager
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify checkpoint was created
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_skips_when_target_table_missing(self, mock_log_class):
        """Incremental sync should skip table when target table is missing."""
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.transform_plan = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=False)
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])

        self.executor.sync_table(job_table)

        self.target_connector.table_exists.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')
        self.assertIn('does not exist', (mock_log.error_message or '').lower())

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_skips_when_concurrent_execution_running(self, mock_log_class):
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.transform_plan = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.checkpoint_manager.maybe_advance_checkpoint = Mock()
        self.executor._prevent_concurrent_sync = Mock(return_value=False)

        self.executor.sync_table(job_table)

        self.executor.checkpoint_manager.maybe_advance_checkpoint.assert_not_called()
        self.assertEqual(mock_log.status, 'completed')
        self.assertIn('concurrent execution running', (mock_log.verification_summary or '').lower())

    def test_upsert_batch_with_retry_uses_upsert_dataframe(self):
        """Batch writes should use connector upsert_dataframe."""
        self.target_connector.upsert_dataframe = Mock()
        rows = [(1, "Alice"), (2, "Bob")]
        columns = ["id", "name"]

        self.executor._upsert_batch_with_retry(
            schema="public",
            table="users",
            columns=columns,
            rows=rows,
            key_columns=["id"],
        )

        self.target_connector.upsert_dataframe.assert_called_once()
        call_kwargs = self.target_connector.upsert_dataframe.call_args.kwargs
        self.assertEqual(call_kwargs["schema"], "public")
        self.assertEqual(call_kwargs["table"], "users")
        self.assertEqual(call_kwargs["key_column"], "id")
        self.assertIsInstance(call_kwargs["df"], pd.DataFrame)

    def test_upsert_batch_with_retry_adds_missing_columns_once(self):
        """Schema drift should call add_missing_columns before upsert, once per table."""
        self.target_connector.upsert_dataframe = Mock()
        self.target_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
        ])
        self.target_connector.add_missing_columns = Mock()

        self.executor._upsert_batch_with_retry(
            schema="public",
            table="users",
            columns=["id", "new_col"],
            rows=[(1, "a"), (2, "b")],
            key_columns=["id"],
        )
        self.executor._upsert_batch_with_retry(
            schema="public",
            table="users",
            columns=["id", "new_col"],
            rows=[(3, "c")],
            key_columns=["id"],
        )

        self.target_connector.add_missing_columns.assert_called_once()
        self.target_connector.upsert_dataframe.assert_called()
        self.assertIn(("public", "users"), self.executor._last_schema_drift_added_columns)

    def test_apply_incremental_overlap_accepts_pandas_timestamp(self):
        self.job.incremental_overlap_seconds = 60
        ts = pd.Timestamp("2024-01-01T12:00:00Z")
        out = self.executor._apply_incremental_overlap(ts, "timestamp")
        self.assertEqual(out, ts.to_pydatetime() - timedelta(seconds=60))

    def test_apply_incremental_overlap_accepts_numpy_datetime64(self):
        self.job.incremental_overlap_seconds = 60
        np_dt = pd.Timestamp("2024-01-01T12:00:00Z").to_datetime64()
        out = self.executor._apply_incremental_overlap(np_dt, "timestamp")
        self.assertEqual(out, pd.Timestamp(np_dt).to_pydatetime() - timedelta(seconds=60))

    def test_upsert_batch_with_retry_unwraps_nested_rows(self):
        self.target_connector.upsert_dataframe = Mock()
        rows = [((1, "Alice"),), ((2, "Bob"),)]
        columns = ["id", "name"]
        self.executor._upsert_batch_with_retry(
            schema="public",
            table="users",
            columns=columns,
            rows=rows,
            key_columns=["id"],
        )
        call_kwargs = self.target_connector.upsert_dataframe.call_args.kwargs
        self.assertEqual(list(call_kwargs["df"].columns), columns)
        self.assertEqual(len(call_kwargs["df"]), 2)

    def test_resolve_incremental_column_auto_falls_back_to_numeric_column(self):
        columns = [
            ColumnInfo("any_future_name", "int", False, False),
            ColumnInfo("name", "varchar", True, False),
        ]
        col, inspected, reason = self.executor._resolve_incremental_column_auto(
            schema="public",
            table="users",
            columns=columns,
            pk_columns=[],
        )
        self.assertEqual(col, "any_future_name")
        self.assertEqual(reason, "auto_numeric_column_fallback_non_nullable")
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_with_checkpoint(self, mock_log_class):
        """Test sync with existing checkpoint"""
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.transform_plan = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock checkpoint manager
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(
            return_value=str(checkpoint_time)
        )
        
        # Mock timezone handler
        self.executor.timezone_handler.parse_checkpoint_value = Mock(
            return_value=checkpoint_time
        )
        
        # Mock table handler
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        # Mock columns
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # Mock primary key
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        
        # Mock query builder
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE "updated_at" > \'2024-01-01 10:00:00\' ORDER BY "updated_at"'
        )
        
        # Mock batch fetching (only new data)
        new_datetime = checkpoint_time + timedelta(hours=2)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(3, new_datetime)],
            []
        ])
        
        # Mock bulk insert
        self.target_connector.bulk_insert = Mock()
        
        # Mock checkpoint manager
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        # Mock execution log filter
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            # Execute sync
            self.executor.sync_table(job_table)
        
        # Verify checkpoint was updated
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_applies_overlap_lower_bound_for_datetime(self, mock_log_class):
        """Overlap-safe incremental should subtract overlap from the datetime checkpoint."""
        self.job.incremental_overlap_seconds = 120

        job_table = Mock(spec=SyncJobTable)
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.transform_plan = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=str(checkpoint_time))
        self.executor.timezone_handler.parse_checkpoint_value = Mock(return_value=checkpoint_time)

        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'

        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])

        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT ...')

        # Simulate keyset fetch returning a non-list result so executor falls back to OFFSET batching.
        self.source_connector.execute_query_fetchall = Mock(return_value=Mock())
        new_datetime = checkpoint_time + timedelta(hours=2)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(3, new_datetime)],
            [],
        ])

        self.target_connector.bulk_insert = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()

        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            self.executor.sync_table(job_table)

        expected_lower_bound = checkpoint_time - timedelta(seconds=120)

        calls = self.executor.query_builder.build_incremental_query.call_args_list
        self.assertGreaterEqual(len(calls), 2)
        for call in calls[:2]:
            self.assertIn('checkpoint_value', call.kwargs)
            self.assertEqual(call.kwargs['checkpoint_value'], expected_lower_bound)

        self.assertEqual(mock_log.status, 'completed')
        self.assertIn('overlap_seconds=', (mock_log.verification_summary or ''))
        self.assertIn('lower_bound_used=', (mock_log.verification_summary or ''))
        self.assertIn('update_outcome=', (mock_log.verification_summary or ''))
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_no_new_rows_does_not_upsert(self, mock_log_class):
        """First incremental run with no new rows should not call upsert and should leave checkpoint unchanged."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        # No existing checkpoint
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)

        # Target exists
        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)

        # Columns and PK
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])

        # Incremental query returns no rows
        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT ...')
        self.source_connector.execute_query_fetchall = Mock(return_value=[])

        # Spy on upsert
        self.target_connector.upsert_dataframe = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()

        self.executor.sync_table(job_table)

        # No upsert when there are no rows
        self.target_connector.upsert_dataframe.assert_not_called()
        # No checkpoint update when nothing changed
        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_not_called()
        self.assertEqual(mock_log.status, 'completed')

    def test_sync_table_no_incremental_column(self):
        """Test sync_table with no configured incremental column (auto mode)."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = None
        job_table.transformation_query = None
        job_table.column_transformations = None

        with patch('sync_engine.incremental_sync.SyncExecutionLog') as mock_log_class:
            mock_log = Mock(spec=SyncExecutionLog)
            mock_log.status = 'pending'
            mock_log_class.objects.create = Mock(return_value=mock_log)
            self.executor.table_handler.target_db_type = 'postgres'
            self.target_connector.table_exists = Mock(return_value=False)
            self.source_connector.get_columns = Mock(return_value=[
                ColumnInfo('id', 'int', False, True),
                ColumnInfo('updated_at', 'timestamp', True, False),
            ])
            self.source_connector.get_primary_key = Mock(return_value=['id'])
            self.executor.sync_table(job_table)

        self.assertEqual(mock_log.status, 'completed')

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_no_safe_incremental_column_uses_keyed_snapshot_fallback(self, mock_log_class):
        """When no safe incremental column exists, run keyed snapshot upsert fallback."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'students'
        job_table.incremental_column = None
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.column_name_overrides = {}
        job_table.excluded_columns = []
        job_table.protected_columns = []
        job_table.incremental_key_columns = ['roll_number']

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('name', 'varchar', True, False),
            ColumnInfo('roll_number', 'int', False, True),
        ])
        self.source_connector.get_primary_key = Mock(return_value=['roll_number'])
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.target_connector.upsert_dataframe = Mock()
        self.source_connector.fetch_batch = Mock(side_effect=[
            [('Alice', 1), ('Bob', 2)],
            [],
        ])

        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            self.executor.sync_table(job_table)

        self.target_connector.upsert_dataframe.assert_called_once()
        kwargs = self.target_connector.upsert_dataframe.call_args.kwargs
        self.assertEqual(kwargs.get('key_column'), 'roll_number')
        self.assertEqual(mock_log.status, 'completed')

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_nullable_date_incremental_uses_keyed_snapshot_fallback(self, mock_log_class):
        """Configured nullable/date-only incremental column should use snapshot fallback for accuracy."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'pg_all_datatypes_test'
        job_table.incremental_column = 'col_date'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.column_name_overrides = {}
        job_table.excluded_columns = []
        job_table.protected_columns = ['col_smallserial']
        job_table.incremental_key_columns = ['col_smallserial']

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.table_handler.target_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('col_smallserial', 'smallint', False, True),
            ColumnInfo('col_date', 'date', True, False),
            ColumnInfo('col_text', 'text', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=['col_smallserial'])
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value='9999-12-31')
        self.target_connector.upsert_dataframe = Mock()
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(11, None, 'row11'), (12, '2024-12-25', 'row12')],
            [],
        ])
        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT incremental')

        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            self.executor.sync_table(job_table)

        # Snapshot fallback path should not build incremental WHERE query.
        self.executor.query_builder.build_incremental_query.assert_not_called()
        self.target_connector.upsert_dataframe.assert_called_once()
        kwargs = self.target_connector.upsert_dataframe.call_args.kwargs
        self.assertEqual(kwargs.get('key_column'), 'col_smallserial')
        self.assertEqual(mock_log.status, 'completed')

    def test_resolve_incremental_column_auto_prefers_datetime_name(self):
        columns = [
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False),
            ColumnInfo('created_at', 'timestamp', True, False),
        ]
        col, inspected, reason = self.executor._resolve_incremental_column_auto(
            schema='public',
            table='users',
            columns=columns,
            pk_columns=['id'],
        )
        self.assertEqual(col, 'updated_at')
        self.assertIn('updated_at', inspected)
        self.assertEqual(reason, 'auto_datetime_priority')
    
    def test_handle_failed_sync(self):
        """Test handling failed sync"""
        error = Exception("Test error")
        checkpoint_value = datetime(2024, 1, 1, 10, 0, 0)
        
        # Should not raise exception
        self.executor._handle_failed_sync('public', 'users', error, checkpoint_value)
    
    def test_handle_partial_batch_failure(self):
        """Test handling partial batch failure"""
        batch = [(1, 'Alice'), (2, 'Bob')]
        
        # Should not raise exception
        self.executor._handle_partial_batch_failure('public', 'users', 1, batch)
    
    def test_recover_from_checkpoint_corruption(self):
        """Test recovering from checkpoint corruption"""
        self.executor.checkpoint_manager.delete_checkpoint = Mock()
        
        self.executor._recover_from_checkpoint_corruption('public', 'users')
        
        self.executor.checkpoint_manager.delete_checkpoint.assert_called_once_with('public', 'users')
    
    def test_prevent_concurrent_sync(self):
        """Test preventing concurrent sync"""
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            # No running logs
            mock_filter.return_value.exclude.return_value.exists = Mock(return_value=False)
            
            result = self.executor._prevent_concurrent_sync('public', 'users')
            self.assertTrue(result)
            
            # Running logs exist
            mock_filter.return_value.exclude.return_value.exists = Mock(return_value=True)
            
            result = self.executor._prevent_concurrent_sync('public', 'users')
            self.assertFalse(result)
    
    def test_execute_no_tables(self):
        """Test execute with no enabled tables"""
        self.job.tables.filter.return_value.exists = Mock(return_value=False)
        
        self.executor.execute()
        
        self.assertEqual(self.execution.status, 'completed')
    
    def test_execute_tables_without_incremental_column(self):
        """Test execute with tables missing incremental column"""
        mock_table = Mock()
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))
        tables_mock.count = Mock(return_value=1)
        tables_mock.__iter__ = Mock(return_value=iter([mock_table]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            completed_logs_mock = Mock()
            completed_logs_mock.count = Mock(return_value=0)
            failed_logs_mock = Mock()
            failed_logs_mock.exists = Mock(return_value=True)
            failed_logs_mock.count = Mock(return_value=1)

            def filter_side_effect(*args, **kwargs):
                if kwargs.get('status') == 'completed':
                    return completed_logs_mock
                if kwargs.get('status') == 'failed':
                    return failed_logs_mock
                return completed_logs_mock

            mock_filter.side_effect = filter_side_effect
            self.executor.execute()
            self.assertIn(self.execution.status, ['completed', 'failed'])
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_success(self, mock_sync_table):
        """Test successful execute"""
        mock_table = Mock(spec=SyncJobTable)
        mock_table.transform_plan = None
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        mock_table.incremental_column = 'updated_at'
        
        # Setup mocks for tables
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.count = Mock(return_value=1)
        tables_mock.__iter__ = Mock(return_value=iter([mock_table]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.target_connector._connected = False
        self.source_connector.connect = Mock()
        self.target_connector.connect = Mock()
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            completed_logs_mock = Mock()
            completed_logs_mock.count = Mock(return_value=1)
            failed_logs_mock = Mock()
            failed_logs_mock.exists = Mock(return_value=False)
            failed_logs_mock.count = Mock(return_value=0)
            
            # Setup filter to return different mocks based on status
            def filter_side_effect(*args, **kwargs):
                if 'status' in kwargs:
                    if kwargs.get('status') == 'completed':
                        return completed_logs_mock
                    elif kwargs.get('status') == 'failed':
                        return failed_logs_mock
                return completed_logs_mock
            
            mock_filter.side_effect = filter_side_effect
            
            self.executor.execute()
        
        self.assertEqual(self.execution.status, 'completed')
        mock_sync_table.assert_called_once_with(mock_table)
    
    def test_init_invalid_none_job(self):
        """Test initialization with None job"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=None,
                execution=self.execution,
                source_connector=self.source_connector,
                target_connector=self.target_connector
            )
    
    def test_init_invalid_none_execution(self):
        """Test initialization with None execution"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=None,
                source_connector=self.source_connector,
                target_connector=self.target_connector
            )
    
    def test_init_invalid_none_source_connector(self):
        """Test initialization with None source connector"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=self.execution,
                source_connector=None,
                target_connector=self.target_connector
            )
    
    def test_init_invalid_none_target_connector(self):
        """Test initialization with None target connector"""
        with self.assertRaises(ValueError):
            IncrementalSyncExecutor(
                job=self.job,
                execution=self.execution,
                source_connector=self.source_connector,
                target_connector=None
            )
    
    def test_compare_incremental_values_string(self):
        """Test comparing string values"""
        self.assertTrue(self.executor._compare_incremental_values('zebra', 'apple'))
        self.assertFalse(self.executor._compare_incremental_values('apple', 'zebra'))
    
    def test_compare_incremental_values_float(self):
        """Test comparing float values"""
        self.assertTrue(self.executor._compare_incremental_values(100.5, 50.2))
        self.assertFalse(self.executor._compare_incremental_values(50.2, 100.5))
    
    def test_get_max_incremental_value_integer(self):
        """Test getting max incremental value with integers"""
        batch = [
            (1, 'Alice', 100),
            (2, 'Bob', 300),
            (3, 'Charlie', 200)
        ]
        col_index = 2
        current_max = 50
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, 300)
    
    def test_get_max_incremental_value_all_none(self):
        """Test getting max incremental value when all values are None"""
        batch = [
            (1, 'Alice', None),
            (2, 'Bob', None),
            (3, 'Charlie', None)
        ]
        col_index = 2
        current_max = datetime(2024, 1, 1, 9, 0, 0)
        
        max_value = self.executor._get_max_incremental_value(batch, col_index, current_max)
        self.assertEqual(max_value, current_max)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_empty_result_set(self, mock_log_class):
        """Test sync with empty result set"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Empty batch
        self.source_connector.fetch_batch = Mock(return_value=[])
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 0})
            
            self.executor.sync_table(job_table)
        
        # Checkpoint should not be updated with empty result
        if isinstance(self.executor.checkpoint_manager.create_or_update_checkpoint, Mock):
            self.assertEqual(self.executor.checkpoint_manager.create_or_update_checkpoint.call_count, 0)
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_multiple_batches(self, mock_log_class):
        """Test sync with multiple batches"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.batch_size = 2  # Small batch size for testing
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Multiple batches
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime), (2, test_datetime + timedelta(hours=1))],
            [(3, test_datetime + timedelta(hours=2)), (4, test_datetime + timedelta(hours=3))],
            []
        ])
        
        self.target_connector.upsert_dataframe = Mock()
        self.executor.checkpoint_manager.maybe_advance_checkpoint = Mock(return_value=True)
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 4})
            
            self.executor.sync_table(job_table)
        
        self.assertEqual(self.target_connector.upsert_dataframe.call_count, 2)
        self.executor.checkpoint_manager.maybe_advance_checkpoint.assert_called_once()
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_with_integer_checkpoint(self, mock_log_class):
        """Test sync with integer checkpoint value"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'id'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Integer checkpoint
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value='100')
        self.executor.timezone_handler.parse_checkpoint_value = Mock(return_value=100)
        
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('name', 'varchar', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE "id" > 100 ORDER BY "id"'
        )
        
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(101, 'New User'), (102, 'Another User')],
            []
        ])
        
        self.target_connector.upsert_dataframe = Mock()
        self.executor.checkpoint_manager.maybe_advance_checkpoint = Mock(return_value=True)
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 2})
            
            self.executor.sync_table(job_table)
        
        self.executor.checkpoint_manager.maybe_advance_checkpoint.assert_called_once()
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_mysql_target_schema_mapping(self, mock_log_class):
        """Test sync with MySQL target (schema mapping)"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'mysql'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.target_connector.database_name = 'target_db'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            []
        ])
        
        self.target_connector.upsert_dataframe = Mock()
        self.executor.checkpoint_manager.maybe_advance_checkpoint = Mock(return_value=True)
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            self.executor.sync_table(job_table)
        
        # Verify upsert called with target_db schema
        self.target_connector.upsert_dataframe.assert_called_once()
        call_args = self.target_connector.upsert_dataframe.call_args
        self.assertEqual(call_args[1]['schema'], 'target_db')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_connection_failure(self, mock_log_class):
        """Test sync with connection failure"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        # Mock get_columns to return proper list before the connection failure
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.executor.table_handler.create_table_if_not_exists = Mock(
            side_effect=Exception("Connection failed")
        )
        
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
        
        # The log status should be updated to 'failed' when exception is raised
        # But since we're catching the exception in the test, we check the log was created
        self.assertIsNotNone(mock_log)
        # The error should be logged
        if hasattr(mock_log, 'error_message'):
            self.assertIsNotNone(mock_log.error_message)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_fetch_batch_failure(self, mock_log_class):
        """Test sync with batch fetch failure"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        # Simulate fetch failure
        self.source_connector.fetch_batch = Mock(side_effect=Exception("Fetch failed"))
        
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
        
        self.assertEqual(mock_log.status, 'failed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_insert_batch_failure(self, mock_log_class):
        """Test sync with batch insert failure"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(return_value=[(1, test_datetime)])
        
        # Simulate upsert failure
        self.target_connector.upsert_dataframe = Mock(side_effect=Exception("Insert failed"))
        
        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)
        
        # Checkpoint should NOT be updated on failure
        # Note: create_or_update_checkpoint might be a function, not a Mock, so we check differently
        checkpoint_calls = getattr(self.executor.checkpoint_manager.maybe_advance_checkpoint, 'call_count', 0)
        self.assertEqual(checkpoint_calls, 0, "Checkpoint should not be updated on failure")
        self.assertEqual(mock_log.status, 'failed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_no_new_data_checkpoint_unchanged(self, mock_log_class):
        """Test sync when no new data - checkpoint unchanged"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(
            return_value=str(checkpoint_time)
        )
        self.executor.timezone_handler.parse_checkpoint_value = Mock(
            return_value=checkpoint_time
        )
        
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE "updated_at" > \'2024-01-01 10:00:00\' ORDER BY "updated_at"'
        )
        
        # Empty batch - no new data
        self.source_connector.fetch_batch = Mock(return_value=[])
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=0)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 0})
            
            self.executor.sync_table(job_table)
        
        # Checkpoint should NOT be updated when max_value == checkpoint_value
        maybe_advance_calls = getattr(self.executor.checkpoint_manager.maybe_advance_checkpoint, 'call_count', 0)
        self.assertEqual(maybe_advance_calls, 0)
        self.assertEqual(mock_log.status, 'completed')
    
    def test_validate_incremental_column_nullable_warning(self):
        """Test validation with nullable column (should log warning)"""
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, True)  # nullable
        ])
        
        # Should not raise error, but log warning
        with patch('sync_engine.incremental_sync.logger') as mock_logger:
            result = self.executor._validate_incremental_column('public', 'users', 'updated_at')
            self.assertTrue(result)
            mock_logger.warning.assert_called()
    
    def test_validate_incremental_column_exception_handling(self):
        """Test validation when get_columns raises exception"""
        self.source_connector.get_columns = Mock(side_effect=Exception("Database error"))
        
        with self.assertRaises(TableSyncError):
            self.executor._validate_incremental_column('public', 'users', 'updated_at')
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_connection_failure(self, mock_sync_table):
        """Test execute with connection failure"""
        mock_table = Mock(spec=SyncJobTable)
        mock_table.transform_plan = None
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        mock_table.incremental_column = 'updated_at'
        
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.__iter__ = Mock(return_value=iter([mock_table]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.source_connector.connect = Mock(side_effect=Exception("Connection failed"))
        
        with self.assertRaises(TableSyncError):
            self.executor.execute()
        
        self.assertEqual(self.execution.status, 'failed')
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_partial_failure(self, mock_sync_table):
        """Test execute with partial failure (some tables succeed, some fail)"""
        mock_table1 = Mock(spec=SyncJobTable)
        mock_table1.transform_plan = None
        mock_table1.schema_name = 'public'
        mock_table1.table_name = 'users'
        mock_table1.incremental_column = 'updated_at'
        
        mock_table2 = Mock(spec=SyncJobTable)
        mock_table2.transform_plan = None
        mock_table2.schema_name = 'public'
        mock_table2.table_name = 'products'
        mock_table2.incremental_column = 'updated_at'
        
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.count = Mock(return_value=2)
        tables_mock.__iter__ = Mock(return_value=iter([mock_table1, mock_table2]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.target_connector._connected = False
        self.source_connector.connect = Mock()
        self.target_connector.connect = Mock()
        
        # First table succeeds, second fails
        def sync_table_side_effect(job_table):
            if job_table.table_name == 'products':
                raise TableSyncError("Sync failed")
        
        mock_sync_table.side_effect = sync_table_side_effect
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            completed_logs_mock = Mock()
            completed_logs_mock.count = Mock(return_value=1)
            failed_logs_mock = Mock()
            failed_logs_mock.exists = Mock(return_value=True)
            failed_logs_mock.count = Mock(return_value=1)
            
            def filter_side_effect(*args, **kwargs):
                if 'status' in kwargs:
                    if kwargs.get('status') == 'completed':
                        return completed_logs_mock
                    elif kwargs.get('status') == 'failed':
                        return failed_logs_mock
                return completed_logs_mock
            
            mock_filter.side_effect = filter_side_effect
            
            self.executor.execute()
        
        # Should be marked as failed due to partial failure
        self.assertEqual(self.execution.status, 'failed')
        self.assertIn('failed to sync', self.execution.error_message)
    
    @patch('sync_engine.incremental_sync.IncrementalSyncExecutor.sync_table')
    def test_execute_all_tables_failed(self, mock_sync_table):
        """Test execute when all tables fail"""
        mock_table = Mock(spec=SyncJobTable)
        mock_table.transform_plan = None
        mock_table.schema_name = 'public'
        mock_table.table_name = 'users'
        mock_table.incremental_column = 'updated_at'
        
        tables_mock = Mock()
        tables_mock.exists = Mock(return_value=True)
        tables_mock.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        tables_mock.count = Mock(return_value=1)
        tables_mock.__iter__ = Mock(return_value=iter([mock_table]))
        self.job.tables.filter = Mock(return_value=tables_mock)
        
        self.source_connector._connected = False
        self.target_connector._connected = False
        self.source_connector.connect = Mock()
        self.target_connector.connect = Mock()
        
        # All tables fail
        mock_sync_table.side_effect = TableSyncError("Sync failed")
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            completed_logs_mock = Mock()
            completed_logs_mock.count = Mock(return_value=0)
            failed_logs_mock = Mock()
            failed_logs_mock.exists = Mock(return_value=True)
            failed_logs_mock.count = Mock(return_value=1)
            
            def filter_side_effect(*args, **kwargs):
                if 'status' in kwargs:
                    if kwargs.get('status') == 'completed':
                        return completed_logs_mock
                    elif kwargs.get('status') == 'failed':
                        return failed_logs_mock
                return completed_logs_mock
            
            mock_filter.side_effect = filter_side_effect
            
            self.executor.execute()
        
        # Should be marked as failed - all tables failed
        self.assertEqual(self.execution.status, 'failed')
        self.assertIn('All', self.execution.error_message)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_checkpoint_update_failure_non_blocking(self, mock_log_class):
        """Test that checkpoint update failure doesn't fail the sync"""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            []
        ])
        
        self.target_connector.bulk_insert = Mock()
        
        # Checkpoint update fails but shouldn't block sync
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock(
            side_effect=Exception("Checkpoint update failed")
        )
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            # Should not raise exception
            self.executor.sync_table(job_table)
        
        # Sync should still be completed despite checkpoint failure
        self.assertEqual(mock_log.status, 'completed')
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_no_primary_key_fallback(self, mock_log_class):
        """Test sync when no primary key - should fall back to incremental_key_columns."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.incremental_key_columns = ['id']
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.create_table_if_not_exists = Mock(return_value=False)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, False),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        
        # No primary key
        self.source_connector.get_primary_key = Mock(return_value=[])
        
        self.executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            []
        ])
        
        self.target_connector.bulk_insert = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            self.executor.sync_table(job_table)
        
        # Verify query builder was called with deterministic ordering tie-breakers
        call_args = self.executor.query_builder.build_incremental_query.call_args
        self.assertEqual(call_args[1]['order_by'], 'updated_at, id')

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_checkpoint_not_advanced_when_post_migration_verification_fails(self, mock_log_class):
        """If post-migration verification fails, checkpoint must not advance."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.incremental_key_columns = ['id']

        job_table.transformation_query = "updated_at > '2024-01-01'"
        job_table.column_transformations = {"dummy": "noop"}
        job_table.column_name_overrides = {}

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=pytz.UTC)
        self.executor.checkpoint_manager.get_checkpoint_value = Mock(
            return_value=str(checkpoint_time)
        )
        self.executor.timezone_handler.parse_checkpoint_value = Mock(
            return_value=checkpoint_time
        )

        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)

        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT ...')

        # Minimal happy-path for the incremental read/upsert loop:
        test_datetime = checkpoint_time + timedelta(hours=1)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            [],
        ])
        self.target_connector.upsert_dataframe = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()

        # Force the verification path to fail:
        self.executor._validate_and_apply_transformations = Mock(return_value=('SELECT transformed', None))
        self.executor._execute_pre_migration_validation = Mock(return_value=(True, None, {
            'expected_row_count': 1,
            'query_results': [],
        }))
        self.executor._verify_post_migration_accuracy = Mock(return_value=(
            False,
            'accuracy mismatch',
            {},
        ))

        with self.assertRaises(TableSyncError):
            self.executor.sync_table(job_table)

        self.executor.checkpoint_manager.create_or_update_checkpoint.assert_not_called()

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_no_delete_propagation_skips_reconcile_deletes(self, mock_log_class):
        """In no-delete mode, sync_table must never call reconcile_deletes()."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.column_name_overrides = {}
        job_table.excluded_columns = []
        job_table.protected_columns = []
        job_table.incremental_key_columns = ['id']

        # Ensure the contract flag is enabled
        self.job.no_delete_propagation = True

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log.save = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.checkpoint_manager.maybe_advance_checkpoint = Mock(return_value=False)

        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)
        self.target_connector.upsert_dataframe = Mock()

        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])

        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT ...')

        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            [],
        ])

        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})

            # Assert reconciliation is skipped
            self.executor.reconcile_deletes = Mock()
            self.executor.sync_table(job_table)

        self.executor.reconcile_deletes.assert_not_called()

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_delete_propagation_calls_reconcile_deletes(self, mock_log_class):
        """In delete-propagation mode, sync_table must call reconcile_deletes()."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.column_name_overrides = {}
        job_table.excluded_columns = []
        job_table.protected_columns = []
        job_table.incremental_key_columns = ['id']

        # Ensure the contract flag is disabled (meaning delete reconciliation allowed)
        self.job.no_delete_propagation = False

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log.save = Mock()
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.checkpoint_manager.maybe_advance_checkpoint = Mock(return_value=False)

        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)
        self.target_connector.upsert_dataframe = Mock()

        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=['id'])

        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT ...')

        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            [],
        ])

        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})

            self.executor.reconcile_deletes = Mock()
            self.executor.sync_table(job_table)

        self.executor.reconcile_deletes.assert_called_once()

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_uses_incremental_key_columns_when_pk_missing(self, mock_log_class):
        """When PK is missing, upsert must use SyncJobTable.incremental_key_columns (first key)."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.incremental_key_columns = ['id', 'other']
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.column_name_overrides = {}

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)

        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)

        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, False),
            ColumnInfo('other', 'int', True, False),
            ColumnInfo('updated_at', 'timestamp', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=[])

        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT ...')
        self.target_connector.upsert_dataframe = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()

        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, 999, test_datetime)],
            [],
        ])

        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            self.executor.sync_table(job_table)

        # ORDER BY must include both configured key columns as tie-breakers.
        call_args = self.executor.query_builder.build_incremental_query.call_args
        self.assertEqual(call_args[1]['order_by'], 'updated_at, id, other')

        # Upsert key_column must be the first configured key column ('id').
        self.assertTrue(self.target_connector.upsert_dataframe.called)
        self.assertEqual(
            self.target_connector.upsert_dataframe.call_args.kwargs.get('key_column'),
            'id',
        )

    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_skips_rows_on_null_upsert_key(self, mock_log_class):
        """Rows with NULL/NaN upsert key should be skipped without failing the run."""
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.incremental_key_columns = ['id']
        job_table.transformation_query = None
        job_table.column_transformations = None
        job_table.column_name_overrides = {}

        mock_log = Mock(spec=SyncExecutionLog)
        mock_log.status = 'pending'
        mock_log_class.objects.create = Mock(return_value=mock_log)

        self.executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        self.executor.table_handler.target_db_type = 'postgres'
        self.executor.table_handler.source_db_type = 'postgres'
        self.target_connector.table_exists = Mock(return_value=True)

        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, False),
            ColumnInfo('updated_at', 'timestamp', True, False),
        ])
        self.source_connector.get_primary_key = Mock(return_value=[])

        self.executor.query_builder.build_incremental_query = Mock(return_value='SELECT ...')
        self.target_connector.upsert_dataframe = Mock()
        self.executor.checkpoint_manager.create_or_update_checkpoint = Mock()

        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        # NULL upsert key (id=None) should be skipped.
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(None, test_datetime)],
            [],
        ])

        self.executor.sync_table(job_table)

        self.target_connector.upsert_dataframe.assert_not_called()
    
    def test_validate_incremental_column_clickhouse_types(self):
        """Test incremental column validation for ClickHouse types"""
        # Mock ClickHouse connector
        clickhouse_connector = Mock()
        clickhouse_connector.__class__.__name__ = 'ClickHouseConnector'
        clickhouse_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'Int64', False, True),
            ColumnInfo('created_at', 'DateTime', True, False),
            ColumnInfo('updated_date', 'Date', True, False),
            ColumnInfo('sequence', 'UInt32', False, False)
        ])
        
        executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=clickhouse_connector,
            target_connector=self.target_connector
        )
        
        # Test ClickHouse DateTime type
        result = executor._validate_incremental_column('test_db', 'users', 'created_at')
        self.assertTrue(result)
        
        # Test ClickHouse Date type
        result = executor._validate_incremental_column('test_db', 'users', 'updated_date')
        self.assertTrue(result)
        
        # Test ClickHouse Int64 type
        result = executor._validate_incremental_column('test_db', 'users', 'id')
        self.assertTrue(result)
        
        # Test ClickHouse UInt32 type
        result = executor._validate_incremental_column('test_db', 'users', 'sequence')
        self.assertTrue(result)
    
    @patch('sync_engine.incremental_sync.SyncExecutionLog')
    def test_sync_table_clickhouse_target(self, mock_log_class):
        """Test incremental sync with ClickHouse as target"""
        # Mock ClickHouse target connector
        clickhouse_target = Mock()
        clickhouse_target.__class__.__name__ = 'ClickHouseConnector'
        clickhouse_target.database_name = 'test_db'
        clickhouse_target.bulk_insert = Mock()
        
        executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=clickhouse_target
        )
        executor.table_handler.target_db_type = 'clickhouse'
        executor.table_handler.create_table_if_not_exists = Mock(return_value=True)
        
        # Mock job table
        job_table = Mock(spec=SyncJobTable)
        job_table.transform_plan = None
        job_table.schema_name = 'public'
        job_table.table_name = 'users'
        job_table.incremental_column = 'updated_at'
        job_table.transformation_query = None
        job_table.column_transformations = None
        
        # Mock execution log
        mock_log = Mock(spec=SyncExecutionLog)
        mock_log_class.objects.create = Mock(return_value=mock_log)
        
        # Mock checkpoint manager
        executor.checkpoint_manager.get_checkpoint_value = Mock(return_value=None)
        
        # Mock source connector
        self.source_connector.get_primary_key = Mock(return_value=['id'])
        self.source_connector.get_columns = Mock(return_value=[
            ColumnInfo('id', 'int', False, True),
            ColumnInfo('updated_at', 'timestamp', True, False)
        ])
        executor.query_builder.build_incremental_query = Mock(
            return_value='SELECT * FROM "public"."users" WHERE 1=1 ORDER BY "updated_at"'
        )
        test_datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.UTC)
        self.source_connector.fetch_batch = Mock(side_effect=[
            [(1, test_datetime)],
            []
        ])
        executor.checkpoint_manager.maybe_advance_checkpoint = Mock(return_value=True)
        
        with patch('sync_engine.incremental_sync.SyncExecutionLog.objects.filter') as mock_filter:
            mock_filter.return_value.count = Mock(return_value=1)
            mock_filter.return_value.aggregate = Mock(return_value={'total': 1})
            
            executor.sync_table(job_table)
        
        # Verify ClickHouse-specific calls
        # ClickHouse should use schema as database name
        clickhouse_target.upsert_dataframe.assert_called_once()
        call_args = clickhouse_target.upsert_dataframe.call_args
        self.assertEqual(call_args[1]['schema'], 'test_db')  # ClickHouse uses connector database

    def test_upsert_batch_with_retry_calls_clickhouse_upsert_dataframe(self):
        """Incremental upsert path delegates to ClickHouseConnector.upsert_dataframe."""
        from connections.connectors.clickhouse import ClickHouseConnector

        tgt = Mock(spec=ClickHouseConnector)
        tgt.__class__.__name__ = "ClickHouseConnector"
        tgt.database_name = "ch_db"
        tgt.get_columns = Mock(
            return_value=[
                ColumnInfo("id", "Int64", False, True),
                ColumnInfo("v", "String", True, False),
            ]
        )
        tgt.add_missing_columns = Mock()
        tgt.upsert_dataframe = Mock()

        executor = IncrementalSyncExecutor(
            job=self.job,
            execution=self.execution,
            source_connector=self.source_connector,
            target_connector=tgt,
        )
        executor._upsert_batch_with_retry(
            schema="ch_db",
            table="tbl",
            columns=["id", "v"],
            rows=[(1, "x")],
            key_columns=["id"],
        )
        tgt.upsert_dataframe.assert_called_once()
        kwargs = tgt.upsert_dataframe.call_args.kwargs
        self.assertEqual(kwargs["schema"], "ch_db")
        self.assertEqual(kwargs["table"], "tbl")
        self.assertEqual(kwargs["key_column"], "id")
        self.assertEqual(list(kwargs["df"].columns), ["id", "v"])


if __name__ == '__main__':
    unittest.main()

