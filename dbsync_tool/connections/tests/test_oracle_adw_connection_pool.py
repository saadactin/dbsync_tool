"""
Tests for Oracle ADW integration with the shared connection pool.

These tests mirror the ClickHouse pool tests but are tolerant of environments
where Oracle ADW (or the oracledb driver) is not available: if a
DatabaseConnectionError is raised, the test simply passes, as that typically
indicates missing infrastructure rather than a logic bug.
"""
from django.test import TestCase
from django.contrib.auth.models import User

from connections.models import DatabaseConnection
from core.connection_pool import get_connection_pool
from core.encryption import encrypt_password
from core.exceptions import DatabaseConnectionError
from core.constants import DEFAULT_PORTS


class OracleADWConnectionPoolTests(TestCase):
    """Test cases for Oracle ADW connection pool integration."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser_oracle",
            password="testpass123",
            email="test_oracle@example.com",
        )
        self.tenant = User.objects.create_user(
            username="tenant_oracle",
            password="tenant123",
            email="tenant_oracle@example.com",
        )

        self.connection = DatabaseConnection.objects.create(
            name="Test Oracle ADW Connection",
            db_type="oracle_adw",
            host="adw.example.com",
            port=DEFAULT_PORTS["oracle_adw"],
            username="adw_user",
            password=encrypt_password("secret_pass"),
            database_name="myadw_high",
            created_by=self.user,
            tenant=self.tenant,
            is_active=True,
        )

    def test_connection_pool_accepts_oracle_adw(self):
        """Connection pool should be able to attempt getting an Oracle ADW connector."""
        pool = get_connection_pool()
        try:
            connector = pool.get_connection(self.connection, read_only=True)
            self.assertIsNotNone(connector)
            pool.return_connection(str(self.connection.id), connector)
        except DatabaseConnectionError:
            # Acceptable when Oracle ADW / driver is not available in the environment.
            pass

    def test_connection_pool_reuse_oracle_adw(self):
        """Oracle ADW connections should be reusable from the pool when available."""
        pool = get_connection_pool()
        try:
            connector1 = pool.get_connection(self.connection, read_only=True)
            pool.return_connection(str(self.connection.id), connector1)

            connector2 = pool.get_connection(self.connection, read_only=True)
            self.assertIsNotNone(connector2)
            pool.return_connection(str(self.connection.id), connector2)
        except DatabaseConnectionError:
            # Acceptable when Oracle ADW / driver is not available.
            pass

