"""
Tests for Health Score feature
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from sync_jobs.models import SyncJob, SyncExecution, HealthScoreSnapshot
from sync_jobs.services import HealthScoreService
from connections.models import DatabaseConnection


class HealthScoreServiceTestCase(TestCase):
    """Test cases for HealthScoreService"""
    
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
    
    def test_calculate_score_no_data(self):
        """Test score calculation with no jobs/executions"""
        score_data = HealthScoreService.calculate_score(self.user)
        
        self.assertIn('score', score_data)
        self.assertIn('components', score_data)
        self.assertIsInstance(score_data['score'], int)
        self.assertGreaterEqual(score_data['score'], 0)
        self.assertLessEqual(score_data['score'], 100)
        
        # With no data, should return perfect score (no failures)
        self.assertEqual(score_data['score'], 100)
    
    def test_calculate_score_with_jobs(self):
        """Test score calculation with jobs"""
        # Create a job
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        score_data = HealthScoreService.calculate_score(self.user)
        
        self.assertIn('score', score_data)
        self.assertIn('components', score_data)
        self.assertIn('success_rate', score_data['components'])
        self.assertIn('connection_health', score_data['components'])
        self.assertIn('schedule_adherence', score_data['components'])
        self.assertIn('error_frequency', score_data['components'])
    
    def test_calculate_score_with_executions(self):
        """Test score calculation with executions"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create successful execution
        SyncExecution.objects.create(
            job=job,
            status='completed',
            started_at=timezone.now() - timedelta(days=1),
            completed_at=timezone.now() - timedelta(days=1) + timedelta(minutes=5),
            total_rows_synced=100
        )
        
        # Create failed execution
        SyncExecution.objects.create(
            job=job,
            status='failed',
            started_at=timezone.now() - timedelta(days=2),
            error_message='Test error',
            total_rows_synced=0
        )
        
        score_data = HealthScoreService.calculate_score(self.user)
        
        # Should have 50% success rate (1 success, 1 failure)
        self.assertEqual(score_data['components']['success_rate'], 50.0)
        self.assertGreater(score_data['score'], 0)
        self.assertLessEqual(score_data['score'], 100)
    
    def test_calculate_success_rate(self):
        """Test success rate calculation"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create 3 successful, 1 failed
        for i in range(3):
            SyncExecution.objects.create(
                job=job,
                status='completed',
                started_at=timezone.now() - timedelta(days=i),
                completed_at=timezone.now() - timedelta(days=i) + timedelta(minutes=5),
                total_rows_synced=100
            )
        
        SyncExecution.objects.create(
            job=job,
            status='failed',
            started_at=timezone.now() - timedelta(days=4),
            error_message='Test error'
        )
        
        # Filter jobs by tenant
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, self.user)
        rate = HealthScoreService._calculate_success_rate(user_jobs, self.user)
        
        # 3 out of 4 = 75%
        self.assertEqual(rate, 75.0)
    
    def test_calculate_connection_health(self):
        """Test connection health calculation"""
        # Both connections are active
        connections = DatabaseConnection.objects.filter(tenant=self.user)
        health = HealthScoreService._calculate_connection_health(connections)
        
        self.assertEqual(health, 100.0)  # Both active
        
        # Deactivate one
        self.source_conn.is_active = False
        self.source_conn.save()
        
        connections = DatabaseConnection.objects.filter(tenant=self.user)
        health = HealthScoreService._calculate_connection_health(connections)
        
        self.assertEqual(health, 50.0)  # 1 out of 2 active
    
    def test_calculate_schedule_adherence(self):
        """Test schedule adherence calculation"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # No scheduled jobs = perfect adherence
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, self.user)
        adherence = HealthScoreService._calculate_schedule_adherence(user_jobs, self.user)
        self.assertEqual(adherence, 100.0)
    
    def test_calculate_error_frequency(self):
        """Test error frequency calculation"""
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            sync_type='full',
            status='completed',
            created_by=self.user,
            tenant=self.user
        )
        
        # Create 2 successful, 1 failed
        for i in range(2):
            SyncExecution.objects.create(
                job=job,
                status='completed',
                started_at=timezone.now() - timedelta(days=i),
                completed_at=timezone.now() - timedelta(days=i) + timedelta(minutes=5),
                total_rows_synced=100
            )
        
        SyncExecution.objects.create(
            job=job,
            status='failed',
            started_at=timezone.now() - timedelta(days=3),
            error_message='Test error'
        )
        
        # Filter jobs by tenant
        from accounts.services.tenant_service import TenantService
        all_jobs = SyncJob.objects.all()
        user_jobs = TenantService.get_queryset_for_user(all_jobs, self.user)
        error_freq = HealthScoreService._calculate_error_frequency(user_jobs, self.user)
        
        # 1 failure out of 3 = 33.33% error rate
        # Error frequency score = 100 - 33.33 = 66.67
        self.assertAlmostEqual(error_freq, 66.7, places=1)
    
    def test_get_trend(self):
        """Test trend retrieval"""
        # Create some snapshots
        for i in range(5):
            HealthScoreSnapshot.objects.create(
                tenant=self.user,
                score=80 + i,
                components={
                    'success_rate': 85,
                    'connection_health': 90,
                    'schedule_adherence': 75,
                    'error_frequency': 80
                },
                calculated_at=timezone.now() - timedelta(days=5-i)
            )
        
        trend = HealthScoreService.get_trend(self.user, days=7)
        
        self.assertIsInstance(trend, list)
        self.assertGreater(len(trend), 0)
        self.assertIn('date', trend[0])
        self.assertIn('score', trend[0])
    
    def test_get_trend_direction(self):
        """Test trend direction calculation"""
        # Create improving trend
        for i in range(5):
            HealthScoreSnapshot.objects.create(
                tenant=self.user,
                score=70 + (i * 5),  # Increasing scores
                components={
                    'success_rate': 85,
                    'connection_health': 90,
                    'schedule_adherence': 75,
                    'error_frequency': 80
                },
                calculated_at=timezone.now() - timedelta(days=5-i)
            )
        
        direction = HealthScoreService.get_trend_direction(self.user)
        self.assertEqual(direction, 'improving')
        
        # Clear and create degrading trend
        HealthScoreSnapshot.objects.filter(tenant=self.user).delete()
        
        for i in range(5):
            HealthScoreSnapshot.objects.create(
                tenant=self.user,
                score=90 - (i * 5),  # Decreasing scores
                components={
                    'success_rate': 85,
                    'connection_health': 90,
                    'schedule_adherence': 75,
                    'error_frequency': 80
                },
                calculated_at=timezone.now() - timedelta(days=5-i)
            )
        
        direction = HealthScoreService.get_trend_direction(self.user)
        self.assertEqual(direction, 'degrading')
    
    def test_save_snapshot(self):
        """Test snapshot saving"""
        HealthScoreService.save_snapshot(self.user)
        
        # Should create a snapshot
        self.assertTrue(HealthScoreSnapshot.objects.filter(tenant=self.user).exists())
        
        snapshot = HealthScoreSnapshot.objects.filter(tenant=self.user).latest('calculated_at')
        self.assertIsNotNone(snapshot)
        self.assertIn('score', snapshot.components or {})
        self.assertGreaterEqual(snapshot.score, 0)
        self.assertLessEqual(snapshot.score, 100)
        
        # Save again (should update existing)
        initial_count = HealthScoreSnapshot.objects.filter(tenant=self.user).count()
        HealthScoreService.save_snapshot(self.user)
        final_count = HealthScoreSnapshot.objects.filter(tenant=self.user).count()
        
        # Should still be 1 (updated, not duplicated)
        self.assertEqual(initial_count, final_count)
