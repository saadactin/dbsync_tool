"""
Unit tests for OracleADWConnector.

These tests focus on:
- Basic connect/test_connection flow with the oracledb driver mocked
- Error mapping for common Oracle errors (e.g. ORA-01017)
- Behaviour of list_databases() for the Oracle ADW service name
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from connections.connectors.oracle_adw import OracleADWConnector
from core.exceptions import DatabaseConnectionError, TableNotFoundError


class OracleADWConnectorTests(TestCase):
    """Test cases for OracleADWConnector."""

    def setUp(self):
        self.host = "adw.example.com"
        self.port = 1522
        self.username = "adw_user"
        self.password = "secret"
        self.service_name = "myadw_high"

    @patch("connections.connectors.oracle_adw.oracledb")
    def test_test_connection_success(self, mock_oracledb):
        """test_connection should return True when SELECT 1 FROM DUAL succeeds."""
        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        fake_cursor.fetchone.return_value = (1,)
        mock_oracledb.connect.return_value = fake_conn

        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )

        result = connector.test_connection()

        self.assertTrue(result)
        mock_oracledb.connect.assert_called_once()
        fake_cursor.execute.assert_called_with("SELECT 1 FROM DUAL")

    @patch("connections.connectors.oracle_adw.oracledb")
    def test_test_connection_invalid_credentials_maps_error(self, mock_oracledb):
        """
        When Oracle raises ORA-01017 during connect, the connector should map it
        to a DatabaseConnectionError with a friendly message.
        """
        mock_oracledb.connect.side_effect = Exception("ORA-01017: invalid username/password; logon denied")

        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )

        with self.assertRaises(DatabaseConnectionError) as ctx:
            connector.test_connection()

        msg = str(ctx.exception)
        self.assertIn("Invalid Oracle username or password", msg)
        self.assertIn("ORA-01017", msg)

    @patch("connections.connectors.oracle_adw.oracledb")
    def test_list_databases_returns_service_name_after_successful_test(self, mock_oracledb):
        """list_databases should return a single entry with the configured service name."""
        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        fake_cursor.fetchone.return_value = (1,)
        mock_oracledb.connect.return_value = fake_conn

        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )

        databases = connector.list_databases()

        self.assertEqual(databases, [self.service_name])

    def test_get_columns_enriches_types_with_precision_and_length(self):
        """
        get_columns should embed precision/scale/length into the data_type string
        so that downstream type-mapping can make non-lossy decisions.
        """
        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        connector._connection = fake_conn

        # First query: table existence check (COUNT(*))
        fake_cursor.fetchone.return_value = (1,)
        # Second query: column metadata
        fake_cursor.fetchall.return_value = [
            ("COL_NUM", "NUMBER", 22, 38, 10, "N"),
            ("COL_VC", "VARCHAR2", 100, None, None, "Y"),
        ]

        cols = connector.get_columns("myschema", "mytable")

        self.assertEqual(len(cols), 2)
        num_col = cols[0]
        vc_col = cols[1]

        self.assertEqual(num_col.name, "COL_NUM")
        self.assertEqual(num_col.data_type, "NUMBER(38,10)")
        self.assertFalse(num_col.is_nullable)
        self.assertEqual(num_col.max_length, 22)

        self.assertEqual(vc_col.name, "COL_VC")
        self.assertEqual(vc_col.data_type, "VARCHAR2(100)")
        self.assertTrue(vc_col.is_nullable)
        self.assertEqual(vc_col.max_length, 100)

    def test_truncate_table_executes_expected_ddl(self):
        """truncate_table should issue a TRUNCATE TABLE DDL with quoted identifiers."""
        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        connector._connection = fake_conn

        connector.truncate_table("myschema", "mytable")

        fake_cursor.execute.assert_called_once()
        sql = fake_cursor.execute.call_args[0][0]
        self.assertIn('TRUNCATE TABLE "MYSCHEMA"."MYTABLE"', sql)

    def test_create_table_uses_columninfo_types_verbatim(self):
        """
        create_table should build a CREATE TABLE statement using the
        ColumnInfo.data_type strings verbatim (already Oracle-specific).
        """
        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        connector._connection = fake_conn

        from connections.connectors.base import ColumnInfo

        columns = [
            ColumnInfo(
                name="id",
                data_type="NUMBER(19)",
                is_nullable=False,
                is_primary_key=True,
                max_length=None,
                default_value=None,
            ),
            ColumnInfo(
                name="name",
                data_type="VARCHAR2(255)",
                is_nullable=True,
                is_primary_key=False,
                max_length=255,
                default_value=None,
            ),
        ]

        connector.create_table("myschema", "mytable", columns)

        fake_cursor.execute.assert_called_once()
        ddl = fake_cursor.execute.call_args[0][0]
        self.assertIn('CREATE TABLE "MYSCHEMA"."MYTABLE"', ddl)
        self.assertIn('"ID" NUMBER(19) NOT NULL', ddl)
        self.assertIn('"NAME" VARCHAR2(255)', ddl)

    def test_bulk_insert_normalizes_rows_and_executes_executemany(self):
        """
        bulk_insert should normalize incoming rows (e.g. booleans -> 0/1)
        and call executemany with bind variables.
        """
        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        connector._connection = fake_conn

        columns = ["id", "is_active"]
        rows = [(1, True), (2, False)]

        connector.bulk_insert("myschema", "mytable", columns, rows)

        fake_cursor.executemany.assert_called_once()
        sql, param_rows = fake_cursor.executemany.call_args[0]

        self.assertIn('INSERT INTO "MYSCHEMA"."MYTABLE"', sql)
        self.assertIn('"ID"', sql)
        self.assertIn('"IS_ACTIVE"', sql)
        # Booleans should be normalized to 0/1
        self.assertEqual(param_rows[0][1], 1)
        self.assertEqual(param_rows[1][1], 0)

    def test_normalize_row_converts_timedelta_and_time_for_timestamp_columns(self):
        """MySQL TIME columns come as timedelta; Oracle TIMESTAMP expects datetime (avoid ORA-00932)."""
        from datetime import datetime, timedelta, time
        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )
        # timedelta -> datetime(1970,1,1) + timedelta
        row1 = connector._normalize_row((timedelta(hours=2, minutes=30),))
        self.assertIsInstance(row1[0], datetime)
        self.assertEqual(row1[0], datetime(1970, 1, 1, 2, 30, 0))
        # time -> datetime with base date
        row2 = connector._normalize_row((time(14, 45, 30),))
        self.assertIsInstance(row2[0], datetime)
        self.assertEqual(row2[0], datetime(1970, 1, 1, 14, 45, 30))

    def test_normalize_row_converts_set_to_comma_separated_string(self):
        """MySQL SET columns return Python set; Oracle CLOB expects string (DPY-3002)."""
        connector = OracleADWConnector(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database_name=self.service_name,
        )
        row = connector._normalize_row(({"READ", "WRITE", "EXECUTE"},))
        self.assertIsInstance(row[0], str)
        self.assertEqual(sorted(row[0].split(",")), ["EXECUTE", "READ", "WRITE"])

