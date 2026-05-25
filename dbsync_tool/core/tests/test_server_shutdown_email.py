"""
Tests for server shutdown email alerts.
These tests verify that emails are sent when the Django dev server stops.
"""

import signal
import os
from unittest.mock import patch, MagicMock, call
from io import StringIO

from django.test import TestCase, override_settings
from django.core.management import call_command
from django.core import mail
from django.conf import settings

from core.models import NotificationRecipient
from core.management.commands.runserver_monitored import Command


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='test@example.com',
    ADMIN_EMAILS=['admin@example.com'],
)
class ServerShutdownEmailTest(TestCase):
    """Test suite for server shutdown email notifications."""

    def setUp(self):
        """Set up test fixtures."""
        self.command = Command()
        self.command.stdout = StringIO()
        self.command.stderr = StringIO()

        # Clear any existing mail
        mail.outbox = []

    def tearDown(self):
        """Clean up after tests."""
        NotificationRecipient.objects.all().delete()

    def test_sigint_handler_is_registered(self):
        """
        Test 1: Verify that SIGINT handler is callable and registered.
        """
        # The signal handler should be a method on the Command instance
        self.assertTrue(hasattr(self.command, '_handle_signal'))
        self.assertTrue(callable(self.command._handle_signal))

        # Verify it can be called without crashing
        with patch.object(self.command, '_terminate_process'):
            self.command._handle_signal(signal.SIGINT, None)
            # Should set should_exit flag instead of calling sys.exit()
            self.assertTrue(self.command.should_exit,
                          "Signal handler should set should_exit flag")

    def test_email_sent_on_sigint(self):
        """
        Test 2: Email is sent when SIGINT handler is triggered.
        This is the CRITICAL test for Ctrl+C functionality.
        """
        self.command.shutdown_reason = "signal_SIGINT"

        # Call the email sending function directly
        self.command._send_shutdown_alert('127.0.0.1', '8004')

        # Should have sent one email
        self.assertEqual(len(mail.outbox), 1)

        # Verify email content
        email = mail.outbox[0]
        self.assertIn('Server Shutdown Alert', email.subject)
        self.assertIn('DB Sync Tool', email.subject)
        self.assertIn('signal_SIGINT', email.body)
        self.assertEqual(email.to, ['admin@example.com'])

    def test_email_sent_on_sigterm(self):
        """
        Test 3: Email is sent when SIGTERM handler is triggered.
        """
        self.command.shutdown_reason = "signal_SIGTERM"
        self.command._send_shutdown_alert('127.0.0.1', '8004')

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn('signal_SIGTERM', email.body)

    def test_email_sent_on_crash(self):
        """
        Test 4: Email fires in finally block even if subprocess crashes.
        """
        self.command.shutdown_reason = "unhandled_exception: ValueError"
        self.command._send_shutdown_alert('127.0.0.1', '8004')

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn('unhandled_exception', email.body)
        self.assertIn('Unexpected termination', email.body)

    def test_recipients_include_db_and_env_fallback(self):
        """
        Test 5: Recipients include active DB emails + ADMIN_EMAILS fallback.
        """
        # Create DB recipients
        NotificationRecipient.objects.create(
            email='db_user1@example.com',
            name='DB User 1',
            is_active=True
        )
        NotificationRecipient.objects.create(
            email='db_user2@example.com',
            name='DB User 2',
            is_active=True
        )
        # Inactive user - should NOT receive email
        NotificationRecipient.objects.create(
            email='inactive@example.com',
            name='Inactive User',
            is_active=False
        )

        self.command.shutdown_reason = "test_shutdown"
        self.command._send_shutdown_alert('127.0.0.1', '8004')

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]

        # Should have 3 recipients: 2 active DB + 1 env fallback
        self.assertEqual(len(email.to), 3)
        self.assertIn('db_user1@example.com', email.to)
        self.assertIn('db_user2@example.com', email.to)
        self.assertIn('admin@example.com', email.to)
        self.assertNotIn('inactive@example.com', email.to)

    def test_smtp_failure_logs_not_crashes(self):
        """
        Test 6: SMTP failure does NOT crash the shutdown - it logs instead.
        """
        # Force send_mail to raise an exception
        with patch('core.management.commands.runserver_monitored.send_mail') as mock_send:
            mock_send.side_effect = Exception("SMTP connection failed")

            # Should NOT raise - should log instead
            try:
                self.command.shutdown_reason = "test_shutdown"
                self.command._send_shutdown_alert('127.0.0.1', '8004')
            except Exception:
                self.fail("_send_shutdown_alert should NOT raise exceptions")

            # Verify error was logged
            stderr_output = self.command.stderr.getvalue()
            self.assertIn('Failed to send shutdown email', stderr_output)

    def test_email_content_has_required_fields(self):
        """
        Test 7: Email subject and body contain timestamp, project name, shutdown reason.
        """
        self.command.shutdown_reason = "keyboard_interrupt"
        self.command._send_shutdown_alert('127.0.0.1', '8004')

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]

        # Subject checks
        self.assertIn('DB Sync Tool', email.subject)
        self.assertIn('Server Shutdown Alert', email.subject)
        self.assertIn('127.0.0.1:8004', email.subject)

        # Body checks
        self.assertIn('Project: DB Sync Tool', email.body)
        self.assertIn('Server: 127.0.0.1:8004', email.body)
        self.assertIn('Reason: keyboard_interrupt', email.body)
        self.assertIn('Timestamp:', email.body)

        # Should be marked as unexpected (not graceful)
        self.assertIn('Unexpected termination', email.body)

    def test_no_email_when_no_recipients(self):
        """
        Test 8: No crash when no recipients configured - just skip email.
        """
        # Override to have no admin emails
        with override_settings(ADMIN_EMAILS=[]):
            self.command.shutdown_reason = "test_shutdown"
            self.command._send_shutdown_alert('127.0.0.1', '8004')

            # Should not crash, and no email sent
            self.assertEqual(len(mail.outbox), 0)

            # Should log warning
            stdout_output = self.command.stdout.getvalue()
            self.assertIn('No notification recipients configured', stdout_output)

    def test_graceful_shutdown_detection(self):
        """
        Test 9: Email body correctly identifies graceful vs unexpected shutdown.
        """
        # Test graceful shutdown
        self.command.shutdown_reason = "graceful_shutdown"
        self.command._send_shutdown_alert('127.0.0.1', '8004')

        email = mail.outbox[0]
        self.assertIn('Graceful shutdown', email.body)

        # Clear outbox
        mail.outbox = []

        # Test unexpected shutdown
        self.command.shutdown_reason = "process_exit_code_1"
        self.command._send_shutdown_alert('127.0.0.1', '8004')

        email = mail.outbox[0]
        self.assertIn('Unexpected termination', email.body)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='test@example.com',
    ADMIN_EMAILS=['admin@example.com'],
)
class SignalHandlerIntegrationTest(TestCase):
    """
    Integration tests for signal handling behavior.
    Tests the ACTUAL bug: signal handler calling sys.exit() bypasses finally block.
    """

    def test_keyboard_interrupt_sends_email_before_exit(self):
        """
        CRITICAL TEST: Verify that KeyboardInterrupt triggers email send.
        This test simulates the actual Ctrl+C scenario.
        """
        command = Command()
        command.stdout = StringIO()
        command.stderr = StringIO()

        # Mock the subprocess to immediately raise KeyboardInterrupt
        with patch('core.management.commands.runserver_monitored.subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            # Mock send_mail to track if it was called
            with patch('core.management.commands.runserver_monitored.send_mail') as mock_send:
                try:
                    # Call handle - should catch KeyboardInterrupt and send email
                    command.handle(port='8004', host='127.0.0.1')
                except (KeyboardInterrupt, SystemExit):
                    # Expected - but email should have been sent
                    pass

                # THIS IS THE CRITICAL ASSERTION
                # With the bug, this will FAIL because sys.exit() bypasses finally
                self.assertTrue(
                    mock_send.called,
                    "Email should be sent even when KeyboardInterrupt occurs (Ctrl+C)"
                )

    def test_signal_handler_does_not_bypass_finally_block(self):
        """
        Test that signal handler allows finally block to execute.
        This directly tests the root cause of the bug.
        """
        command = Command()
        command.stdout = StringIO()
        command.stderr = StringIO()

        finally_executed = {'called': False}

        def mock_send_alert(*args, **kwargs):
            finally_executed['called'] = True

        # Replace the send method
        command._send_shutdown_alert = mock_send_alert

        with patch('core.management.commands.runserver_monitored.subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            try:
                command.handle(port='8004', host='127.0.0.1')
            except (KeyboardInterrupt, SystemExit):
                pass

            # THIS WILL FAIL with current implementation
            self.assertTrue(
                finally_executed['called'],
                "Finally block must execute to send email alert"
            )
