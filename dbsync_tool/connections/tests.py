from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from connections.models import DatabaseConnection, ConnectionTestLog
from core.encryption import encrypt_password, decrypt_password


class DatabaseConnectionModelTests(TestCase):
    """Test cases for DatabaseConnection model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
    
    def test_create_connection(self):
        """Test creating a database connection"""
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
        """Test that password is encrypted on save"""
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
        """Test that password can be decrypted"""
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
        """Test that default port is set if not provided"""
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
        """Test port validation"""
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
        """Test string representation of model"""
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
    """Test cases for ConnectionTestLog model"""
    
    def setUp(self):
        """Set up test data"""
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
        """Test creating a test log"""
        log = ConnectionTestLog.objects.create(
            connection=self.conn,
            status='success',
            tested_by=self.user
        )
        self.assertIsNotNone(log.id)
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.connection, self.conn)
    
    def test_test_log_relationship(self):
        """Test relationship between connection and test logs"""
        log1 = ConnectionTestLog.objects.create(
            connection=self.conn,
            status='success',
            tested_by=self.user
        )
        log2 = ConnectionTestLog.objects.create(
            connection=self.conn,
            status='failed',
            error_message="Connection timeout",
            tested_by=self.user
        )
        self.assertEqual(self.conn.test_logs.count(), 2)
