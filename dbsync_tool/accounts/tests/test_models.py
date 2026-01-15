"""
Unit tests for UserProfile model and tenant fields
"""
from django.test import TestCase
from django.contrib.auth.models import User
from accounts.models import UserProfile, Role
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncSchedule


class UserProfileModelTest(TestCase):
    """Test UserProfile model creation and role methods"""
    
    def setUp(self):
        """Set up test users with different roles"""
        self.super_admin = User.objects.create_user(
            username='superadmin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        UserProfile.objects.create(
            user=self.super_admin,
            role=Role.SUPER_ADMIN,
            tenant=None
        )
        
        self.admin = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True,
            is_superuser=False
        )
        UserProfile.objects.create(
            user=self.admin,
            role=Role.ADMIN,
            tenant=self.admin
        )
        
        self.operator = User.objects.create_user(
            username='operator',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.operator,
            role=Role.OPERATOR,
            tenant=self.admin
        )
        
        self.viewer = User.objects.create_user(
            username='viewer',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.viewer,
            role=Role.VIEWER,
            tenant=self.admin
        )
    
    def test_userprofile_auto_created_on_user_creation(self):
        """Test that UserProfile is auto-created when User is created"""
        new_user = User.objects.create_user(
            username='newuser',
            password='testpass123'
        )
        self.assertTrue(hasattr(new_user, 'userprofile'))
        self.assertIsNotNone(new_user.userprofile)
    
    def test_userprofile_default_role_is_viewer(self):
        """Test that default role is VIEWER"""
        new_user = User.objects.create_user(
            username='newuser2',
            password='testpass123'
        )
        # Signal should create profile with default role
        profile = new_user.userprofile
        self.assertEqual(profile.role, Role.VIEWER)
    
    def test_userprofile_str_representation(self):
        """Test __str__ method"""
        profile = self.admin.userprofile
        str_repr = str(profile)
        self.assertIn(self.admin.username, str_repr)
        self.assertIn('Admin', str_repr)
    
    def test_super_admin_has_no_tenant(self):
        """Test that Super Admin has tenant=None"""
        profile = self.super_admin.userprofile
        self.assertIsNone(profile.tenant)
        self.assertTrue(profile.is_super_admin())
    
    def test_admin_tenant_is_self(self):
        """Test that Admin tenant is self"""
        profile = self.admin.userprofile
        self.assertEqual(profile.tenant, self.admin)
        self.assertTrue(profile.is_admin())
    
    def test_operator_tenant_is_admin(self):
        """Test that Operator tenant is their Admin"""
        profile = self.operator.userprofile
        self.assertEqual(profile.tenant, self.admin)
        self.assertTrue(profile.is_operator())
    
    def test_viewer_tenant_is_admin(self):
        """Test that Viewer tenant is their Admin"""
        profile = self.viewer.userprofile
        self.assertEqual(profile.tenant, self.admin)
        self.assertTrue(profile.is_viewer())
    
    def test_is_super_admin_method(self):
        """Test is_super_admin() method"""
        self.assertTrue(self.super_admin.userprofile.is_super_admin())
        self.assertFalse(self.admin.userprofile.is_super_admin())
        self.assertFalse(self.operator.userprofile.is_super_admin())
        self.assertFalse(self.viewer.userprofile.is_super_admin())
    
    def test_is_admin_method(self):
        """Test is_admin() method"""
        self.assertFalse(self.super_admin.userprofile.is_admin())
        self.assertTrue(self.admin.userprofile.is_admin())
        self.assertFalse(self.operator.userprofile.is_admin())
        self.assertFalse(self.viewer.userprofile.is_admin())
    
    def test_is_operator_method(self):
        """Test is_operator() method"""
        self.assertFalse(self.super_admin.userprofile.is_operator())
        self.assertFalse(self.admin.userprofile.is_operator())
        self.assertTrue(self.operator.userprofile.is_operator())
        self.assertFalse(self.viewer.userprofile.is_operator())
    
    def test_is_viewer_method(self):
        """Test is_viewer() method"""
        self.assertFalse(self.super_admin.userprofile.is_viewer())
        self.assertFalse(self.admin.userprofile.is_viewer())
        self.assertFalse(self.operator.userprofile.is_viewer())
        self.assertTrue(self.viewer.userprofile.is_viewer())
    
    def test_get_tenant_super_admin_returns_none(self):
        """Test get_tenant() for Super Admin"""
        profile = self.super_admin.userprofile
        self.assertIsNone(profile.get_tenant())
    
    def test_get_tenant_admin_returns_self(self):
        """Test get_tenant() for Admin"""
        profile = self.admin.userprofile
        self.assertEqual(profile.get_tenant(), self.admin)
    
    def test_get_tenant_operator_returns_admin(self):
        """Test get_tenant() for Operator"""
        profile = self.operator.userprofile
        self.assertEqual(profile.get_tenant(), self.admin)
    
    def test_get_tenant_viewer_returns_admin(self):
        """Test get_tenant() for Viewer"""
        profile = self.viewer.userprofile
        self.assertEqual(profile.get_tenant(), self.admin)


class TenantFieldTest(TestCase):
    """Test tenant fields on data models"""
    
    def setUp(self):
        """Set up test admin and connections"""
        self.admin = User.objects.create_user(
            username='admin',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=self.admin,
            role=Role.ADMIN,
            tenant=self.admin
        )
    
    def test_connection_requires_tenant(self):
        """Test that connection requires tenant"""
        connection = DatabaseConnection(
            name='Test DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='testdb',
            created_by=self.admin,
            tenant=self.admin
        )
        connection.full_clean()  # Should not raise
        connection.save()
        self.assertEqual(connection.tenant, self.admin)
    
    def test_cascade_delete_on_admin_deletion(self):
        """Test that deleting Admin deletes all tenant data"""
        connection = DatabaseConnection.objects.create(
            name='Test DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='testdb',
            created_by=self.admin,
            tenant=self.admin
        )
        connection_id = connection.id
        
        # Delete admin
        self.admin.delete()
        
        # Connection should be deleted
        self.assertFalse(
            DatabaseConnection.objects.filter(id=connection_id).exists()
        )
    
    def test_cascade_delete_connections(self):
        """Test that connections are deleted when Admin is deleted"""
        conn1 = DatabaseConnection.objects.create(
            name='Test DB 1',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='testdb1',
            created_by=self.admin,
            tenant=self.admin
        )
        conn2 = DatabaseConnection.objects.create(
            name='Test DB 2',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='testdb2',
            created_by=self.admin,
            tenant=self.admin
        )
        
        # Delete admin
        self.admin.delete()
        
        # Both connections should be deleted
        self.assertFalse(DatabaseConnection.objects.filter(id=conn1.id).exists())
        self.assertFalse(DatabaseConnection.objects.filter(id=conn2.id).exists())
    
    def test_cascade_delete_jobs(self):
        """Test that jobs are deleted when Admin is deleted"""
        # Create connection first
        connection = DatabaseConnection.objects.create(
            name='Test DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='testdb',
            created_by=self.admin,
            tenant=self.admin
        )
        
        # Create job
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=connection,
            target_connection=connection,
            created_by=self.admin,
            tenant=self.admin
        )
        job_id = job.id
        
        # Delete admin
        self.admin.delete()
        
        # Job should be deleted
        self.assertFalse(SyncJob.objects.filter(id=job_id).exists())
    
    def test_cascade_delete_schedules(self):
        """Test that schedules are deleted when Admin is deleted"""
        # Create connection and job first
        connection = DatabaseConnection.objects.create(
            name='Test DB',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='testdb',
            created_by=self.admin,
            tenant=self.admin
        )
        
        job = SyncJob.objects.create(
            name='Test Job',
            source_connection=connection,
            target_connection=connection,
            created_by=self.admin,
            tenant=self.admin
        )
        
        # Create schedule
        schedule = SyncSchedule.objects.create(
            job=job,
            schedule_type='interval',
            interval_minutes=60,
            is_enabled=True,
            created_by=self.admin,
            tenant=self.admin
        )
        schedule_id = schedule.id
        
        # Delete admin
        self.admin.delete()
        
        # Schedule should be deleted
        self.assertFalse(SyncSchedule.objects.filter(id=schedule_id).exists())

