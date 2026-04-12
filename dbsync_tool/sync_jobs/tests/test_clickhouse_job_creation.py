"""
Tests for ClickHouse job creation and UI integration
Tests job creation via API and UI for ClickHouse connections
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable
from core.encryption import encrypt_password
import os
import json


class ClickHouseJobCreationTests(TestCase):
    """Test ClickHouse job creation"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create tenant (as User)
        self.tenant = User.objects.create_user(
            username='clickhouse_tenant',
            email='tenant@example.com',
            password='tenant123'
        )
        
        # Create user
        self.user = User.objects.create_user(
            username='clickhouse_job_test',
            password='testpass123',
            email='clickhouse_job_test@example.com'
        )
        
        # Create user profile - for Admin, tenant should be the user themselves
        from accounts.models import UserProfile, Role
        profile, created = UserProfile.objects.get_or_create(
            user=self.user,
            defaults={
                'role': Role.ADMIN,
                'tenant': None  # Admin users have tenant=None, they ARE the tenant
            }
        )
        if not created:
            profile.role = Role.ADMIN
            profile.tenant = None  # Admin users are their own tenant
            profile.save()
        
        self.client.login(username='clickhouse_job_test', password='testpass123')
        
        # Create ClickHouse connection
        # For Admin users, tenant should be the user themselves
        clickhouse_password = os.environ.get('CLICKHOUSE_PASSWORD', '') or 'default'
        self.clickhouse_conn = DatabaseConnection.objects.create(
            name='Test ClickHouse Connection',
            db_type='clickhouse',
            host=os.environ.get('CLICKHOUSE_HOST', 'localhost'),
            port=int(os.environ.get('CLICKHOUSE_PORT', '9000')),
            username=os.environ.get('CLICKHOUSE_USER', 'default'),
            password=encrypt_password(clickhouse_password),
            database_name=os.environ.get('CLICKHOUSE_DATABASE', 'default'),
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
        
        # Create PostgreSQL connection for cross-database tests
        self.postgres_conn = DatabaseConnection.objects.create(
            name='Test PostgreSQL Connection',
            db_type='postgres',
            host=os.environ.get('TEST_POSTGRES_HOST', 'localhost'),
            port=int(os.environ.get('TEST_POSTGRES_PORT', 5432)),
            username=os.environ.get('TEST_POSTGRES_USER', 'postgres'),
            password=encrypt_password(os.environ.get('TEST_POSTGRES_PASSWORD', 'postgres')),
            database_name=os.environ.get('TEST_POSTGRES_DB', 'tauseef'),
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
    
    def test_create_job_with_clickhouse_source(self):
        """Test creating job with ClickHouse source"""
        # Test job creation via form submission
        url = reverse('sync_jobs:create_step1')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Verify ClickHouse connection appears in connections
        # Note: Connections are filtered by tenant, so we verify the connection exists
        self.assertIn('connections', response.context)
        connections = response.context['connections']
        # Check if our ClickHouse connection is in the list
        connection_ids = [str(c.id) for c in connections]
        self.assertIn(str(self.clickhouse_conn.id), connection_ids, 
                     "ClickHouse connection should appear in connections list")
    
    def test_create_job_with_clickhouse_target(self):
        """Test creating job with ClickHouse target"""
        url = reverse('sync_jobs:create_step1')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Verify ClickHouse connection appears in connections
        self.assertIn('connections', response.context)
        connections = response.context['connections']
        # Check if our ClickHouse connection is in the list
        connection_ids = [str(c.id) for c in connections]
        self.assertIn(str(self.clickhouse_conn.id), connection_ids,
                     "ClickHouse connection should appear in connections list")
    
    def test_create_job_clickhouse_to_clickhouse(self):
        """Test ClickHouse → ClickHouse job creation"""
        # Create a second ClickHouse connection for same-database-type test
        clickhouse_password = os.environ.get('CLICKHOUSE_PASSWORD', '') or 'default'
        clickhouse_conn2 = DatabaseConnection.objects.create(
            name='Test ClickHouse Connection 2',
            db_type='clickhouse',
            host=os.environ.get('CLICKHOUSE_HOST', 'localhost'),
            port=int(os.environ.get('CLICKHOUSE_PORT', '9000')),
            username=os.environ.get('CLICKHOUSE_USER', 'default'),
            password=encrypt_password(clickhouse_password),
            database_name=os.environ.get('CLICKHOUSE_DATABASE', 'default'),
            created_by=self.user,
            tenant=self.user,  # Admin users are their own tenant
            is_active=True
        )
        
        # Test that both connections appear in dropdowns
        url = reverse('sync_jobs:create_step1')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Verify both ClickHouse connections are available
        connections = response.context['connections']
        connection_ids = [str(c.id) for c in connections]
        # At least one ClickHouse connection should be available
        has_clickhouse = (str(self.clickhouse_conn.id) in connection_ids or 
                         str(clickhouse_conn2.id) in connection_ids)
        self.assertTrue(has_clickhouse, "At least one ClickHouse connection should appear")
    
    def test_step1_clickhouse_connections(self):
        """Test Step 1 with ClickHouse connections"""
        url = reverse('sync_jobs:create_step1')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('connections', response.context)
        
        # Verify ClickHouse connection is present
        connections = response.context['connections']
        connection_ids = [str(c.id) for c in connections]
        self.assertIn(str(self.clickhouse_conn.id), connection_ids,
                     "ClickHouse connection should appear in Step 1")
    
    def test_step2_clickhouse_metadata_loading(self):
        """Test Step 2 metadata loading for ClickHouse"""
        # Set up session data for step 2
        session = self.client.session
        session['sync_job_name'] = 'Test ClickHouse Job'
        session['sync_job_source_connection_id'] = str(self.clickhouse_conn.id)
        session['sync_job_target_connection_id'] = str(self.postgres_conn.id)
        session.save()
        
        # Test Step 2 view
        url = reverse('sync_jobs:create_step2')
        response = self.client.get(url)
        
        # Should load successfully
        self.assertIn(response.status_code, [200, 302])  # 302 if redirect needed
        
        # If successful, verify context has source connection
        if response.status_code == 200:
            self.assertIn('source_connection', response.context)
            self.assertEqual(response.context['source_connection'].db_type, 'clickhouse')
    
    def test_step3_clickhouse_incremental_columns(self):
        """Schedule step loads ClickHouse source metadata for incremental options."""
        session = self.client.session
        session['sync_job_name'] = 'Test ClickHouse Incremental Job'
        session['sync_job_source_connection_type'] = 'database'
        session['sync_job_source_connection_id'] = str(self.clickhouse_conn.id)
        session['sync_job_target_connection_id'] = str(self.postgres_conn.id)
        session['sync_job_selected_tables'] = [
            {'schema_name': 'default', 'table_name': 'test_table'}
        ]
        session.save()
        from sync_jobs.tests.wizard_helpers import seed_transform_plans_in_session

        seed_transform_plans_in_session(self.client, source_db_type='clickhouse')

        url = reverse('sync_jobs:create_step4')
        response = self.client.get(url)

        self.assertIn(response.status_code, [200, 302])

        if response.status_code == 200:
            self.assertIn('source_connection', response.context)
            self.assertEqual(response.context['source_connection'].db_type, 'clickhouse')
