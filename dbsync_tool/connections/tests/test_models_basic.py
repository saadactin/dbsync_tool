from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from core.constants import DB_TYPE_CHOICES, DEFAULT_PORTS
from connections.models import DatabaseConnection, ConnectionTestLog
from unittest.mock import MagicMock, patch


class DatabaseConnectionModelTests(TestCase):
    """Test cases for DatabaseConnection model (moved from legacy `connections/tests.py`)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )

    def test_oracle_adw_in_db_type_choices_and_default_port(self):
        """oracle_adw should be a supported DB type with a sensible default port."""
        types = [t[0] for t in DB_TYPE_CHOICES]
        self.assertIn('oracle_adw', types)
        self.assertEqual(DEFAULT_PORTS.get('oracle_adw'), 1522)

    def test_create_connection(self):
        conn = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="testuser",
            password="testpass",
            database_name="testdb",
            created_by=self.user
        )
        self.assertIsNotNone(conn.id)
        self.assertEqual(conn.name, "Test DB")
        self.assertEqual(conn.db_type, "postgres")

    def test_password_encryption(self):
        conn = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="testuser",
            password="plain_password",
            database_name="testdb",
            created_by=self.user
        )
        # Password should be encrypted (Fernet encrypted strings start with 'gAAAAAB')
        self.assertTrue(conn.password.startswith('gAAAAAB'))
        self.assertNotEqual(conn.password, "plain_password")

    def test_password_decryption(self):
        conn = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="testuser",
            password="test_password_123",
            database_name="testdb",
            created_by=self.user
        )
        decrypted = conn.get_decrypted_password()
        self.assertEqual(decrypted, "test_password_123")

    def test_default_port(self):
        conn = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            username="testuser",
            password="testpass",
            database_name="testdb",
            created_by=self.user
        )
        self.assertEqual(conn.port, 5432)  # Default for postgres

    def test_oracle_adw_validation_success(self):
        """Creating an Oracle ADW connection with required fields should succeed."""
        conn = DatabaseConnection.objects.create(
            name="Oracle ADW",
            db_type="oracle_adw",
            host="adw.example.com",
            # Let model choose default port for oracle_adw if desired
            port=DEFAULT_PORTS['oracle_adw'],
            username="adw_user",
            password="secret_pass",
            # We treat database_name as the ADW service name / TNS alias
            database_name="myadw_high",
            created_by=self.user,
        )
        self.assertEqual(conn.db_type, "oracle_adw")
        self.assertEqual(conn.port, DEFAULT_PORTS['oracle_adw'])

    def test_oracle_adw_missing_required_fields_raises(self):
        """Oracle ADW connections must have host, port, username, password, and service name."""
        conn = DatabaseConnection(
            name="Oracle ADW Invalid",
            db_type="oracle_adw",
            host="",
            port=0,
            username="",
            password="",
            database_name="",
            created_by=self.user,
        )
        with self.assertRaises(ValidationError) as ctx:
            conn.full_clean()
        error_dict = ctx.exception.message_dict
        self.assertIn('host', error_dict)
        self.assertIn('port', error_dict)
        self.assertIn('username', error_dict)
        self.assertIn('password', error_dict)
        self.assertIn('database_name', error_dict)

    @patch("connections.connectors.get_connector")
    def test_test_connection_uses_connector_for_oracle_adw(self, mock_get_connector):
        """
        DatabaseConnection.test_connection should delegate to the connector for oracle_adw
        and return its boolean result.
        """
        conn = DatabaseConnection.objects.create(
            name="Oracle ADW",
            db_type="oracle_adw",
            host="adw.example.com",
            port=DEFAULT_PORTS["oracle_adw"],
            username="adw_user",
            password="secret_pass",
            database_name="myadw_high",
            created_by=self.user,
        )

        fake_connector = MagicMock()
        fake_connector.test_connection.return_value = True
        mock_get_connector.return_value = fake_connector

        result = conn.test_connection()

        self.assertTrue(result)
        mock_get_connector.assert_called_once()

    def test_port_validation(self):
        conn = DatabaseConnection(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=70000,  # Invalid port
            username="testuser",
            password="testpass",
            database_name="testdb",
            created_by=self.user
        )
        with self.assertRaises(ValidationError):
            conn.full_clean()

    def test_str_representation(self):
        conn = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="testuser",
            password="testpass",
            database_name="testdb",
            created_by=self.user
        )
        self.assertIn("Test DB", str(conn))
        self.assertIn("PostgreSQL", str(conn))


class ConnectionTestLogModelTests(TestCase):
    """Test cases for ConnectionTestLog model (moved from legacy `connections/tests.py`)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.conn = DatabaseConnection.objects.create(
            name="Test DB",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="testuser",
            password="testpass",
            database_name="testdb",
            created_by=self.user
        )

    def test_create_test_log(self):
        log = ConnectionTestLog.objects.create(
            connection=self.conn,
            status='success',
            tested_by=self.user
        )
        self.assertIsNotNone(log.id)
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.connection, self.conn)

    def test_test_log_relationship(self):
        ConnectionTestLog.objects.create(
            connection=self.conn,
            status='success',
            tested_by=self.user
        )
        ConnectionTestLog.objects.create(
            connection=self.conn,
            status='failed',
            error_message="Connection timeout",
            tested_by=self.user
        )
        self.assertEqual(self.conn.test_logs.count(), 2)

