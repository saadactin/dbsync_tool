from django.test import SimpleTestCase

from sync_engine.flat_file_sync import FlatFileSyncExecutor


class _Execution:
    status = "pending"

    def save(self):
        return None


class _Job:
    id = "job"
    source_file_connection = None


class FlatFileTargetCompatTests(SimpleTestCase):
    def _executor(self, connector):
        return FlatFileSyncExecutor(_Job(), _Execution(), connector)

    def test_target_schema_postgres(self):
        conn = type("PostgresConnector", (), {})()
        self.assertEqual(self._executor(conn)._target_schema("file"), "public")

    def test_target_schema_mysql(self):
        conn = type("MySQLConnector", (), {"database_name": "appdb"})()
        self.assertEqual(self._executor(conn)._target_schema("file"), "appdb")

    def test_target_schema_sqlserver(self):
        conn = type("SQLServerConnector", (), {})()
        self.assertEqual(self._executor(conn)._target_schema("file"), "dbo")

    def test_target_schema_clickhouse(self):
        conn = type("ClickHouseConnector", (), {"database_name": "analytics"})()
        self.assertEqual(self._executor(conn)._target_schema("file"), "analytics")

    def test_target_schema_oracle(self):
        conn = type("OracleADWConnector", (), {"username": "admin"})()
        self.assertEqual(self._executor(conn)._target_schema("file"), "ADMIN")

