"""
Unit tests for MongoDBConnector schema inference (get_columns).
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from connections.connectors.mongodb import MongoDBConnector


class MongoDBConnectorInferenceTests(TestCase):
    @patch("connections.connectors.mongodb.MongoDBConnector.connect")
    def test_get_columns_infers_flat_fields_and_includes_id(self, mock_connect):
        connector = MongoDBConnector(
            host="localhost",
            port=27017,
            username="u",
            password="p",
            database_name="admin",
        )

        fake_client = MagicMock()
        connector._client = fake_client

        # Mock db/collection and find cursor
        fake_db = MagicMock()
        fake_coll = MagicMock()
        fake_client.__getitem__.return_value = fake_db
        fake_db.__getitem__.return_value = fake_coll

        fake_coll.find.return_value = [
            {"_id": "abc", "name": "Saad", "age": 10, "address": {"city": "Pune"}},
            {"_id": "def", "name": "Ali", "address": {"city": "Mumbai"}},
        ]

        cols = connector.get_columns("appdb", "users")
        by_name = {c.name: c for c in cols}

        self.assertIn("_id", by_name)
        self.assertTrue(by_name["_id"].is_primary_key)
        self.assertFalse(by_name["_id"].is_nullable)

        self.assertIn("name", by_name)
        self.assertIn("age", by_name)
        self.assertIn("address_city", by_name)
        # For schemaless MongoDB sources, non-PK fields must stay nullable.
        self.assertTrue(by_name["name"].is_nullable)
        self.assertTrue(by_name["age"].is_nullable)

