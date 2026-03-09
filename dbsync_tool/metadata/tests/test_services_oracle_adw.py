"""
Oracle ADW specific tests for metadata.services.

These tests verify that the metadata layer can work with an oracle_adw
DatabaseConnection by using the connection pool and OracleADWConnector
interface, without requiring a real Oracle database.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.contrib.auth.models import User

from connections.models import DatabaseConnection
from core.constants import DEFAULT_PORTS
from metadata import services as metadata_services


class OracleADWMetadataServicesTests(TestCase):
    """Tests for metadata services with oracle_adw connections."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="oracle_meta_user",
            email="oracle_meta@example.com",
            password="testpass123",
        )
        # Create an Oracle ADW DatabaseConnection; no real DB is contacted
        self.connection = DatabaseConnection.objects.create(
            name="Oracle ADW Meta Test",
            db_type="oracle_adw",
            host="adw.example.com",
            port=DEFAULT_PORTS["oracle_adw"],
            username="adw_user",
            password="secret_pass",
            database_name="myadw_high",
            created_by=self.user,
        )

    @patch("metadata.services.get_connection_pool")
    def test_load_schemas_lazy_uses_pool_with_oracle_connector(self, mock_get_pool):
        """load_schemas_lazy should obtain an Oracle connector from the pool and call get_schemas()."""
        fake_pool = MagicMock()
        fake_pool.query_timeout = 30
        fake_connector = MagicMock()
        fake_connector.get_schemas.return_value = ["ADW_SCHEMA1", "ADW_SCHEMA2"]

        fake_pool.get_connection.return_value = fake_connector
        mock_get_pool.return_value = fake_pool

        result = metadata_services.load_schemas_lazy(
            str(self.connection.id), self.user, use_cache=False
        )

        fake_pool.get_connection.assert_called_once()
        fake_connector.get_schemas.assert_called_once()
        self.assertEqual(
            result,
            [{"name": "ADW_SCHEMA1"}, {"name": "ADW_SCHEMA2"}],
        )

    @patch("metadata.services.get_connection_pool")
    def test_load_tables_lazy_uses_pool_with_oracle_connector(self, mock_get_pool):
        """load_tables_lazy should call connector.get_tables for oracle_adw."""
        fake_pool = MagicMock()
        fake_pool.query_timeout = 30
        fake_connector = MagicMock()
        fake_connector.get_tables.return_value = ["TABLE_A", "TABLE_B"]

        fake_pool.get_connection.return_value = fake_connector
        mock_get_pool.return_value = fake_pool

        result = metadata_services.load_tables_lazy(
            str(self.connection.id), "ADW_SCHEMA", self.user, use_cache=False
        )

        fake_pool.get_connection.assert_called_once()
        fake_connector.get_tables.assert_called_once_with("ADW_SCHEMA")
        self.assertEqual(
            result,
            [{"name": "TABLE_A"}, {"name": "TABLE_B"}],
        )

    @patch("metadata.services.get_connection_pool")
    def test_load_columns_lazy_returns_oracle_column_metadata(self, mock_get_pool):
        """load_columns_lazy should return rich column metadata from OracleADWConnector.get_columns()."""
        from connections.connectors.base import ColumnInfo

        fake_pool = MagicMock()
        fake_pool.query_timeout = 30
        fake_connector = MagicMock()
        fake_connector.get_columns.return_value = [
            ColumnInfo(
                name="ID",
                data_type="NUMBER(10,0)",
                is_nullable=False,
                is_primary_key=True,
                max_length=None,
                default_value=None,
            ),
            ColumnInfo(
                name="CREATED_AT",
                data_type="TIMESTAMP(6)",
                is_nullable=False,
                is_primary_key=False,
                max_length=None,
                default_value=None,
            ),
        ]

        fake_pool.get_connection.return_value = fake_connector
        mock_get_pool.return_value = fake_pool

        result = metadata_services.load_columns_lazy(
            str(self.connection.id),
            "ADW_SCHEMA",
            "ORDERS",
            self.user,
            use_cache=False,
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(
            result[0],
            {
                "name": "ID",
                "data_type": "NUMBER(10,0)",
                "is_nullable": False,
                "is_primary_key": True,
                "max_length": None,
                "default_value": None,
            },
        )
        self.assertEqual(
            result[1]["name"],
            "CREATED_AT",
        )

