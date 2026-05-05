from django.test import SimpleTestCase

from connections.connectors.sqlserver import SQLServerConnector


class SQLServerDefaultTranslationTests(SimpleTestCase):
    def setUp(self):
        self.connector = SQLServerConnector(
            host="localhost",
            port=1433,
            username="u",
            password="p",
            database_name="db",
        )

    def test_boolean_defaults_map_to_bit_literals(self):
        self.assertEqual(self.connector._format_default_value("TRUE", "BOOLEAN"), "1")
        self.assertEqual(self.connector._format_default_value("FALSE", "BOOLEAN"), "0")
        self.assertEqual(self.connector._format_default_value("((TRUE))", "BOOLEAN"), "1")
        self.assertEqual(self.connector._format_default_value("(false)", "BOOLEAN"), "0")

    def test_sqlserver_constants_and_now_mapping(self):
        self.assertEqual(self.connector._format_default_value("now()", "DATETIME"), "GETDATE()")
        self.assertEqual(
            self.connector._format_default_value("CURRENT_TIMESTAMP", "DATETIME"),
            "CURRENT_TIMESTAMP",
        )
        self.assertEqual(self.connector._format_default_value("(NULL)", "INT"), "NULL")

    def test_numeric_and_text_defaults(self):
        self.assertEqual(self.connector._format_default_value("42", "INT"), "42")
        self.assertEqual(self.connector._format_default_value("active", "VARCHAR"), "'active'")
