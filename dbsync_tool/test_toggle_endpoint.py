"""
Test script to diagnose and fix the toggle endpoint issue
Run: python test_toggle_endpoint.py
"""
import os
import sys
import django

# Fix Windows console encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.test import RequestFactory, Client
from django.contrib.auth.models import User
from core.models import NotificationRecipient
from core.middleware.request_validation import RequestValidationMiddleware
import json

print("="*70)
print("TOGGLE ENDPOINT DIAGNOSTIC TEST")
print("="*70)

# Create test user and recipient
print("\n1. Setting up test data...")
user, _ = User.objects.get_or_create(username='testuser', defaults={'is_staff': True})
user.set_password('testpass')
user.save()

recipient, _ = NotificationRecipient.objects.get_or_create(
    email='test@example.com',
    defaults={'name': 'Test User', 'is_active': True}
)
print(f"   ✓ Created recipient: {recipient.email} (ID: {recipient.id}, Active: {recipient.is_active})")

# Test 1: Direct middleware test
print("\n2. Testing middleware directly...")
factory = RequestFactory()

test_cases = [
    {
        'name': 'PATCH with application/json header, no body',
        'request': factory.patch(
            f'/api/notification-recipients/{recipient.id}/toggle/',
            content_type='application/json'
        )
    },
    {
        'name': 'PATCH with application/json header, empty dict body',
        'request': factory.patch(
            f'/api/notification-recipients/{recipient.id}/toggle/',
            data='{}',
            content_type='application/json'
        )
    },
    {
        'name': 'PATCH with application/json header, no content-length',
        'request': factory.patch(
            f'/api/notification-recipients/{recipient.id}/toggle/',
            content_type='application/json',
            CONTENT_LENGTH='0'
        )
    },
]

middleware = RequestValidationMiddleware(lambda req: None)

for i, test in enumerate(test_cases, 1):
    print(f"\n   Test {i}: {test['name']}")
    request = test['request']
    print(f"   - Content-Type: {request.META.get('CONTENT_TYPE', 'NOT SET')}")
    print(f"   - Content-Length: {request.META.get('CONTENT_LENGTH', 'NOT SET')}")
    print(f"   - Body: {request.body}")

    result = middleware.process_request(request)

    if result is None:
        print(f"   ✓ PASSED - Middleware allowed the request")
    else:
        print(f"   ✗ FAILED - Middleware rejected with status {result.status_code}")
        print(f"   Response: {result.content.decode()}")

# Test 2: Full endpoint test with authenticated client
print("\n3. Testing full endpoint with authenticated client...")
client = Client()
client.force_login(user)

print(f"   Recipient before: ID={recipient.id}, Active={recipient.is_active}")

response = client.patch(
    f'/api/notification-recipients/{recipient.id}/toggle/',
    content_type='application/json'
)

print(f"   Response status: {response.status_code}")
print(f"   Response body: {response.content.decode()}")

if response.status_code == 200:
    recipient.refresh_from_db()
    print(f"   Recipient after: ID={recipient.id}, Active={recipient.is_active}")
    print(f"   ✓ ENDPOINT WORKS!")
else:
    print(f"   ✗ ENDPOINT FAILED")

# Test 3: Simulate exact browser request
print("\n4. Simulating exact browser request...")
response = client.patch(
    f'/api/notification-recipients/{recipient.id}/toggle/',
    HTTP_CONTENT_TYPE='application/json',
    HTTP_X_CSRFTOKEN='dummy-token'
)

print(f"   Response status: {response.status_code}")
print(f"   Response body: {response.content.decode()}")

if response.status_code == 200:
    print(f"   ✓ BROWSER SIMULATION WORKS!")
else:
    print(f"   ✗ BROWSER SIMULATION FAILED")

# Test 4: Check view directly
print("\n5. Testing view function directly...")
from core.views import notification_recipients_toggle

factory = RequestFactory()
request = factory.patch(
    f'/api/notification-recipients/{recipient.id}/toggle/',
    content_type='application/json'
)
request.user = user

try:
    response = notification_recipients_toggle(request, recipient.id)
    print(f"   Response status: {response.status_code}")
    print(f"   Response body: {response.content.decode()}")

    if response.status_code == 200:
        print(f"   ✓ VIEW FUNCTION WORKS!")
    else:
        print(f"   ✗ VIEW FUNCTION FAILED")
except Exception as e:
    print(f"   ✗ VIEW FUNCTION ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("DIAGNOSIS COMPLETE")
print("="*70)

# Cleanup
print("\nCleaning up test data...")
recipient.delete()
print("Done!")
