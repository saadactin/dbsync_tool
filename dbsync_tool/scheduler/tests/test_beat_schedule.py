"""
Tests for Celery Beat schedule configuration
"""
from django.test import TestCase
from django_celery_beat.models import PeriodicTask, IntervalSchedule
from scheduler.beat_schedule import setup_beat_schedule, verify_beat_schedule, cleanup_beat_schedule
import logging

logger = logging.getLogger(__name__)


class BeatScheduleTestCase(TestCase):
    """Test cases for beat schedule setup"""
    
    def test_setup_beat_schedule_creates_task(self):
        """Test that setup creates periodic task"""
        task, created = setup_beat_schedule()
        
        self.assertIsNotNone(task)
        self.assertTrue(task.enabled)
        self.assertEqual(task.name, 'trigger-scheduled-jobs')
        self.assertEqual(task.task, 'scheduler.tasks.trigger_scheduled_jobs_task')
    
    def test_setup_beat_schedule_idempotent(self):
        """Test that setup is idempotent"""
        task1, created1 = setup_beat_schedule()
        task2, created2 = setup_beat_schedule()
        
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(task1.id, task2.id)
    
    def test_verify_beat_schedule_valid(self):
        """Test verification of valid schedule"""
        setup_beat_schedule()
        is_valid = verify_beat_schedule()
        
        self.assertTrue(is_valid)
    
    def test_verify_beat_schedule_invalid(self):
        """Test verification of invalid schedule (not setup)"""
        is_valid = verify_beat_schedule()
        
        self.assertFalse(is_valid)
    
    def test_cleanup_beat_schedule(self):
        """Test cleanup of beat schedule"""
        setup_beat_schedule()
        deleted_count = cleanup_beat_schedule()
        
        self.assertEqual(deleted_count, 1)
        self.assertFalse(PeriodicTask.objects.filter(name='trigger-scheduled-jobs').exists())

