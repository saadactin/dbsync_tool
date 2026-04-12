"""
MongoDB specific tests for metadata.services lazy loading.

These tests ensure the metadata layer calls MongoDBConnector methods through the
connection pool without requiring a real MongoDB instance.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.contrib.auth.models import User

from connections.models import DatabaseConnection
from core.constants import DEFAULT_PORTS
from metadata import services as metadata_services
from accounts.models import UserProfile, Role


class MongoDBMetadataServicesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mongo_meta_user",
            email="mongo_meta@example.com",
            password="testpass123",
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={"role": Role.ADMIN, "tenant": self.user},
        )
        # Ensure the related object cache doesn't keep a stale profile (signals may create a default VIEWER).
        self.user = User.objects.get(pk=self.user.pk)
        self.connection = DatabaseConnection.objects.create(
            name="Mongo Meta Test",
            db_type="mongodb",
            host="localhost",
            port=DEFAULT_PORTS["mongodb"],
            username="u",
            password="p",
            database_name="admin",
            created_by=self.user,
            tenant=self.user,
            is_active=True,
        )

    @patch("metadata.services.get_connection_pool")
    def test_load_schemas_lazy_calls_get_schemas(self, mock_get_pool):
        fake_pool = MagicMock()
        fake_pool.query_timeout = 30
        fake_connector = MagicMock()
        fake_connector.get_schemas.return_value = ["appdb", "analytics"]

        fake_pool.get_connection.return_value = fake_connector
        mock_get_pool.return_value = fake_pool

        result = metadata_services.load_schemas_lazy(
            str(self.connection.id), self.user, use_cache=False
        )
        fake_connector.get_schemas.assert_called_once()
        self.assertEqual(result, [{"name": "appdb"}, {"name": "analytics"}])

    @patch("metadata.services.get_connection_pool")
    def test_load_tables_lazy_calls_get_tables(self, mock_get_pool):
        fake_pool = MagicMock()
        fake_pool.query_timeout = 30
        fake_connector = MagicMock()
        fake_connector.get_tables.return_value = ["users", "orders"]

        fake_pool.get_connection.return_value = fake_connector
        mock_get_pool.return_value = fake_pool

        result = metadata_services.load_tables_lazy(
            str(self.connection.id), "appdb", self.user, use_cache=False
        )
        fake_connector.get_tables.assert_called_once_with("appdb")
        self.assertEqual(result, [{"name": "users"}, {"name": "orders"}])

    @patch("metadata.services.get_connection_pool")
    def test_load_columns_lazy_calls_get_columns(self, mock_get_pool):
        from connections.connectors.base import ColumnInfo

        fake_pool = MagicMock()
        fake_pool.query_timeout = 30
        fake_connector = MagicMock()
        fake_connector.get_columns.return_value = [
            ColumnInfo(
                name="_id",
                data_type="string",
                is_nullable=False,
                is_primary_key=True,
                max_length=None,
                default_value=None,
            ),
            ColumnInfo(
                name="name",
                data_type="string",
                is_nullable=True,
                is_primary_key=False,
                max_length=None,
                default_value=None,
            ),
        ]

        fake_pool.get_connection.return_value = fake_connector
        mock_get_pool.return_value = fake_pool

        result = metadata_services.load_columns_lazy(
            str(self.connection.id),
            "appdb",
            "users",
            self.user,
            use_cache=False,
        )
        fake_connector.get_columns.assert_called_once_with("appdb", "users")
        self.assertEqual(result[0]["name"], "_id")
        self.assertTrue(result[0]["is_primary_key"])

