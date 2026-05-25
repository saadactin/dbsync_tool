"""
Custom management command to run Django development server with crash/shutdown monitoring.

Usage:
    python manage.py runserver_monitored

When the server stops (gracefully or crashes), sends an email alert to:
- All active NotificationRecipient emails from database
- Fallback ADMIN_EMAILS from .env

CRITICAL: Email is sent BEFORE shutdown completes to ensure delivery.
"""

import sys
import os
import subprocess
import traceback
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.mail import send_mail

# NO SIGNAL HANDLERS - They are unreliable on Windows for KeyboardInterrupt
# Instead, we use try/except KeyboardInterrupt which is GUARANTEED to catch Ctrl+C


class Command(BaseCommand):
    help = "Run Django dev server with crash/shutdown email monitoring (catches Ctrl+C)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--port',
            type=str,
            default='8004',
            help='Port to run the server on (default: 8004)'
        )
        parser.add_argument(
            '--host',
            type=str,
            default='127.0.0.1',
            help='Host to bind to (default: 127.0.0.1)'
        )

    def handle(self, *args, **options):
        port = options['port']
        host = options['host']

        self.stdout.write("=" * 70)
        self.stdout.write(
            self.style.SUCCESS(f"  Starting MONITORED Django server on {host}:{port}")
        )
        self.stdout.write(
            self.style.WARNING(f"  Email alerts will be sent on shutdown/crash")
        )
        self.stdout.write(
            self.style.WARNING(f"  Press Ctrl+C to stop (email will be sent BEFORE shutdown)")
        )
        self.stdout.write("=" * 70)
        self.stdout.write("")

        base_dir = Path(settings.BASE_DIR)
        manage_py = base_dir / "manage.py"

        cmd = [
            sys.executable,
            str(manage_py),
            "runserver",
            f"{host}:{port}",
            "--noreload"  # Disable auto-reloader to prevent double-process issues
        ]

        process = None
        shutdown_reason = "unknown"

        try:
            # Start subprocess
            process = subprocess.Popen(
                cmd,
                stdout=sys.stdout,
                stderr=sys.stderr,
                cwd=str(base_dir)
            )

            # Wait for process - this is where KeyboardInterrupt will be raised
            exit_code = process.wait()

            # Process exited on its own
            if exit_code == 0:
                shutdown_reason = "graceful_shutdown"
            else:
                shutdown_reason = f"crashed_exit_code_{exit_code}"

        except KeyboardInterrupt:
            # THIS IS THE CRITICAL PATH - Ctrl+C always raises KeyboardInterrupt here
            shutdown_reason = "manual_shutdown_ctrl_c"

            self.stdout.write("")
            self.stdout.write(self.style.WARNING("=" * 70))
            self.stdout.write(self.style.WARNING("  Ctrl+C detected! Shutting down..."))
            self.stdout.write(self.style.WARNING("=" * 70))
            self.stdout.write("")

            # Terminate subprocess FIRST
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            # THEN send email (this happens BEFORE we exit)
            self._send_shutdown_email(host, port, shutdown_reason)

            # Exit cleanly
            sys.exit(0)

        except Exception as e:
            shutdown_reason = f"unexpected_exception_{type(e).__name__}"
            self.stderr.write(self.style.ERROR(f"\nServer crashed with exception: {e}"))

            # Terminate subprocess
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    pass

            # Send email about crash
            self._send_shutdown_email(host, port, shutdown_reason)

            # Re-raise so traceback is visible
            raise

        else:
            # Normal exit (no exception) - send email
            self._send_shutdown_email(host, port, shutdown_reason)

    def _send_shutdown_email(self, host, port, reason):
        """
        Send email alert about server shutdown.
        This method MUST complete before the process exits.
        """
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("=" * 70))
        self.stdout.write(self.style.WARNING("  Sending shutdown alert email..."))
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
                self.stdout.write(f"  Warning: Could not query DB recipients: {e}")

            # Get env fallback
            env_emails = getattr(settings, 'ADMIN_EMAILS', [])

            # Merge and deduplicate
            all_emails = list(set(db_emails + env_emails))

            if not all_emails:
                self.stdout.write(
                    self.style.ERROR("  ERROR: No recipients configured!")
                )
                self.stdout.write(
                    "  Add recipients at: http://localhost:8004/notifications/"
                )
                self.stdout.write(
                    "  Or set ADMIN_EMAILS in .env"
                )
                self._log_email_error("No recipients configured")
                return

            # Build email
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            project_name = "DB Sync Tool"

            subject = f"[{project_name}] Server Shutdown - {reason}"

            message = f"""
Server Shutdown Notification
{'=' * 60}

Project: {project_name}
Server: {host}:{port}
Timestamp: {timestamp}
Reason: {reason}

{'=' * 60}
This is an automated alert from the DB Sync Tool monitoring system.

To restart the server, run:
  python manage.py runserver_monitored
"""

            # Send email synchronously
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=all_emails,
                fail_silently=False
            )

            self.stdout.write(
                self.style.SUCCESS(f"  [OK] Email sent to {len(all_emails)} recipient(s):")
            )
            for email in all_emails:
                self.stdout.write(f"       - {email}")

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"  [FAIL] Email send failed: {e}")
            )
            self._log_email_error(f"SMTP Error: {e}\n{traceback.format_exc()}")

        self.stdout.write("=" * 70)
        self.stdout.write("")

    def _log_email_error(self, message):
        """
        Log email failure to file.
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

            self.stdout.write(f"  Error logged to: {log_file}")

        except Exception as log_err:
            self.stderr.write(f"  Could not write log: {log_err}")
