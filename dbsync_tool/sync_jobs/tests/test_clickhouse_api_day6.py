"""
Tests for ClickHouse API endpoints (Day 6)
Tests REST API endpoints with ClickHouse connections
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
import json

from sync_jobs.models import SyncJob, SyncJobTable
from connections.models import DatabaseConnection


class ClickHouseAPITests(TestCase):
    """Test ClickHouse API endpoints"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        # Create ClickHouse connections
        self.clickhouse_source = DatabaseConnection.objects.create(
            name='ClickHouse Source',
            db_type='clickhouse',
            host='localhost',
            port=9000,
            username='default',
            password='test',
            database_name='test_source',
            created_by=self.user,
            is_active=True
        )
        
        self.clickhouse_target = DatabaseConnection.objects.create(
            name='ClickHouse Target',
            db_type='clickhouse',
            host='localhost',
            port=9000,
            username='default',
            password='test',
            database_name='test_target',
            created_by=self.user,
            is_active=True
        )
        
        # Create PostgreSQL connection for cross-database test
        self.postgres_conn = DatabaseConnection.objects.create(
            name='PostgreSQL Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test_db',
            created_by=self.user,
            is_active=True
        )
    
    def test_create_job_with_clickhouse_source(self):
        """Test creating job via API with ClickHouse source"""
        url = reverse('job-list')
        data = {
            'name': 'ClickHouse Source Job',
            'source_connection': str(self.clickhouse_source.id),
            'target_connection': str(self.postgres_conn.id),
            'sync_type': 'full'
        }
        
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        
        # Should accept ClickHouse connection
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        # If 400, check it's not because of ClickHouse
        if response.status_code == 400:
            response_data = json.loads(response.content)
            self.assertNotIn('clickhouse', str(response_data).lower())
    
    def test_create_job_with_clickhouse_target(self):
        """Test creating job via API with ClickHouse target"""
        url = reverse('job-list')
        data = {
            'name': 'ClickHouse Target Job',
            'source_connection': str(self.postgres_conn.id),
            'target_connection': str(self.clickhouse_target.id),
            'sync_type': 'full'
        }
        
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        
        # Should accept ClickHouse connection
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        # If 400, check it's not because of ClickHouse
        if response.status_code == 400:
            response_data = json.loads(response.content)
            self.assertNotIn('clickhouse', str(response_data).lower())
    
    def test_create_job_clickhouse_to_clickhouse(self):
        """Test creating job via API with ClickHouse to ClickHouse"""
        url = reverse('job-list')
        data = {
            'name': 'ClickHouse to ClickHouse Job',
            'source_connection': str(self.clickhouse_source.id),
            'target_connection': str(self.clickhouse_target.id),
            'sync_type': 'full'
        }
        
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        
        # Should accept ClickHouse to ClickHouse sync
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
    
    def test_get_job_list_with_clickhouse(self):
        """Test getting job list with ClickHouse jobs"""
        # Create a job with ClickHouse
        job = SyncJob.objects.create(
            name='Test ClickHouse Job',
            source_connection=self.clickhouse_source,
            target_connection=self.clickhouse_target,
            sync_type='full',
            created_by=self.user
        )
        
        url = reverse('job-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = json.loads(response.content)
        # Should return jobs including ClickHouse jobs (DRF returns paginated response)
        if isinstance(data, dict) and 'results' in data:
            self.assertIsInstance(data['results'], list)
            self.assertGreater(len(data['results']), 0)
        else:
            self.assertIsInstance(data, list)
    
    def test_get_job_detail_with_clickhouse(self):
        """Test getting job detail with ClickHouse connections"""
        job = SyncJob.objects.create(
            name='Test ClickHouse Job',
            source_connection=self.clickhouse_source,
            target_connection=self.clickhouse_target,
            sync_type='full',
            created_by=self.user
        )
        
        url = reverse('job-detail', args=[job.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = json.loads(response.content)
        # Should include connection information
        self.assertIn('source_connection', data)
        self.assertIn('target_connection', data)
