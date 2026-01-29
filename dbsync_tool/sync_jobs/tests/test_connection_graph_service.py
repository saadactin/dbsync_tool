"""
Tests for ConnectionGraphService
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution
from sync_jobs.services import ConnectionGraphService
from connections.models import DatabaseConnection


class ConnectionGraphServiceTestCase(TestCase):
    """Test cases for ConnectionGraphService"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create user profile (required for tenant service)
        from accounts.models import UserProfile
        UserProfile.objects.create(
            user=self.user,
            role='admin'
        )
        
        # Create connections
        self.source_conn = DatabaseConnection.objects.create(
            name='Test Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
        
        self.target_conn = DatabaseConnection.objects.create(
            name='Test Target',
            db_type='mysql',
            host='localhost',
            port=3306,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
        
        self.third_conn = DatabaseConnection.objects.create(
            name='Test Third',
            db_type='sqlserver',
            host='localhost',
            port=1433,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user,
            is_active=True
        )
    
    def test_build_graph_no_connections(self):
        """Test graph building with no connections"""
        # Create another user with no connections
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
            email='other@example.com'
        )
        from accounts.models import UserProfile
        UserProfile.objects.create(user=other_user, role='admin')
        
        graph_data = ConnectionGraphService.build_graph(other_user)
        
        self.assertIn('nodes', graph_data)
        self.assertIn('edges', graph_data)
        self.assertEqual(len(graph_data['nodes']), 0)
        self.assertEqual(len(graph_data['edges']), 0)
    
    def test_build_graph_no_jobs(self):
        """Test graph building with connections but no jobs"""
        graph_data = ConnectionGraphService.build_graph(self.user)
        
        self.assertIn('nodes', graph_data)
        self.assertIn('edges', graph_data)
        self.assertEqual(len(graph_data['nodes']), 3)  # 3 connections
        self.assertEqual(len(graph_data['edges']), 0)  # No jobs
        
        # Check node properties
        node_ids = [node['id'] for node in graph_data['nodes']]
        self.assertIn(str(self.source_conn.id), node_ids)
        self.assertIn(str(self.target_conn.id), node_ids)
        self.assertIn(str(self.third_conn.id), node_ids)
        
        # Check node structure
        for node in graph_data['nodes']:
            self.assertIn('id', node)
            self.assertIn('name', node)
            self.assertIn('type', node)
            self.assertIn('job_count', node)
            self.assertIn('is_active', node)
            self.assertEqual(node['job_count'], 0)
    
    def test_build_graph_with_jobs(self):
        """Test graph building with jobs"""
        # Create jobs
        job1 = SyncJob.objects.create(
            name='Job 1',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        job2 = SyncJob.objects.create(
            name='Job 2',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='incremental',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        job3 = SyncJob.objects.create(
            name='Job 3',
            source_connection=self.target_conn,
            target_connection=self.third_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        graph_data = ConnectionGraphService.build_graph(self.user)
        
        self.assertEqual(len(graph_data['nodes']), 3)
        self.assertEqual(len(graph_data['edges']), 2)  # 2 unique edges
        
        # Check node job counts
        source_node = next(n for n in graph_data['nodes'] if n['id'] == str(self.source_conn.id))
        target_node = next(n for n in graph_data['nodes'] if n['id'] == str(self.target_conn.id))
        third_node = next(n for n in graph_data['nodes'] if n['id'] == str(self.third_conn.id))
        
        self.assertEqual(source_node['job_count'], 2)  # 2 jobs as source
        self.assertEqual(target_node['job_count'], 3)  # 2 as target, 1 as source
        self.assertEqual(third_node['job_count'], 1)  # 1 as target
        
        # Check edges
        edge1 = next(e for e in graph_data['edges'] 
                    if e['source'] == str(self.source_conn.id) 
                    and e['target'] == str(self.target_conn.id))
        edge2 = next(e for e in graph_data['edges'] 
                    if e['source'] == str(self.target_conn.id) 
                    and e['target'] == str(self.third_conn.id))
        
        self.assertEqual(edge1['job_count'], 2)
        self.assertEqual(len(edge1['jobs']), 2)
        self.assertEqual(edge2['job_count'], 1)
        self.assertEqual(len(edge2['jobs']), 1)
        
        # Check edge structure
        for edge in graph_data['edges']:
            self.assertIn('source', edge)
            self.assertIn('target', edge)
            self.assertIn('jobs', edge)
            self.assertIn('job_count', edge)
            self.assertIn('status', edge)
            self.assertIn('success_rate', edge)
            self.assertIn(edge['status'], ['healthy', 'warning', 'critical'])
    
    def test_build_graph_self_loop_skipped(self):
        """Test that self-loops (source == target) are skipped"""
        job = SyncJob.objects.create(
            name='Self Loop Job',
            source_connection=self.source_conn,
            target_connection=self.source_conn,  # Same connection
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        graph_data = ConnectionGraphService.build_graph(self.user)
        
        # Should have nodes but no edges (self-loop skipped)
        self.assertEqual(len(graph_data['nodes']), 3)
        self.assertEqual(len(graph_data['edges']), 0)
    
    def test_calculate_edge_health_no_executions(self):
        """Test edge health calculation with no executions"""
        jobs = SyncJob.objects.filter(
            source_connection=self.source_conn,
            target_connection=self.target_conn
        )
        
        health_data = ConnectionGraphService._calculate_edge_health(jobs)
        
        self.assertIn('status', health_data)
        self.assertIn('success_rate', health_data)
        self.assertEqual(health_data['status'], 'healthy')
        self.assertEqual(health_data['success_rate'], 100.0)
    
    def test_calculate_edge_health_healthy(self):
        """Test edge health calculation with healthy executions"""
        job = SyncJob.objects.create(
            name='Healthy Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create 10 successful executions
        now = timezone.now()
        for i in range(10):
            SyncExecution.objects.create(
                job=job,
                status='completed',
                started_at=now - timedelta(hours=10-i),
                completed_at=now - timedelta(hours=10-i) + timedelta(seconds=10),
                total_rows_synced=1000
            )
        
        jobs = SyncJob.objects.filter(
            source_connection=self.source_conn,
            target_connection=self.target_conn
        )
        
        health_data = ConnectionGraphService._calculate_edge_health(jobs)
        
        self.assertEqual(health_data['status'], 'healthy')
        self.assertEqual(health_data['success_rate'], 100.0)
    
    def test_calculate_edge_health_warning(self):
        """Test edge health calculation with warning status (50-80% success)"""
        job = SyncJob.objects.create(
            name='Warning Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create 10 executions: 6 successful, 4 failed (60% success rate)
        now = timezone.now()
        for i in range(6):
            SyncExecution.objects.create(
                job=job,
                status='completed',
                started_at=now - timedelta(hours=10-i),
                completed_at=now - timedelta(hours=10-i) + timedelta(seconds=10),
                total_rows_synced=1000
            )
        
        for i in range(4):
            SyncExecution.objects.create(
                job=job,
                status='failed',
                started_at=now - timedelta(hours=4-i),
                error_message='Test error',
                total_rows_synced=0
            )
        
        jobs = SyncJob.objects.filter(
            source_connection=self.source_conn,
            target_connection=self.target_conn
        )
        
        health_data = ConnectionGraphService._calculate_edge_health(jobs)
        
        self.assertEqual(health_data['status'], 'warning')
        self.assertEqual(health_data['success_rate'], 60.0)
    
    def test_calculate_edge_health_critical(self):
        """Test edge health calculation with critical status (<50% success)"""
        job = SyncJob.objects.create(
            name='Critical Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='failed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create 10 executions: 3 successful, 7 failed (30% success rate)
        now = timezone.now()
        for i in range(3):
            SyncExecution.objects.create(
                job=job,
                status='completed',
                started_at=now - timedelta(hours=10-i),
                completed_at=now - timedelta(hours=10-i) + timedelta(seconds=10),
                total_rows_synced=1000
            )
        
        for i in range(7):
            SyncExecution.objects.create(
                job=job,
                status='failed',
                started_at=now - timedelta(hours=7-i),
                error_message='Test error',
                total_rows_synced=0
            )
        
        jobs = SyncJob.objects.filter(
            source_connection=self.source_conn,
            target_connection=self.target_conn
        )
        
        health_data = ConnectionGraphService._calculate_edge_health(jobs)
        
        self.assertEqual(health_data['status'], 'critical')
        self.assertEqual(health_data['success_rate'], 30.0)
    
    def test_build_graph_tenant_isolation(self):
        """Test that graph respects tenant isolation"""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
            email='other@example.com'
        )
        from accounts.models import UserProfile
        UserProfile.objects.create(user=other_user, role='admin')
        
        # Create connection and job for other user
        other_conn = DatabaseConnection.objects.create(
            name='Other Source',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='test',
            password='test',
            database_name='test',
            created_by=other_user,
            tenant=other_user,
            is_active=True
        )
        
        other_job = SyncJob.objects.create(
            name='Other Job',
            source_connection=other_conn,
            target_connection=other_conn,
            sync_type='full',
            status='completed',
            created_by=other_user,
            tenant=other_user
        )
        
        # Build graph for first user
        graph_data = ConnectionGraphService.build_graph(self.user)
        
        # Should not include other user's connections/jobs
        node_ids = [node['id'] for node in graph_data['nodes']]
        self.assertNotIn(str(other_conn.id), node_ids)
        
        # Build graph for other user
        other_graph_data = ConnectionGraphService.build_graph(other_user)
        
        # Should only include other user's connections
        self.assertEqual(len(other_graph_data['nodes']), 1)
        self.assertEqual(other_graph_data['nodes'][0]['id'], str(other_conn.id))
    
    def test_build_graph_inactive_connections_excluded(self):
        """Test that inactive connections are excluded"""
        # Create inactive connection
        inactive_conn = DatabaseConnection.objects.create(
            name='Inactive Connection',
            db_type='clickhouse',
            host='localhost',
            port=9000,
            username='test',
            password='test',
            database_name='test',
            created_by=self.user,
            tenant=self.user,
            is_active=False  # Inactive
        )
        
        graph_data = ConnectionGraphService.build_graph(self.user)
        
        # Should not include inactive connection
        node_ids = [node['id'] for node in graph_data['nodes']]
        self.assertNotIn(str(inactive_conn.id), node_ids)
