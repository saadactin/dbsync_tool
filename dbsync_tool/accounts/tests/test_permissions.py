"""
Unit tests for permission mixins
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.views import View
from accounts.models import UserProfile, Role
from accounts.permissions import (
    RoleRequiredMixin,
    SuperAdminRequiredMixin,
    AdminOrSuperAdminMixin,
    OperatorOrAboveMixin,
    ViewerReadOnlyMixin
)


class TestView(RoleRequiredMixin, View):
    """Test view for testing mixins"""
    allowed_roles = [Role.ADMIN]
    
    def get(self, request):
        return HttpResponse("OK")


class PermissionMixinTest(TestCase):
    """Test permission mixins"""
    
    def setUp(self):
        """Set up test users with different roles"""
        self.factory = RequestFactory()
        
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
        
        # Create Admin
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
        
        # Create Operator
        self.operator = User.objects.create_user(
            username='operator',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.operator,
            role=Role.OPERATOR,
            tenant=self.admin
        )
        
        # Create Viewer
        self.viewer = User.objects.create_user(
            username='viewer',
            password='testpass123'
        )
        UserProfile.objects.create(
            user=self.viewer,
            role=Role.VIEWER,
            tenant=self.admin
        )
    
    def test_role_required_mixin_blocks_unauthorized_roles(self):
        """Test that RoleRequiredMixin blocks unauthorized roles"""
        class TestView(RoleRequiredMixin, View):
            allowed_roles = [Role.ADMIN]
            
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.operator  # Operator not in allowed_roles
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_role_required_mixin_allows_authorized_roles(self):
        """Test that RoleRequiredMixin allows authorized roles"""
        class TestView(RoleRequiredMixin, View):
            allowed_roles = [Role.ADMIN]
            
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.admin  # Admin is in allowed_roles
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_super_admin_required_mixin_blocks_admin(self):
        """Test that SuperAdminRequiredMixin blocks Admin"""
        class TestView(SuperAdminRequiredMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.admin
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_super_admin_required_mixin_blocks_operator(self):
        """Test that SuperAdminRequiredMixin blocks Operator"""
        class TestView(SuperAdminRequiredMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.operator
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_super_admin_required_mixin_blocks_viewer(self):
        """Test that SuperAdminRequiredMixin blocks Viewer"""
        class TestView(SuperAdminRequiredMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.viewer
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_super_admin_required_mixin_allows_super_admin(self):
        """Test that SuperAdminRequiredMixin allows Super Admin"""
        class TestView(SuperAdminRequiredMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.super_admin
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_admin_or_super_admin_mixin_allows_super_admin(self):
        """Test that AdminOrSuperAdminMixin allows Super Admin"""
        class TestView(AdminOrSuperAdminMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.super_admin
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_admin_or_super_admin_mixin_allows_admin(self):
        """Test that AdminOrSuperAdminMixin allows Admin"""
        class TestView(AdminOrSuperAdminMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.admin
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_admin_or_super_admin_mixin_blocks_operator(self):
        """Test that AdminOrSuperAdminMixin blocks Operator"""
        class TestView(AdminOrSuperAdminMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.operator
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_admin_or_super_admin_mixin_blocks_viewer(self):
        """Test that AdminOrSuperAdminMixin blocks Viewer"""
        class TestView(AdminOrSuperAdminMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.viewer
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_operator_or_above_mixin_allows_super_admin(self):
        """Test that OperatorOrAboveMixin allows Super Admin"""
        class TestView(OperatorOrAboveMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.super_admin
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_operator_or_above_mixin_allows_admin(self):
        """Test that OperatorOrAboveMixin allows Admin"""
        class TestView(OperatorOrAboveMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.admin
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_operator_or_above_mixin_allows_operator(self):
        """Test that OperatorOrAboveMixin allows Operator"""
        class TestView(OperatorOrAboveMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.operator
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_operator_or_above_mixin_blocks_viewer(self):
        """Test that OperatorOrAboveMixin blocks Viewer"""
        class TestView(OperatorOrAboveMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.viewer
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_viewer_read_only_mixin_blocks_post(self):
        """Test that ViewerReadOnlyMixin blocks POST for Viewer"""
        class TestView(ViewerReadOnlyMixin, View):
            def post(self, request):
                return HttpResponse("OK")
        
        request = self.factory.post('/test/')
        request.user = self.viewer
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_viewer_read_only_mixin_blocks_put(self):
        """Test that ViewerReadOnlyMixin blocks PUT for Viewer"""
        class TestView(ViewerReadOnlyMixin, View):
            def put(self, request):
                return HttpResponse("OK")
        
        request = self.factory.put('/test/')
        request.user = self.viewer
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_viewer_read_only_mixin_blocks_delete(self):
        """Test that ViewerReadOnlyMixin blocks DELETE for Viewer"""
        class TestView(ViewerReadOnlyMixin, View):
            def delete(self, request):
                return HttpResponse("OK")
        
        request = self.factory.delete('/test/')
        request.user = self.viewer
        view = TestView.as_view()
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_viewer_read_only_mixin_allows_get(self):
        """Test that ViewerReadOnlyMixin allows GET for Viewer"""
        class TestView(ViewerReadOnlyMixin, View):
            def get(self, request):
                return HttpResponse("OK")
        
        request = self.factory.get('/test/')
        request.user = self.viewer
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_viewer_read_only_mixin_allows_post_for_operator(self):
        """Test that ViewerReadOnlyMixin allows POST for Operator"""
        class TestView(ViewerReadOnlyMixin, View):
            def post(self, request):
                return HttpResponse("OK")
        
        request = self.factory.post('/test/')
        request.user = self.operator
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)

