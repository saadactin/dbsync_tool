from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from connections.models import DatabaseConnection, ConnectionTestLog


class DatabaseConnectionModelTests(TestCase):
    """Test cases for DatabaseConnection model (moved from legacy `connections/tests.py`)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )

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

