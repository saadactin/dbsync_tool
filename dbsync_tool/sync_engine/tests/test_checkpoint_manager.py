"""
Tests for checkpoint manager
"""
from django.test import TestCase
from django.contrib.auth.models import User
from sync_jobs.models import SyncJob, SyncCheckpoint
from connections.models import DatabaseConnection
from sync_engine.checkpoint_manager import CheckpointManager
from sync_engine.exceptions import CheckpointError
from django.utils import timezone

class CheckpointManagerTestCase(TestCase):
    """Test cases for CheckpointManager"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='encrypted_password',
            database_name='test_db',
            created_by=self.user
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='encrypted_password',
            database_name='test_db',
            created_by=self.user
        )
        
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            created_by=self.user
        )
        
        self.manager = CheckpointManager(self.job)
    
    def test_get_checkpoint_not_exists(self):
        """Test getting non-existent checkpoint"""
        checkpoint = self.manager.get_checkpoint('public', 'test_table')
        self.assertIsNone(checkpoint)
    
    def test_create_checkpoint(self):
        """Test creating a new checkpoint"""
        checkpoint = self.manager.create_or_update_checkpoint(
            'public', 'test_table', '2024-01-01 00:00:00'
        )
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.last_value, '2024-01-01 00:00:00')
        self.assertEqual(checkpoint.schema_name, 'public')
        self.assertEqual(checkpoint.table_name, 'test_table')
    
    def test_update_checkpoint(self):
        """Test updating existing checkpoint"""
        # Create checkpoint
        self.manager.create_or_update_checkpoint(
            'public', 'test_table', '2024-01-01 00:00:00'
        )
        
        # Update checkpoint
        checkpoint = self.manager.create_or_update_checkpoint(
            'public', 'test_table', '2024-01-02 00:00:00'
        )
        self.assertEqual(checkpoint.last_value, '2024-01-02 00:00:00')
        
        # Verify only one checkpoint exists
        count = SyncCheckpoint.objects.filter(
            job=self.job,
            schema_name='public',
            table_name='test_table'
        ).count()
        self.assertEqual(count, 1)
    
    def test_get_checkpoint_value(self):
        """Test getting checkpoint value"""
        self.manager.create_or_update_checkpoint(
            'public', 'test_table', '2024-01-01 00:00:00'
        )
        
        value = self.manager.get_checkpoint_value('public', 'test_table')
        self.assertEqual(value, '2024-01-01 00:00:00')
        
        # Test non-existent checkpoint
        value = self.manager.get_checkpoint_value('public', 'nonexistent')
        self.assertIsNone(value)
    
    def test_delete_checkpoint(self):
        """Test deleting checkpoint"""
        self.manager.create_or_update_checkpoint(
            'public', 'test_table', '2024-01-01 00:00:00'
        )
        
        deleted = self.manager.delete_checkpoint('public', 'test_table')
        self.assertTrue(deleted)
        
        # Verify deleted
        checkpoint = self.manager.get_checkpoint('public', 'test_table')
        self.assertIsNone(checkpoint)
        
        # Test deleting non-existent checkpoint
        deleted = self.manager.delete_checkpoint('public', 'nonexistent')
        self.assertFalse(deleted)
    
    def test_reset_all_checkpoints(self):
        """Test resetting all checkpoints"""
        # Create multiple checkpoints
        self.manager.create_or_update_checkpoint('public', 'table1', 'value1')
        self.manager.create_or_update_checkpoint('public', 'table2', 'value2')
        self.manager.create_or_update_checkpoint('public', 'table3', 'value3')
        
        count = self.manager.reset_all_checkpoints()
        self.assertEqual(count, 3)
        
        # Verify all deleted
        all_checkpoints = self.manager.get_all_checkpoints()
        self.assertEqual(len(all_checkpoints), 0)
    
    def test_get_all_checkpoints(self):
        """Test getting all checkpoints"""
        self.manager.create_or_update_checkpoint('public', 'table1', 'value1')
        self.manager.create_or_update_checkpoint('public', 'table2', 'value2')
        
        all_checkpoints = self.manager.get_all_checkpoints()
        self.assertEqual(len(all_checkpoints), 2)
    
    def test_invalid_inputs(self):
        """Test error handling for invalid inputs"""
        # Test None schema_name
        with self.assertRaises(ValueError):
            self.manager.get_checkpoint(None, 'table')
        
        # Test empty table_name
        with self.assertRaises(ValueError):
            self.manager.create_or_update_checkpoint('public', '', 'value')
    
    def test_none_value_checkpoint(self):
        """Test checkpoint with None value"""
        checkpoint = self.manager.create_or_update_checkpoint(
            'public', 'test_table', None
        )
        self.assertIsNone(checkpoint.last_value)
    
    def test_init_with_none_job(self):
        """Test initialization with None job"""
        with self.assertRaises(ValueError):
            CheckpointManager(None)

    def test_maybe_advance_checkpoint_skips_when_did_advance_false(self):
        """Checkpoint should not be created/updated when did_advance=False."""
        did = self.manager.maybe_advance_checkpoint(
            'public',
            'test_table',
            did_advance=False,
            value='2024-01-01 00:00:00',
        )
        self.assertFalse(did)
        self.assertEqual(
            SyncCheckpoint.objects.filter(job=self.job, schema_name='public', table_name='test_table').count(),
            0,
        )

    def test_maybe_advance_checkpoint_advances_when_did_advance_true(self):
        """Checkpoint should be created/updated when did_advance=True."""
        did = self.manager.maybe_advance_checkpoint(
            'public',
            'test_table',
            did_advance=True,
            value='2024-01-01 00:00:00',
        )
        self.assertTrue(did)
        checkpoint = self.manager.get_checkpoint('public', 'test_table')
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.last_value, '2024-01-01 00:00:00')

        # Second advance should update (not create a second row)
        did2 = self.manager.maybe_advance_checkpoint(
            'public',
            'test_table',
            did_advance=True,
            value='2024-01-02 00:00:00',
        )
        self.assertTrue(did2)
        checkpoint = self.manager.get_checkpoint('public', 'test_table')
        self.assertEqual(checkpoint.last_value, '2024-01-02 00:00:00')
        count = SyncCheckpoint.objects.filter(
            job=self.job,
            schema_name='public',
            table_name='test_table',
        ).count()
        self.assertEqual(count, 1)

    def test_maybe_advance_checkpoint_monotonic_skip_keeps_previous_value(self):
        """If did_advance=False after an existing checkpoint, value must remain unchanged."""
        self.manager.create_or_update_checkpoint(
            'public',
            'test_table',
            '2024-01-02 00:00:00'
        )
        did = self.manager.maybe_advance_checkpoint(
            'public',
            'test_table',
            did_advance=False,
            value='2024-01-01 00:00:00',
        )
        self.assertFalse(did)
        checkpoint = self.manager.get_checkpoint('public', 'test_table')
        self.assertEqual(checkpoint.last_value, '2024-01-02 00:00:00')

