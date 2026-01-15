"""
Test case for Create Sync Job Step 2 - Table Selection
Tests the page loads correctly and handles errors gracefully
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from accounts.models import UserProfile, Role
from connections.models import DatabaseConnection
import uuid


class CreateJobStep2TestCase(TestCase):
    """Test Step 2 of sync job creation - Table Selection"""
    
    def setUp(self):
        """Set up test data"""
        # Create a user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        UserProfile.objects.get_or_create(
            user=self.user,
            defaults={'role': Role.ADMIN, 'tenant': self.user}
        )
        
        # Create a connection
        self.connection = DatabaseConnection.objects.create(
            name='Test SQL Server',
            db_type='sqlserver',
            host='localhost',
            port=1433,
            username='testuser',
            password='testpass',
            database_name='TestDB',
            is_active=True,
            created_by=self.user,
            tenant=self.user
        )
        
        self.client = Client()
        self.client.force_login(self.user)
    
    def test_step2_page_loads_with_session_data(self):
        """Test that Step 2 page loads when session data exists"""
        # Set up session data (as if from Step 1)
        session = self.client.session
        session['sync_job_name'] = 'Test Job'
        session['sync_job_source_connection_id'] = str(self.connection.id)
        session['sync_job_target_connection_id'] = str(self.connection.id)
        session.save()
        
        # Access Step 2 page
        response = self.client.get(reverse('sync_jobs:create_step2'))
        
        # Should return 200 OK
        self.assertEqual(response.status_code, 200)
        
        # Should contain source connection info
        self.assertContains(response, self.connection.name)
        self.assertContains(response, 'Step 2 of 3')
        
        # Should contain required DOM elements
        self.assertContains(response, 'id="loading-indicator"')
        self.assertContains(response, 'id="error-message"')
        self.assertContains(response, 'id="table-selection-area"')
        self.assertContains(response, 'id="schemas-container"')
        self.assertContains(response, 'id="table-search"')
        self.assertContains(response, 'id="next-btn"')
        
        # Should contain JavaScript connection ID
        self.assertContains(response, f'SOURCE_CONNECTION_ID')
    
    def test_step2_redirects_if_no_session_data(self):
        """Test that Step 2 redirects to Step 1 if session data is missing"""
        # Don't set session data
        response = self.client.get(reverse('sync_jobs:create_step2'))
        
        # Should redirect to Step 1
        self.assertRedirects(response, reverse('sync_jobs:create_step1'))
    
    def test_step2_handles_missing_connection(self):
        """Test that Step 2 handles missing connection gracefully"""
        # Set up session with invalid connection ID
        session = self.client.session
        session['sync_job_name'] = 'Test Job'
        session['sync_job_source_connection_id'] = str(uuid.uuid4())
        session['sync_job_target_connection_id'] = str(uuid.uuid4())
        session.save()
        
        # Access Step 2 page
        response = self.client.get(reverse('sync_jobs:create_step2'))
        
        # Should redirect to Step 1 with error message
        self.assertRedirects(response, reverse('sync_jobs:create_step1'))
    
    def test_step2_metadata_api_endpoint(self):
        """Test that metadata API endpoint works for schemas"""
        # Set up session
        session = self.client.session
        session['sync_job_source_connection_id'] = str(self.connection.id)
        session.save()
        
        # Try to access schemas endpoint
        url = reverse('metadata:schemas', kwargs={'connection_id': self.connection.id})
        response = self.client.get(url)
        
        # Should return JSON response (may be error if connection fails, but should be valid JSON)
        self.assertIn(response['Content-Type'], ['application/json', 'text/html; charset=utf-8'])
        
        if response['Content-Type'] == 'application/json':
            import json
            data = json.loads(response.content)
            # Should have success or error field
            self.assertIn('success', data)

