"""Tests for timed database/API connection test endpoints and service."""
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from accounts.models import UserProfile, Role
from connections.models import DatabaseConnection, APIConnection
from connections.services import test_database_connection


class TestDatabaseConnectionServiceLatency(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="svcuser", password="pass", email="a@b.c"
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": None},
        )
        self.conn = DatabaseConnection.objects.create(
            name="DB1",
            db_type="postgres",
            host="db.example",
            port=5432,
            username="u",
            password="p",
            database_name="d",
            created_by=self.user,
            tenant=self.user,
            is_active=True,
        )

    @patch("connections.services.get_connector")
    def test_success_includes_latency_and_details(self, mock_get):
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = True
        mock_get.return_value = mock_connector

        out = test_database_connection(self.conn, self.user)
        self.assertTrue(out["success"])
        self.assertEqual(out["message"], "Connection successful")
        self.assertIn("latency_ms", out)
        self.assertIsInstance(out["latency_ms"], int)
        self.assertGreaterEqual(out["latency_ms"], 0)
        self.assertEqual(out["details"]["host"], "db.example")
        self.assertEqual(out["details"]["db_type"], "postgres")
        mock_connector.close.assert_called_once()

    @patch("connections.services.get_connector")
    def test_connector_false_includes_latency(self, mock_get):
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = False
        mock_get.return_value = mock_connector

        out = test_database_connection(self.conn, None)
        self.assertFalse(out["success"])
        self.assertGreaterEqual(out["latency_ms"], 0)


class ConnectionTestViewLatencyTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="vuser", password="pass", email="v@b.c"
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": None},
        )
        self.conn = DatabaseConnection.objects.create(
            name="DB2",
            db_type="mysql",
            host="h",
            port=3306,
            username="u",
            password="p",
            database_name="d",
            created_by=self.user,
            tenant=self.user,
            is_active=True,
        )

    @patch("connections.views.test_database_connection")
    def test_post_json_includes_latency_ms(self, mock_test):
        mock_test.return_value = {
            "success": True,
            "message": "ok",
            "latency_ms": 42,
            "details": {"host": "h"},
        }
        self.client.login(username="vuser", password="pass")
        url = reverse("connections:test", args=[self.conn.id])
        response = self.client.post(url, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["latency_ms"], 42)
        self.assertEqual(data["details"]["host"], "h")


class APIConnectionTestViewLatencyTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="tadmin", password="pass", email="t@b.c"
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": self.user},
        )
        self.api = APIConnection.objects.create(
            name="Z1",
            api_type="zoho_crm",
            client_id="c",
            client_secret="s",
            refresh_token="r",
            api_domain="https://www.zohoapis.in",
            token_url="https://accounts.zoho.in/oauth/v2/token",
            tenant=self.user,
            created_by=self.user,
        )

    @patch.object(APIConnection, "test_connection")
    def test_existing_connection_response_has_latency(self, mock_tc):
        mock_tc.return_value = (True, "ok", ["m1"])
        self.client.login(username="tadmin", password="pass")
        url = reverse("connections:api_test", args=[self.api.id])
        response = self.client.post(url, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertIn("latency_ms", data)
        self.assertIsInstance(data["latency_ms"], int)
        self.assertGreaterEqual(data["latency_ms"], 0)
        self.assertEqual(data["details"]["api_type"], "zoho_crm")


class ConnectionTestAndListDatabasesLatencyTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="lst", password="pass", email="l@b.c"
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": None},
        )

    @patch("connections.views.get_connector")
    def test_success_includes_latency_ms(self, mock_get):
        mock_connector = MagicMock()
        mock_connector.list_databases.return_value = ["a", "b"]
        mock_get.return_value = mock_connector
        self.client.login(username="lst", password="pass")
        url = reverse("connections:test_and_list_databases")
        body = {
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "username": "u",
            "password": "p",
        }
        response = self.client.post(
            url, data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertIn("latency_ms", data)
        self.assertGreaterEqual(data["latency_ms"], 0)
        self.assertEqual(data["details"]["host"], "localhost")
