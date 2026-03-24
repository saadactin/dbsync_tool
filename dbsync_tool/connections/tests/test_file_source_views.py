from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import FileSourceConnection


class FileSourceViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='tenantadmin', password='testpass123', email='admin@example.com'
        )
        self.operator = User.objects.create_user(
            username='operator', password='testpass123', email='operator@example.com'
        )
        self.viewer = User.objects.create_user(
            username='viewer', password='testpass123', email='viewer@example.com'
        )
        self.other_tenant = User.objects.create_user(
            username='tenant2', password='testpass123', email='tenant2@example.com'
        )
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={'role': Role.ADMIN, 'tenant': self.admin}
        )
        UserProfile.objects.update_or_create(
            user=self.operator, defaults={'role': Role.OPERATOR, 'tenant': self.admin}
        )
        UserProfile.objects.update_or_create(
            user=self.viewer, defaults={'role': Role.VIEWER, 'tenant': self.admin}
        )
        UserProfile.objects.update_or_create(
            user=self.other_tenant, defaults={'role': Role.ADMIN, 'tenant': self.other_tenant}
        )
        self.source = FileSourceConnection.objects.create(
            name='CSV Source',
            relative_path='imports/source.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.admin,
            created_by=self.admin,
            is_active=True,
        )
        self.other_source = FileSourceConnection.objects.create(
            name='Tenant2 CSV Source',
            relative_path='imports/source.csv',
            delimiter=',',
            encoding='utf-8',
            has_header=True,
            tenant=self.other_tenant,
            created_by=self.other_tenant,
            is_active=True,
        )

    def test_login_required(self):
        response = self.client.get(reverse('connections:file_source_list'))
        self.assertEqual(response.status_code, 302)

    def test_viewer_can_read_list_and_detail(self):
        self.client.login(username='viewer', password='testpass123')
        list_resp = self.client.get(reverse('connections:file_source_list'))
        detail_resp = self.client.get(reverse('connections:file_source_detail', args=[self.source.id]))
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(detail_resp.status_code, 200)

    def test_viewer_cannot_create_update_delete(self):
        self.client.login(username='viewer', password='testpass123')
        create_resp = self.client.post(reverse('connections:file_source_create'), data={
            'name': 'X',
            'relative_path': 'imports/x.csv',
            'delimiter': ',',
            'encoding': 'utf-8',
            'has_header': True,
            'is_active': True,
        })
        self.assertEqual(create_resp.status_code, 403)

        update_resp = self.client.post(reverse('connections:file_source_update', args=[self.source.id]), data={
            'name': 'X2',
            'relative_path': 'imports/x2.csv',
            'delimiter': ',',
            'encoding': 'utf-8',
            'has_header': True,
            'is_active': True,
        })
        self.assertEqual(update_resp.status_code, 403)

        delete_resp = self.client.post(reverse('connections:file_source_delete', args=[self.source.id]))
        self.assertEqual(delete_resp.status_code, 403)

    def test_operator_can_create_update_delete(self):
        self.client.login(username='operator', password='testpass123')
        create_resp = self.client.post(reverse('connections:file_source_create'), data={
            'name': 'Created by Operator',
            'relative_path': 'imports/op.csv',
            'delimiter': ',',
            'encoding': 'utf-8',
            'has_header': True,
            'is_active': True,
        })
        self.assertEqual(create_resp.status_code, 302)
        created = FileSourceConnection.objects.get(name='Created by Operator')

        update_resp = self.client.post(reverse('connections:file_source_update', args=[created.id]), data={
            'name': 'Updated by Operator',
            'relative_path': 'imports/op.csv',
            'delimiter': ',',
            'encoding': 'utf-8',
            'has_header': True,
            'is_active': True,
        })
        self.assertEqual(update_resp.status_code, 302)

        delete_resp = self.client.post(reverse('connections:file_source_delete', args=[created.id]))
        self.assertEqual(delete_resp.status_code, 302)
        self.assertFalse(FileSourceConnection.objects.filter(id=created.id).exists())

    def test_cross_tenant_access_blocked(self):
        self.client.login(username='tenantadmin', password='testpass123')
        resp = self.client.get(reverse('connections:file_source_detail', args=[self.other_source.id]))
        self.assertEqual(resp.status_code, 404)
