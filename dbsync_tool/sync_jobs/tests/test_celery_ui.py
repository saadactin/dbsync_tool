"""
UI tests for Celery integration
Tests the Run Now button, task status API, and error handling
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from sync_jobs.models import SyncJob, SyncExecution
from connections.models import DatabaseConnection
from unittest.mock import patch, MagicMock
import json


class CeleryUITestCase(TestCase):
    """Test cases for Celery UI integration"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user
        )
        
        self.job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='pending',
            created_by=self.user
        )
    
    def test_job_run_now_triggers_celery_task(self):
        """Test Run Now button triggers Celery task"""
        self.client.login(username='testuser', password='testpass123')
        
        with patch('scheduler.tasks.execute_sync_job.delay') as mock_delay:
            mock_task = MagicMock()
            mock_task.id = 'test-task-id-123'
            mock_delay.return_value = mock_task
            
            response = self.client.post(
                reverse('sync_jobs:job_run_now', args=[self.job.id]),
                follow=True
            )
            
            self.assertEqual(response.status_code, 200)
            mock_delay.assert_called_once_with(str(self.job.id))
    
    def test_job_run_now_displays_task_id(self):
        """Test Run Now displays task ID in success message"""
        self.client.login(username='testuser', password='testpass123')
        
        with patch('scheduler.tasks.execute_sync_job.delay') as mock_delay:
            mock_task = MagicMock()
            mock_task.id = 'test-task-id-456'
            mock_delay.return_value = mock_task
            
            response = self.client.post(
                reverse('sync_jobs:job_run_now', args=[self.job.id]),
                follow=True
            )
            
            self.assertEqual(response.status_code, 200)
            messages = list(response.context['messages'])
            self.assertTrue(any('test-task-id-456' in str(m) for m in messages))
    
    def test_job_run_now_running_job_fails(self):
        """Test Run Now fails when job is already running"""
        self.client.login(username='testuser', password='testpass123')
        
        self.job.status = 'running'
        self.job.save()
        
        response = self.client.post(
            reverse('sync_jobs:job_run_now', args=[self.job.id]),
            follow=True
        )
        
        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any('already running' in str(m).lower() for m in messages))
    
    def test_job_run_now_paused_job_fails(self):
        """Test Run Now fails when job is paused"""
        self.client.login(username='testuser', password='testpass123')
        
        self.job.status = 'paused'
        self.job.save()
        
        response = self.client.post(
            reverse('sync_jobs:job_run_now', args=[self.job.id]),
            follow=True
        )
        
        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any('paused' in str(m).lower() for m in messages))
    
    def test_task_status_api_endpoint(self):
        """Test task status API endpoint"""
        self.client.login(username='testuser', password='testpass123')
        
        from celery.result import AsyncResult
        from unittest.mock import patch
        
        task_id = 'test-task-id-789'
        
        with patch('scheduler.views.AsyncResult') as mock_async_result:
            mock_result = MagicMock()
            mock_result.status = 'SUCCESS'
            mock_result.ready.return_value = True
            mock_result.result = {'status': 'completed', 'job_id': str(self.job.id)}
            mock_result.failed.return_value = False
            mock_async_result.return_value = mock_result
            
            response = self.client.get(
                reverse('scheduler:task_status', args=[task_id])
            )
            
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(data['task_id'], task_id)
            self.assertEqual(data['status'], 'SUCCESS')
            self.assertTrue(data['ready'])
    
    def test_task_status_api_endpoint_failed_task(self):
        """Test task status API endpoint with failed task"""
        self.client.login(username='testuser', password='testpass123')
        
        from celery.result import AsyncResult
        from unittest.mock import patch
        
        task_id = 'test-task-id-failed'
        
        with patch('scheduler.views.AsyncResult') as mock_async_result:
            mock_result = MagicMock()
            mock_result.status = 'FAILURE'
            mock_result.ready.return_value = True
            mock_result.result = None
            mock_result.failed.return_value = True
            mock_result.info = 'Task failed: Connection error'
            mock_result.traceback = None
            mock_async_result.return_value = mock_result
            
            response = self.client.get(
                reverse('scheduler:task_status', args=[task_id])
            )
            
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(data['task_id'], task_id)
            self.assertEqual(data['status'], 'FAILURE')
            self.assertIn('error', data)
            self.assertIn('Connection error', data['error'])
    
    def test_task_status_api_endpoint_unauthorized(self):
        """Test task status API requires authentication"""
        task_id = 'test-task-id-unauth'
        
        response = self.client.get(
            reverse('scheduler:task_status', args=[task_id])
        )
        
        # Should redirect to login
        self.assertIn(response.status_code, [302, 403])

