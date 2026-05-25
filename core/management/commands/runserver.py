"""
Override Django's built-in runserver command to add email monitoring.

This replaces the default 'python manage.py runserver' with a monitored version.
When you press Ctrl+C, an email alert is sent BEFORE shutdown.

Usage:
    python manage.py runserver 8004
    python manage.py runserver
    python manage.py runserver 0.0.0.0:8000

All standard runserver arguments work normally.
"""

import sys
import os
import threading
import traceback
from datetime import datetime
from pathlib import Path

from django.core.management.commands.runserver import Command as RunserverCommand
from django.conf import settings
from django.core.mail import send_mail


class Command(RunserverCommand):
    """
    Extends Django's built-in runserver command with email monitoring.

    Email is sent on:
    - Manual shutdown (Ctrl+C)
    - Server crashes
    - Any unexpected termination
    """

    help = "Starts the development server with email alerts on shutdown (ENHANCED)"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_started = False
        self.shutdown_reason = "unknown"

    def handle(self, *args, **options):
        """
        Wrap the default runserver handle() with email monitoring.
        """
        # Extract host and port for email
        addrport = options.get('addrport', '127.0.0.1:8000')
        if ':' in addrport:
            self.host, port = addrport.rsplit(':', 1)
            self.port = port
        else:
            self.host = '127.0.0.1'
            self.port = addrport

        # Print startup banner
        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write(
            self.style.SUCCESS(
                f"  Django Development Server - EMAIL MONITORING ENABLED"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"  Server: {self.host}:{self.port}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"  Email alerts will be sent on shutdown/crash"
            )
        )
        self.stdout.write("=" * 70)
        self.stdout.write("")

        try:
            # Call the original Django runserver
            self.server_started = True
            super().handle(*args, **options)

            # If we reach here, server exited normally
            self.shutdown_reason = "graceful_shutdown"

        except KeyboardInterrupt:
            # Ctrl+C pressed - THIS IS THE CRITICAL PATH
            self.shutdown_reason = "manual_shutdown_ctrl_c"

            self.stdout.write("")
            self.stdout.write(self.style.WARNING("=" * 70))
            self.stdout.write(
                self.style.WARNING("  Ctrl+C detected! Shutting down server...")
            )
            self.stdout.write(self.style.WARNING("=" * 70))
            self.stdout.write("")

            # Send email BEFORE exiting
            self._send_shutdown_email()

            # Exit cleanly
            sys.exit(0)

        except Exception as e:
            # Unexpected crash
            self.shutdown_reason = f"crash_{type(e).__name__}"

            self.stderr.write("")
            self.stderr.write(self.style.ERROR("=" * 70))
            self.stderr.write(
                self.style.ERROR(f"  Server crashed: {type(e).__name__}")
            )
            self.stderr.write(self.style.ERROR("=" * 70))
            self.stderr.write("")

            # Send email about crash
            self._send_shutdown_email()

            # Re-raise to show traceback
            raise

    def _send_shutdown_email(self):
        """
        Send email alert about server shutdown.
        This runs synchronously BEFORE process exits.
        """
        if not self.server_started:
            # Server never started, skip email
            return

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("=" * 70))
        self.stdout.write(
            self.style.WARNING("  Sending shutdown notification email...")
        )
        self.stdout.write(self.style.WARNING("=" * 70))

        try:
            # Get DB recipients
            db_emails = []
            try:
                from core.models import NotificationRecipient
                db_emails = list(
                    NotificationRecipient.objects
                    .filter(is_active=True)
                    .values_list('email', flat=True)
                )
            except Exception as e:
                self.stdout.write(f"  Note: Could not query DB recipients: {e}")

            # Get env fallback
            env_emails = getattr(settings, 'ADMIN_EMAILS', [])

            # Merge and deduplicate
            all_emails = list(set(db_emails + env_emails))

            if not all_emails:
                self.stdout.write("")
                self.stdout.write(
                    self.style.ERROR("  [SKIP] No recipients configured")
                )
                self.stdout.write(
                    "  Add recipients: http://localhost:{}/notifications/".format(self.port)
                )
                self.stdout.write(
                    "  Or set ADMIN_EMAILS in .env file"
                )
                self._log_email_error("No recipients configured - email not sent")
                self.stdout.write("=" * 70)
                self.stdout.write("")
                return

            # Build email
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            project_name = "DB Sync Tool"

            subject = f"[{project_name}] Server Shutdown - {self.shutdown_reason}"

            message = f"""
Server Shutdown Notification
{'=' * 60}

Project: {project_name}
Server: {self.host}:{self.port}
Timestamp: {timestamp}
Reason: {self.shutdown_reason}

{'=' * 60}
This is an automated alert from the DB Sync Tool monitoring system.

To restart the server, run:
  python manage.py runserver {self.port}
"""

            # Send email synchronously
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=all_emails,
                fail_silently=False
            )

            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [OK] Email sent to {len(all_emails)} recipient(s):"
                )
            )
            for email in all_emails:
                self.stdout.write(f"       - {email}")
            self.stdout.write("")

        except Exception as e:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(f"  [FAIL] Email send error: {e}")
            )
            self._log_email_error(f"SMTP Error: {e}\n{traceback.format_exc()}")
            self.stdout.write("")

        self.stdout.write("=" * 70)
        self.stdout.write("")

    def _log_email_error(self, message):
        """
        Log email failure to file for debugging.
        """
        try:
            log_dir = Path(settings.BASE_DIR) / 'logs'
            log_dir.mkdir(exist_ok=True)

            log_file = log_dir / 'email_errors.log'

            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Error: {message}\n")
                f.write(f"{'=' * 80}\n")

            self.stdout.write(f"  Error logged to: logs/email_errors.log")

        except Exception as log_err:
            self.stderr.write(f"  Could not write error log: {log_err}")
