from unittest.mock import Mock

from django.test import TestCase

from connections.connectors.base import ColumnInfo
from connections.connectors.clickhouse import ClickHouseConnector


class ClickHouseSQLServerCompatibilityTests(TestCase):
    def setUp(self):
        # We don't connect to a live ClickHouse server for these unit tests.
        self.connector = ClickHouseConnector(
            host="localhost",
            port=9000,
            username="default",
            password="",
            database_name="default",
        )

    def test_format_default_value_getdate_variants_to_now(self):
        self.assertEqual(self.connector._format_default_value("GETDATE()", "DateTime"), "now()")
        self.assertEqual(
            self.connector._format_default_value("((getdate()))", "DateTime"),
            "now()",
        )
        self.assertEqual(
            self.connector._format_default_value("CURRENT_TIMESTAMP", "DateTime"),
            "now()",
        )
        self.assertEqual(
            self.connector._format_default_value("SYSDATETIME()", "DateTime"),
            "now()",
        )
        self.assertEqual(
            self.connector._format_default_value("GETUTCDATE()", "DateTime"),
            "now()",
        )

    def test_format_default_value_newid_variants_to_generateuuidv4(self):
        self.assertEqual(self.connector._format_default_value("NEWID()", "UUID"), "generateUUIDv4()")
        self.assertEqual(
            self.connector._format_default_value("NEWSEQUENTIALID()", "UUID"),
            "generateUUIDv4()",
        )

    def test_create_table_includes_allow_nullable_key_and_assume_not_null_for_nullable_order_by(self):
        # Mock the connection so `create_table` captures the generated DDL.
        self.connector._connection = Mock()
        self.connector.ensure_schema_exists = Mock()

        columns = [
            ColumnInfo(
                name="id",
                data_type="Int32",
                is_nullable=True,  # nullable key (the edge case)
                is_primary_key=True,
            ),
            ColumnInfo(
                name="name",
                data_type="String",
                is_nullable=False,
                is_primary_key=False,
            ),
        ]

        self.connector.create_table(schema="test_db", table="test_table", columns=columns)

        ddl = self.connector._connection.command.call_args[0][0]

        self.assertIn("SETTINGS allow_nullable_key = 1", ddl)
        self.assertIn("assumeNotNull(`id`)", ddl)

