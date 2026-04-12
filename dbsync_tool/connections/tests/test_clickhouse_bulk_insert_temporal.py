"""Unit tests for ClickHouse bulk_insert temporal column handling (Date32 / DateTime64)."""
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import Mock

from django.test import TestCase

from connections.connectors.base import ColumnInfo
from connections.connectors.clickhouse import ClickHouseConnector


class ClickHouseBulkInsertTemporalTests(TestCase):
    def setUp(self):
        self.connector = ClickHouseConnector(
            host="localhost",
            port=8123,
            username="default",
            password="",
            database_name="default",
        )

    def _run_bulk_insert_mocked(self, table_columns, columns, rows):
        self.connector._connection = Mock()
        self.connector.get_columns = Mock(return_value=table_columns)
        self.connector.bulk_insert(
            schema="db1",
            table="t1",
            columns=columns,
            rows=rows,
        )
        return self.connector._connection.insert.call_args

    def test_date32_row_keeps_python_date(self):
        call = self._run_bulk_insert_mocked(
            [
                ColumnInfo(
                    name="c_date",
                    data_type="Date32",
                    is_nullable=False,
                    is_primary_key=False,
                ),
            ],
            ["c_date"],
            [(date(9999, 12, 31),)],
        )
        data = call.kwargs.get("data") or call[1].get("data")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0][0], date(9999, 12, 31))

    def test_nullable_date32_normalized_inner_type(self):
        call = self._run_bulk_insert_mocked(
            [
                ColumnInfo(
                    name="c_date",
                    data_type="Nullable(Date32)",
                    is_nullable=True,
                    is_primary_key=False,
                ),
            ],
            ["c_date"],
            [(date(2024, 1, 15),)],
        )
        data = call.kwargs.get("data") or call[1].get("data")
        self.assertEqual(data[0][0], date(2024, 1, 15))

    def test_datetime64_column_uses_datetime_not_date_only_branch(self):
        call = self._run_bulk_insert_mocked(
            [
                ColumnInfo(
                    name="c_ts",
                    data_type="DateTime64(6, 'UTC')",
                    is_nullable=False,
                    is_primary_key=False,
                ),
            ],
            ["c_ts"],
            [(datetime(9999, 12, 31, 23, 59, 59, 999999),)],
        )
        data = call.kwargs.get("data") or call[1].get("data")
        self.assertIsInstance(data[0][0], datetime)
        self.assertEqual(data[0][0].year, 9999)

    def test_normalize_value_timedelta_to_string(self):
        td = timedelta(days=1, hours=2)
        self.assertEqual(self.connector._normalize_value(td), str(td))

    def test_uuid_column_hyphenated_string_becomes_uuid_object(self):
        u = uuid.UUID("aa2b5f2a-65a9-42ac-98aa-0ecf58cafc64")
        call = self._run_bulk_insert_mocked(
            [
                ColumnInfo(
                    name="col_uuid",
                    data_type="UUID",
                    is_nullable=False,
                    is_primary_key=False,
                ),
            ],
            ["col_uuid"],
            [("aa2b5f2a-65a9-42ac-98aa-0ecf58cafc64",)],
        )
        data = call.kwargs.get("data") or call[1].get("data")
        self.assertEqual(data[0][0], u)

    def test_normalize_value_psycopg_range_to_string(self):
        FakeRange = type(
            "DateRange",
            (),
            {
                "__module__": "psycopg2._range",
                "__str__": lambda self: "[2010-01-01,)",
            },
        )
        fr = FakeRange()
        self.assertEqual(self.connector._normalize_value(fr), "[2010-01-01,)")
