from django.test import TestCase

from core.constants import DEFAULT_PORTS
from connections.forms import DatabaseConnectionForm


class DatabaseConnectionFormOracleADWTests(TestCase):
    """Tests for DatabaseConnectionForm behaviour with Oracle ADW (oracle_adw)."""

    def test_oracle_adw_choice_available_in_form(self):
        form = DatabaseConnectionForm()
        choices = [choice[0] for choice in form.fields["db_type"].choices]
        self.assertIn("oracle_adw", choices)

    def test_oracle_adw_form_valid_with_required_fields(self):
        data = {
            "name": "Oracle ADW Conn",
            "db_type": "oracle_adw",
            "host": "adw.example.com",
            "port": DEFAULT_PORTS["oracle_adw"],
            "username": "adw_user",
            "password": "secret_pass",
            # For Oracle ADW we treat database_name as the service name / TNS alias
            "database_name": "myadw_high",
            "is_active": True,
        }
        form = DatabaseConnectionForm(data=data)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_oracle_adw_form_valid_with_service_name_containing_dots(self):
        """Oracle ADW service names like xxx.adb.oraclecloud.com are allowed."""
        data = {
            "name": "Oracle ADW Conn",
            "db_type": "oracle_adw",
            "host": "adb.ap-mumbai-1.oraclecloud.com",
            "port": DEFAULT_PORTS["oracle_adw"],
            "username": "admin",
            "password": "secret",
            "database_name": "ge3cf99f4b998df_ktestadw_high.adb.oraclecloud.com",
            "is_active": True,
        }
        form = DatabaseConnectionForm(data=data)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        self.assertEqual(
            form.cleaned_data["database_name"],
            "ge3cf99f4b998df_ktestadw_high.adb.oraclecloud.com",
        )

    def test_oracle_adw_missing_service_name_raises_error(self):
        data = {
            "name": "Oracle ADW Conn",
            "db_type": "oracle_adw",
            "host": "adw.example.com",
            "port": DEFAULT_PORTS["oracle_adw"],
            "username": "adw_user",
            "password": "secret_pass",
            "database_name": "",
            "is_active": True,
        }
        form = DatabaseConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("database_name", form.errors)
        # Some message indicating the field is required
        msg = form.errors["database_name"][0]
        self.assertIn("required", msg.lower(), msg=f"Expected a required message, got: {msg}")

    def test_oracle_adw_missing_username_raises_error(self):
        data = {
            "name": "Oracle ADW Conn",
            "db_type": "oracle_adw",
            "host": "adw.example.com",
            "port": DEFAULT_PORTS["oracle_adw"],
            "username": "",
            "password": "secret_pass",
            "database_name": "myadw_high",
            "is_active": True,
        }
        form = DatabaseConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)


class DatabaseConnectionFormMongoLocalTests(TestCase):
    def test_mongodb_local_allows_empty_user_pass_autofills_root_root(self):
        data = {
            "name": "mongo",
            "db_type": "mongodb",
            "host": "localhost",
            "port": DEFAULT_PORTS["mongodb"],
            "username": "",
            "password": "",
            "database_name": "",
            "is_active": True,
        }
        form = DatabaseConnectionForm(data=data)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        self.assertEqual(form.cleaned_data["username"], "root")
        self.assertEqual(form.cleaned_data["password"], "root")

    def test_mongodb_local_missing_password_only_is_invalid(self):
        data = {
            "name": "mongo",
            "db_type": "mongodb",
            "host": "localhost",
            "port": DEFAULT_PORTS["mongodb"],
            "username": "root",
            "password": "",
            "database_name": "",
            "is_active": True,
        }
        form = DatabaseConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_mongodb_non_local_requires_credentials(self):
        data = {
            "name": "mongo_remote",
            "db_type": "mongodb",
            "host": "192.168.1.10",
            "port": DEFAULT_PORTS["mongodb"],
            "username": "",
            "password": "",
            "database_name": "",
            "is_active": True,
        }
        form = DatabaseConnectionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

