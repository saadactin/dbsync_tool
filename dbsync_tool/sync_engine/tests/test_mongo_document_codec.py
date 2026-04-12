import datetime as dt
import uuid
from decimal import Decimal

from django.test import TestCase

from core.mongo_document_codec import (
    build_document_from_sql_row,
    normalize_mongo_value,
    sanitize_mongo_key,
)


class MongoDocumentCodecTests(TestCase):
    def test_sanitize_mongo_key_rewrites_invalid_patterns(self):
        self.assertEqual(sanitize_mongo_key("a.b"), "a_b")
        self.assertEqual(sanitize_mongo_key("$field"), "_field")
        self.assertEqual(sanitize_mongo_key(""), "_field")

    def test_normalize_handles_decimal_and_date(self):
        out_dec = normalize_mongo_value(Decimal("111.11"))
        # Prefer Decimal128 when bson is available; fallback is string.
        self.assertIn(type(out_dec).__name__, {"Decimal128", "str"})

        out_date = normalize_mongo_value(dt.date(2026, 4, 7))
        self.assertIsInstance(out_date, dt.datetime)
        self.assertEqual(out_date.date(), dt.date(2026, 4, 7))
        self.assertEqual(normalize_mongo_value(dt.time(8, 10)), "08:10:00")

    def test_normalize_handles_uuid_and_bytes(self):
        u = uuid.uuid4()
        out_u = normalize_mongo_value(u)
        self.assertEqual(out_u, str(u))

        out_bytes = normalize_mongo_value(b"abc")
        # bson Binary class name varies by import path; fallback is base64 string.
        self.assertIn(type(out_bytes).__name__, {"Binary", "str"})

    def test_build_document_pk_null_falls_back_to_deterministic_hash(self):
        doc = build_document_from_sql_row(
            source_columns=["id", "name"],
            target_fields=["id", "name"],
            row=[None, "Alice"],
            pk_columns=["id"],
        )
        self.assertIn("_id", doc)
        self.assertIsNotNone(doc["_id"])
        self.assertNotEqual(doc["_id"], "None")

    def test_build_document_composite_pk_generates_distinct_ids(self):
        doc1 = build_document_from_sql_row(
            source_columns=["order_id", "line_no", "sku"],
            target_fields=["order_id", "line_no", "sku"],
            row=[10, 1, "A"],
            pk_columns=["order_id", "line_no"],
        )
        doc2 = build_document_from_sql_row(
            source_columns=["order_id", "line_no", "sku"],
            target_fields=["order_id", "line_no", "sku"],
            row=[10, 2, "B"],
            pk_columns=["order_id", "line_no"],
        )
        self.assertNotEqual(doc1["_id"], doc2["_id"])

    def test_build_document_sanitizes_field_names(self):
        doc = build_document_from_sql_row(
            source_columns=["id", "price"],
            target_fields=["$bad.name", "cost.value"],
            row=[1, Decimal("10.00")],
            pk_columns=["id"],
        )
        self.assertIn("_bad_name", doc)
        self.assertIn("cost_value", doc)

