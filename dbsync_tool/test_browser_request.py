"""
Test exactly what the browser sends
"""
import os
import sys
import django

# Fix Windows encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import NotificationRecipient

print("Testing EXACT browser request pattern...")

# Setup
user = User.objects.filter(username='admin').first() or User.objects.create_superuser('admin', 'admin@test.com', 'admin')
recipient, _ = NotificationRecipient.objects.get_or_create(email='browser@test.com', defaults={'name': 'Browser Test', 'is_active': True})

client = Client()
client.force_login(user)

print(f"\nRecipient: {recipient.email} (ID: {recipient.id}, Active: {recipient.is_active})")

# Simulate exact fetch() call from JavaScript
print("\nSending PATCH request exactly as browser does...")
print("Headers:")
print("  Content-Type: application/json")
print("  X-CSRFToken: (token)")
print("Body: (empty)")

response = client.patch(
    f'/api/notification-recipients/{recipient.id}/toggle/',
    data='',  # Empty body
    content_type='application/json',
    HTTP_X_CSRFTOKEN='test-token'
)

print(f"\nResponse Status: {response.status_code}")
print(f"Response Headers: {dict(response.items())}")
print(f"Response Body: {response.content.decode()}")

if response.status_code == 200:
    print("\n✓ SUCCESS - Toggle works!")
    recipient.refresh_from_db()
    print(f"Recipient is now: {recipient.is_active}")
else:
    print("\n✗ FAILED - Toggle doesn't work")
    print("\nTrying without empty string body...")

    response2 = client.patch(
        f'/api/notification-recipients/{recipient.id}/toggle/',
        content_type='application/json',
        HTTP_X_CSRFTOKEN='test-token'
    )

    print(f"Response Status: {response2.status_code}")
    print(f"Response Body: {response2.content.decode()}")

    if response2.status_code == 200:
        print("\n✓ Works without explicit empty body")
    else:
        print("\n✗ Still fails")

# Cleanup
recipient.delete()
print("\nTest complete!")
