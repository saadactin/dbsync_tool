"""
Tests for monitoring service
"""
from django.test import TestCase
from core.monitoring import HealthCheckService, PerformanceMonitor


class HealthCheckServiceTestCase(TestCase):
    """Test cases for HealthCheckService"""
    
    def test_check_database(self):
        """Test database health check"""
        result = HealthCheckService.check_database()
        self.assertIn('status', result)
        self.assertIn('message', result)
        # Database should be healthy in tests
        self.assertEqual(result['status'], 'healthy')
    
    def test_get_system_health(self):
        """Test getting system health"""
        health = HealthCheckService.get_system_health()
        self.assertIn('overall_status', health)
        self.assertIn('checks', health)
        self.assertIn('timestamp', health)
        self.assertIn('database', health['checks'])


class PerformanceMonitorTestCase(TestCase):
    """Test cases for PerformanceMonitor"""
    
    def test_get_celery_stats(self):
        """Test getting Celery stats"""
        stats = PerformanceMonitor.get_celery_stats()
        self.assertIsInstance(stats, dict)
    
    def test_get_queue_lengths(self):
        """Test getting queue lengths"""
        queues = PerformanceMonitor.get_queue_lengths()
        self.assertIsInstance(queues, dict)

