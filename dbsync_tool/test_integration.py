"""
Integration test script for Day 4
Run with: python manage.py shell < test_integration.py
"""
from connections.models import DatabaseConnection, ConnectionTestLog
from django.contrib.auth.models import User
from core.constants import DB_TYPE_CHOICES, DEFAULT_PORTS
from core.encryption import encrypt_password, decrypt_password
from core.exceptions import EncryptionError

print("=" * 60)
print("Day 4 Integration Tests")
print("=" * 60)

# Test 1: Constants
print("\n1. Testing Constants...")
assert len(DB_TYPE_CHOICES) == 3, "Should have 3 database types"
assert DEFAULT_PORTS['postgres'] == 5432
assert DEFAULT_PORTS['mysql'] == 3306
assert DEFAULT_PORTS['sqlserver'] == 1433
print("[OK] Constants test passed")

# Test 2: Encryption
print("\n2. Testing Encryption...")
test_passwords = ["test123", "MyP@ssw0rd!", "very_long_password_123456789"]
for pwd in test_passwords:
    encrypted = encrypt_password(pwd)
    decrypted = decrypt_password(encrypted)
    assert decrypted == pwd, f"Encryption failed for: {pwd}"
print("[OK] Encryption test passed")

# Test 3: Models
print("\n3. Testing Models...")
user = User.objects.first()
if not user:
    user = User.objects.create_user('testuser', 'test@test.com', 'testpass')

# Create connections for all 3 types
for db_type, display_name in DB_TYPE_CHOICES:
    conn = DatabaseConnection.objects.create(
        name=f"Test {display_name}",
        db_type=db_type,
        host="localhost",
        port=DEFAULT_PORTS[db_type],
        username="testuser",
        password="testpass123",
        database_name="testdb",
        created_by=user
    )
    assert conn.get_decrypted_password() == "testpass123"
    print(f"  [OK] Created {display_name} connection")

print("[OK] Models test passed")

# Test 4: Test Logs
print("\n4. Testing Test Logs...")
conn = DatabaseConnection.objects.first()
log = ConnectionTestLog.objects.create(
    connection=conn,
    status='success',
    tested_by=user
)
assert log.connection == conn
print("[OK] Test logs test passed")

print("\n" + "=" * 60)
print("All Integration Tests Passed!")
print("=" * 60)

