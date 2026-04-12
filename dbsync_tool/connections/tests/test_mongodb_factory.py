from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase

from connections.connectors.factory import get_connector
from connections.models import DatabaseConnection
from core.exceptions import InvalidDatabaseTypeError


class MongoDBFactoryTests(TestCase):
    @patch("connections.connectors.factory.decrypt_password")
    @patch("pymongo.MongoClient")
    def test_factory_get_connector_supports_mongodb(self, mock_mongo_client, mock_decrypt):
        mock_decrypt.return_value = "secret"
        mock_mongo_client.return_value = MagicMock()

        user = User.objects.create_user(username="u", password="p")
        conn = DatabaseConnection.objects.create(
            name="mongo1",
            db_type="mongodb",
            host="localhost",
            port=27017,
            username="root",
            password="ENCRYPTED",
            database_name="saad",
            created_by=user,
            tenant=user,
            is_active=True,
        )

        connector = get_connector(conn)
        # Connector type import is optional; just ensure it doesn't raise and has core attrs.
        self.assertEqual(connector.host, "localhost")
        self.assertEqual(int(connector.port), 27017)

    def test_factory_get_connector_unsupported_type_raises(self):
        # Model validation prevents invalid db_type from being saved, so this case is already guarded.
        # We keep this test minimal to ensure factory raises on future unexpected types if encountered.
        with patch("connections.connectors.factory.decrypt_password") as mock_decrypt:
            mock_decrypt.return_value = "pw"
            with self.assertRaises(InvalidDatabaseTypeError):
                get_connector(
                    MagicMock(
                        db_type="nope",
                        host="h",
                        port=1,
                        username="u",
                        password="ENCRYPTED",
                        database_name="d",
                    )
                )

