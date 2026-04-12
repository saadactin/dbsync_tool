from unittest.mock import MagicMock, patch

import datetime as dt
from decimal import Decimal
import pandas as pd
from django.test import TestCase

from connections.connectors.mongodb import MongoDBConnector


class MongoUpsertDataframeTests(TestCase):
    @patch("connections.connectors.mongodb.MongoDBConnector.connect")
    def test_upsert_dataframe_sets_id_and_calls_bulk_write(self, _mock_connect):
        c = MongoDBConnector(host="localhost", port=27017, username="u", password="p")
        fake_client = MagicMock()
        c._client = fake_client

        fake_coll = MagicMock()
        fake_db = MagicMock()
        fake_client.__getitem__.return_value = fake_db
        fake_db.__getitem__.return_value = fake_coll

        df = pd.DataFrame([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
        c.upsert_dataframe(schema="appdb", table="users", df=df, key_column="id")

        fake_coll.bulk_write.assert_called_once()

    @patch("connections.connectors.mongodb.MongoDBConnector.connect")
    def test_bulk_upsert_documents_normalizes_decimal_and_date(self, _mock_connect):
        c = MongoDBConnector(host="localhost", port=27017, username="u", password="p")
        fake_client = MagicMock()
        c._client = fake_client

        fake_coll = MagicMock()
        fake_db = MagicMock()
        fake_client.__getitem__.return_value = fake_db
        fake_db.__getitem__.return_value = fake_coll

        c.bulk_upsert_documents(
            schema="appdb",
            table="orders",
            docs=[{"_id": "1", "amount": Decimal("12.50"), "order_date": dt.date(2026, 4, 7)}],
        )

        fake_coll.bulk_write.assert_called_once()

