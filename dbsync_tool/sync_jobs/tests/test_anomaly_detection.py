"""
Tests for AnomalyDetectionService
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, AnomalyAlert
from sync_jobs.services import AnomalyDetectionService
from connections.models import DatabaseConnection


class AnomalyDetectionServiceTestCase(TestCase):
    """Test cases for AnomalyDetectionService"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        
        # Create user profile (required for tenant service)
        from accounts.models import UserProfile
        UserProfile.objects.create(
            user=self.user,
            role='admin'
        )
        
        # Create connections
        self.source_conn = DatabaseConnection.objects.create(
            name='Source DB',
            db_type='postgresql',
            host='localhost',
            port=5432,
            database='test_db',
            username='test_user',
            password='test_pass',
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Target DB',
            db_type='postgresql',
            host='localhost',
            port=5432,
            database='test_db',
            username='test_user',
            password='test_pass',
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
        
        # Create a job
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
    
    def test_detect_duration_anomaly(self):
        """Test duration anomaly detection"""
        now = timezone.now()
        
        # Create normal executions (10 seconds each)
        for i in range(5):
            SyncExecution.objects.create(
                job=self.job,
                status='completed',
                started_at=now - timedelta(minutes=10-i),
                completed_at=now - timedelta(minutes=10-i) + timedelta(seconds=10),
                total_rows_synced=1000
            )
        
        # Create an anomalous execution (50 seconds - 5x normal)
        SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=now - timedelta(minutes=1),
            completed_at=now - timedelta(minutes=1) + timedelta(seconds=50),
            total_rows_synced=1000
        )
        
        anomaly = AnomalyDetectionService._detect_duration_anomaly(self.job)
        
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly['type'], 'duration_spike')
        self.assertEqual(anomaly['severity'], 'critical')  # >3x multiplier
    
    def test_detect_failure_pattern(self):
        """Test failure pattern detection"""
        now = timezone.now()
        
        # Create 3 consecutive failures
        for i in range(3):
            SyncExecution.objects.create(
                job=self.job,
                status='failed',
                started_at=now - timedelta(minutes=3-i),
                error_message='Test error'
            )
        
        anomaly = AnomalyDetectionService._detect_failure_pattern(self.job)
        
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly['type'], 'failure_pattern')
        self.assertEqual(anomaly['severity'], 'critical')
    
    def test_detect_row_count_anomaly(self):
        """Test row count anomaly detection"""
        now = timezone.now()
        
        # Create normal executions (1000 rows each)
        for i in range(5):
            SyncExecution.objects.create(
                job=self.job,
                status='completed',
                started_at=now - timedelta(minutes=10-i),
                completed_at=now - timedelta(minutes=10-i) + timedelta(seconds=10),
                total_rows_synced=1000
            )
        
        # Create an anomalous execution (300 rows - 70% drop)
        SyncExecution.objects.create(
            job=self.job,
            status='completed',
            started_at=now - timedelta(minutes=1),
            completed_at=now - timedelta(minutes=1) + timedelta(seconds=10),
            total_rows_synced=300
        )
        
        anomaly = AnomalyDetectionService._detect_row_count_anomaly(self.job)
        
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly['type'], 'row_count_drop')
        self.assertEqual(anomaly['severity'], 'warning')  # 30-50% drop
    
    def test_detect_connection_timeout(self):
        """Test connection timeout detection"""
        now = timezone.now()
        
        # Create 3 executions with timeout errors
        for i in range(3):
            SyncExecution.objects.create(
                job=self.job,
                status='failed',
                started_at=now - timedelta(hours=2-i),
                error_message='Connection timeout occurred'
            )
        
        anomaly = AnomalyDetectionService._detect_connection_timeout(self.job)
        
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly['type'], 'connection_timeout')
        self.assertEqual(anomaly['severity'], 'critical')
    
    def test_get_active_anomalies(self):
        """Test getting active anomalies"""
        # Create an anomaly alert
        AnomalyAlert.objects.create(
            job=self.job,
            tenant=self.user,
            anomaly_type='duration_spike',
            severity='critical',
            description='Test anomaly',
            is_acknowledged=False
        )
        
        anomalies = AnomalyDetectionService.get_active_anomalies(self.user)
        
        self.assertEqual(anomalies.count(), 1)
        self.assertEqual(anomalies.first().anomaly_type, 'duration_spike')
    
    def test_acknowledge_anomaly(self):
        """Test acknowledging an anomaly"""
        alert = AnomalyAlert.objects.create(
            job=self.job,
            tenant=self.user,
            anomaly_type='duration_spike',
            severity='critical',
            description='Test anomaly',
            is_acknowledged=False
        )
        
        result = AnomalyDetectionService.acknowledge_anomaly(str(alert.id), self.user)
        
        self.assertIsNotNone(result)
        self.assertTrue(result.is_acknowledged)
        self.assertIsNotNone(result.acknowledged_at)
        self.assertEqual(result.acknowledged_by, self.user)
    
    def test_get_anomaly_stats(self):
        """Test getting anomaly statistics"""
        # Create various anomalies
        AnomalyAlert.objects.create(
            job=self.job,
            tenant=self.user,
            anomaly_type='duration_spike',
            severity='critical',
            description='Test 1',
            is_acknowledged=False
        )
        
        AnomalyAlert.objects.create(
            job=self.job,
            tenant=self.user,
            anomaly_type='failure_pattern',
            severity='warning',
            description='Test 2',
            is_acknowledged=True
        )
        
        stats = AnomalyDetectionService.get_anomaly_stats(self.user)
        
        self.assertEqual(stats['total'], 2)
        self.assertEqual(stats['critical'], 1)
        self.assertEqual(stats['warning'], 1)
        self.assertEqual(stats['acknowledged'], 1)
        self.assertEqual(stats['unacknowledged'], 1)
    
    def test_detect_job_anomalies_no_data(self):
        """Test detection with no execution data"""
        # Job with no executions
        new_job = SyncJob.objects.create(
            name='New Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user,
            tenant=self.user
        )
        
        anomalies = AnomalyDetectionService.detect_job_anomalies(new_job, self.user)
        
        # Should return empty list (no data to analyze)
        self.assertEqual(len(anomalies), 0)
