from django.test import TestCase

from core.constants import DEFAULT_PORTS
from connections.forms import DatabaseConnectionForm


class SQLServerNamedInstanceHostFormTests(TestCase):
    def test_sqlserver_named_instance_host_valid(self):
        data = {
            "name": "SQLServer Named Instance Conn",
            "db_type": "sqlserver",
            "host": r"localhost\SQLEXPRESS",
            "port": DEFAULT_PORTS["sqlserver"],
            "username": "sa",
            "password": "root-password",
            "database_name": "testdb",
            "is_active": True,
        }

        form = DatabaseConnectionForm(data=data)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_sqlserver_named_instance_host_invalid_missing_instance(self):
        data = {
            "name": "SQLServer Named Instance Conn",
            "db_type": "sqlserver",
            # Trailing backslash is invalid for HOST\INSTANCE format
            "host": "localhost\\",
            "port": DEFAULT_PORTS["sqlserver"],
            "username": "sa",
            "password": "root-password",
            "database_name": "testdb",
            "is_active": True,
        }

        form = DatabaseConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("host", form.errors)

