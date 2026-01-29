"""
Tests for Anomaly Detection API endpoints
"""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from sync_jobs.models import SyncJob, AnomalyAlert
from connections.models import DatabaseConnection


class AnomalyAPITestCase(TestCase):
    """Test cases for anomaly detection API endpoints"""
    
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        
        # Create user profile (required for tenant service)
        from accounts.models import UserProfile
        UserProfile.objects.create(
            user=self.user,
            role='admin'
        )
        
        self.client.force_authenticate(user=self.user)
        
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
    
    def test_get_anomalies_endpoint(self):
        """Test GET /api/jobs/anomalies/"""
        # Create an anomaly
        AnomalyAlert.objects.create(
            job=self.job,
            tenant=self.user,
            anomaly_type='duration_spike',
            severity='critical',
            description='Test anomaly',
            is_acknowledged=False
        )
        
        response = self.client.get('/api/jobs/anomalies/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('results', response.data)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_get_anomaly_stats_endpoint(self):
        """Test GET /api/jobs/anomalies/stats/"""
        # Create anomalies
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
        
        response = self.client.get('/api/jobs/anomalies/stats/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('total', response.data)
        self.assertIn('critical', response.data)
        self.assertIn('warning', response.data)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['critical'], 1)
        self.assertEqual(response.data['warning'], 1)
    
    def test_acknowledge_anomaly_endpoint(self):
        """Test POST /api/jobs/anomalies/acknowledge/"""
        alert = AnomalyAlert.objects.create(
            job=self.job,
            tenant=self.user,
            anomaly_type='duration_spike',
            severity='critical',
            description='Test anomaly',
            is_acknowledged=False
        )
        
        response = self.client.post(
            '/api/jobs/anomalies/acknowledge/',
            {'anomaly_id': str(alert.id)},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_acknowledged'])
        
        # Verify in database
        alert.refresh_from_db()
        self.assertTrue(alert.is_acknowledged)
        self.assertIsNotNone(alert.acknowledged_at)
    
    def test_acknowledge_anomaly_not_found(self):
        """Test acknowledging non-existent anomaly"""
        response = self.client.post(
            '/api/jobs/anomalies/acknowledge/',
            {'anomaly_id': '00000000-0000-0000-0000-000000000000'},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_anomalies_endpoint_requires_authentication(self):
        """Test that anomalies endpoint requires authentication"""
        self.client.logout()
        
        response = self.client.get('/api/jobs/anomalies/')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
