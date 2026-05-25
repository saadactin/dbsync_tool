#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick test script for notification features.
Run: python test_notification_features.py
"""

import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.core.mail import send_mail
from django.conf import settings
from core.models import NotificationRecipient


def test_email_config():
    """Test if email settings are configured."""
    print("=" * 60)
    print("Testing Email Configuration")
    print("=" * 60)

    required_settings = [
        'EMAIL_BACKEND',
        'EMAIL_HOST',
        'EMAIL_PORT',
        'EMAIL_HOST_USER',
        'DEFAULT_FROM_EMAIL'
    ]

    all_configured = True
    for setting in required_settings:
        value = getattr(settings, setting, None)
        status = "[OK]" if value else "[FAIL]"
        print(f"{status} {setting}: {value if value else 'NOT SET'}")
        if not value:
            all_configured = False

    print()
    if all_configured:
        print("[OK] All email settings configured")
    else:
        print("[FAIL] Some email settings missing - check your .env file")

    return all_configured


def test_notification_model():
    """Test NotificationRecipient model."""
    print("\n" + "=" * 60)
    print("Testing NotificationRecipient Model")
    print("=" * 60)

    try:
        # Count recipients
        count = NotificationRecipient.objects.count()
        active_count = NotificationRecipient.objects.filter(is_active=True).count()

        print(f"[OK] Model accessible")
        print(f"  Total recipients: {count}")
        print(f"  Active recipients: {active_count}")

        if count > 0:
            print("\nCurrent recipients:")
            for recipient in NotificationRecipient.objects.all():
                status = "Active" if recipient.is_active else "Inactive"
                name_part = f" ({recipient.name})" if recipient.name else ""
                print(f"  - {recipient.email}{name_part} - {status}")
        else:
            print("\n  No recipients configured yet")
            print("  Add recipients via: http://localhost:8004/notifications/")

        return True

    except Exception as e:
        print(f"[FAIL] Error accessing model: {e}")
        return False


def test_email_recipients():
    """Test getting all email recipients (DB + env)."""
    print("\n" + "=" * 60)
    print("Testing Email Recipients Aggregation")
    print("=" * 60)

    try:
        # Get DB recipients
        db_emails = list(
            NotificationRecipient.objects
            .filter(is_active=True)
            .values_list('email', flat=True)
        )

        # Get env recipients
        env_emails = getattr(settings, 'ADMIN_EMAILS', [])

        # Merge
        all_emails = list(set(db_emails + env_emails))

        print(f"Database recipients: {len(db_emails)}")
        for email in db_emails:
            print(f"  - {email}")

        print(f"\nEnvironment ADMIN_EMAILS: {len(env_emails)}")
        for email in env_emails:
            print(f"  - {email}")

        print(f"\nTotal unique recipients: {len(all_emails)}")

        if not all_emails:
            print("\n[WARNING] No recipients configured!")
            print("  Shutdown alerts will not be sent.")
            print("  Action: Add recipients at http://localhost:8004/notifications/")
            print("         or set ADMIN_EMAILS in .env")

        return len(all_emails) > 0

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_send_email():
    """Test sending an actual email."""
    print("\n" + "=" * 60)
    print("Testing Email Sending")
    print("=" * 60)

    response = input("Send a test email? (y/n): ").strip().lower()
    if response != 'y':
        print("Skipped.")
        return True

    try:
        # Get recipients
        db_emails = list(
            NotificationRecipient.objects
            .filter(is_active=True)
            .values_list('email', flat=True)
        )
        env_emails = getattr(settings, 'ADMIN_EMAILS', [])
        all_emails = list(set(db_emails + env_emails))

        if not all_emails:
            print("[FAIL] No recipients to send to!")
            return False

        print(f"Sending test email to {len(all_emails)} recipient(s)...")

        send_mail(
            subject="[DB Sync Tool] Test Email - Notification System",
            message="This is a test email from the DB Sync Tool notification system.\n\n"
                    "If you received this, email alerts are working correctly!",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=all_emails,
            fail_silently=False
        )

        print("[OK] Email sent successfully!")
        print(f"  Recipients: {', '.join(all_emails)}")
        print("\n  Check your inbox!")

        return True

    except Exception as e:
        print(f"[FAIL] Failed to send email: {e}")
        print("\nTroubleshooting:")
        print("  1. Check .env email settings")
        print("  2. Verify SMTP credentials")
        print("  3. If using Gmail, ensure App Password is used (not regular password)")
        print("  4. Check logs/email_errors.log for details")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("DB Sync Tool - Notification Features Test Suite")
    print("=" * 60)

    results = {
        "Email Config": test_email_config(),
        "Notification Model": test_notification_model(),
        "Email Recipients": test_email_recipients(),
    }

    # Only offer to send test email if previous tests pass
    if all(results.values()):
        results["Send Email"] = test_send_email()

    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} - {test_name}")

    print("\n" + "=" * 60)

    if all(results.values()):
        print("[OK] All tests passed! Notification system is ready.")
        print("\nNext steps:")
        print("  1. Start monitored server: python manage.py runserver_monitored")
        print("  2. Manage recipients: http://localhost:8004/notifications/")
    else:
        print("[FAIL] Some tests failed. Please fix the issues above.")
        print("\nRefer to NOTIFICATION_FEATURES.md for troubleshooting.")


if __name__ == '__main__':
    main()
