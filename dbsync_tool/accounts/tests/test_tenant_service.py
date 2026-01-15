"""
Unit tests for TenantService
"""
from django.test import TestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob
from accounts.models import UserProfile, Role
from accounts.services.tenant_service import TenantService


class TenantServiceTest(TestCase):
    """Test TenantService methods"""
    
    def setUp(self):
        """Set up test data with multiple admins and connections"""
        # Create Super Admin
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
        
        # Create Admin A
        self.admin_a = User.objects.create_user(
            username='admin_a',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=self.admin_a,
            role=Role.ADMIN,
            tenant=self.admin_a
        )
        
        # Create Admin B
        self.admin_b = User.objects.create_user(
            username='admin_b',
            password='testpass123',
            is_staff=True
        )
        UserProfile.objects.create(
            user=self.admin_b,
            role=Role.ADMIN,
            tenant=self.admin_b
        )
        
        # Create Operator for Admin A
        self.operator_a = User.objects.create_user(
            username='operator_a',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.operator_a,
            role=Role.OPERATOR,
            tenant=self.admin_a
        )
        
        # Create Viewer for Admin A
        self.viewer_a = User.objects.create_user(
            username='viewer_a',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.viewer_a,
            role=Role.VIEWER,
            tenant=self.admin_a
        )
        
        # Create connections for each admin
        self.conn_a = DatabaseConnection.objects.create(
            name='Admin A Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='db_a',
            created_by=self.admin_a,
            tenant=self.admin_a
        )
        
        self.conn_b = DatabaseConnection.objects.create(
            name='Admin B Connection',
            db_type='postgres',
            host='localhost',
            port=5432,
            username='user',
            password='encrypted_pass',
            database_name='db_b',
            created_by=self.admin_b,
            tenant=self.admin_b
        )
    
    def test_super_admin_sees_all_connections(self):
        """Test that Super Admin sees all connections"""
        qs = DatabaseConnection.objects.all()
        filtered_qs = TenantService.get_queryset_for_user(qs, self.super_admin)
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(self.conn_a, filtered_qs)
        self.assertIn(self.conn_b, filtered_qs)
    
    def test_admin_sees_only_own_connections(self):
        """Test that Admin sees only their tenant connections"""
        qs = DatabaseConnection.objects.all()
        filtered_qs = TenantService.get_queryset_for_user(qs, self.admin_a)
        self.assertEqual(filtered_qs.count(), 1)
        self.assertIn(self.conn_a, filtered_qs)
        self.assertNotIn(self.conn_b, filtered_qs)
    
    def test_operator_sees_only_tenant_connections(self):
        """Test that Operator sees only tenant connections"""
        qs = DatabaseConnection.objects.all()
        filtered_qs = TenantService.get_queryset_for_user(qs, self.operator_a)
        self.assertEqual(filtered_qs.count(), 1)
        self.assertIn(self.conn_a, filtered_qs)
        self.assertNotIn(self.conn_b, filtered_qs)
    
    def test_viewer_sees_only_tenant_connections(self):
        """Test that Viewer sees only tenant connections"""
        qs = DatabaseConnection.objects.all()
        filtered_qs = TenantService.get_queryset_for_user(qs, self.viewer_a)
        self.assertEqual(filtered_qs.count(), 1)
        self.assertIn(self.conn_a, filtered_qs)
        self.assertNotIn(self.conn_b, filtered_qs)
    
    def test_cross_tenant_isolation_admin_a_vs_admin_b(self):
        """Test that Admin A cannot see Admin B's data"""
        qs = DatabaseConnection.objects.all()
        filtered_qs_a = TenantService.get_queryset_for_user(qs, self.admin_a)
        filtered_qs_b = TenantService.get_queryset_for_user(qs, self.admin_b)
        
        self.assertNotIn(self.conn_b, filtered_qs_a)
        self.assertNotIn(self.conn_a, filtered_qs_b)
    
    def test_unauthenticated_user_sees_nothing(self):
        """Test that unauthenticated user sees nothing"""
        from django.contrib.auth.models import AnonymousUser
        qs = DatabaseConnection.objects.all()
        anonymous_user = AnonymousUser()
        filtered_qs = TenantService.get_queryset_for_user(qs, anonymous_user)
        self.assertEqual(filtered_qs.count(), 0)
    
    def test_missing_profile_returns_empty_queryset(self):
        """Test that missing profile returns empty queryset"""
        # Create user without profile
        user_no_profile = User.objects.create_user(
            username='noprofile',
            password='testpass123'
        )
        qs = DatabaseConnection.objects.all()
        filtered_qs = TenantService.get_queryset_for_user(qs, user_no_profile)
        self.assertEqual(filtered_qs.count(), 0)
    
    def test_get_user_tenant_super_admin_returns_none(self):
        """Test get_user_tenant() for Super Admin"""
        tenant = TenantService.get_user_tenant(self.super_admin)
        self.assertIsNone(tenant)
    
    def test_get_user_tenant_admin_returns_self(self):
        """Test get_user_tenant() for Admin"""
        tenant = TenantService.get_user_tenant(self.admin_a)
        self.assertEqual(tenant, self.admin_a)
    
    def test_get_user_tenant_operator_returns_admin(self):
        """Test get_user_tenant() for Operator"""
        tenant = TenantService.get_user_tenant(self.operator_a)
        self.assertEqual(tenant, self.admin_a)
    
    def test_get_user_tenant_viewer_returns_admin(self):
        """Test get_user_tenant() for Viewer"""
        tenant = TenantService.get_user_tenant(self.viewer_a)
        self.assertEqual(tenant, self.admin_a)
    
    def test_get_user_tenant_unauthenticated_returns_none(self):
        """Test get_user_tenant() for unauthenticated user"""
        from django.contrib.auth.models import AnonymousUser
        anonymous_user = AnonymousUser()
        tenant = TenantService.get_user_tenant(anonymous_user)
        self.assertIsNone(tenant)
    
    def test_can_user_manage_tenant_super_admin_always_true(self):
        """Test that Super Admin can manage all tenants"""
        self.assertTrue(
            TenantService.can_user_manage_tenant(self.super_admin, self.admin_a)
        )
        self.assertTrue(
            TenantService.can_user_manage_tenant(self.super_admin, self.admin_b)
        )
    
    def test_can_user_manage_tenant_admin_only_self(self):
        """Test that Admin can only manage themselves"""
        self.assertTrue(
            TenantService.can_user_manage_tenant(self.admin_a, self.admin_a)
        )
        self.assertFalse(
            TenantService.can_user_manage_tenant(self.admin_a, self.admin_b)
        )
    
    def test_can_user_manage_tenant_operator_false(self):
        """Test that Operator cannot manage tenants"""
        self.assertFalse(
            TenantService.can_user_manage_tenant(self.operator_a, self.admin_a)
        )
    
    def test_can_user_manage_tenant_viewer_false(self):
        """Test that Viewer cannot manage tenants"""
        self.assertFalse(
            TenantService.can_user_manage_tenant(self.viewer_a, self.admin_a)
        )
    
    def test_can_user_manage_tenant_cross_tenant_false(self):
        """Test that Admin cannot manage other tenant"""
        self.assertFalse(
            TenantService.can_user_manage_tenant(self.admin_a, self.admin_b)
        )
    
    def test_get_tenant_users_includes_admin(self):
        """Test that get_tenant_users() returns Admin + tenant users"""
        tenant_users = TenantService.get_tenant_users(self.admin_a)
        usernames = [user.username for user in tenant_users]
        self.assertIn('admin_a', usernames)
        self.assertIn('operator_a', usernames)
        self.assertIn('viewer_a', usernames)
    
    def test_get_tenant_users_includes_operators(self):
        """Test that get_tenant_users() returns all operators"""
        tenant_users = TenantService.get_tenant_users(self.admin_a)
        usernames = [user.username for user in tenant_users]
        self.assertIn('operator_a', usernames)
    
    def test_get_tenant_users_includes_viewers(self):
        """Test that get_tenant_users() returns all viewers"""
        tenant_users = TenantService.get_tenant_users(self.admin_a)
        usernames = [user.username for user in tenant_users]
        self.assertIn('viewer_a', usernames)
    
    def test_get_tenant_users_excludes_other_tenants(self):
        """Test that get_tenant_users() excludes other tenant users"""
        tenant_users = TenantService.get_tenant_users(self.admin_a)
        usernames = [user.username for user in tenant_users]
        self.assertNotIn('admin_b', usernames)
        self.assertNotIn('superadmin', usernames)

