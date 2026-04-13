from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
import smtplib

class Command(BaseCommand):
    help = 'Test the email configuration'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('--- Email Configuration Debug ---'))
        self.stdout.write(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"EMAIL_HOST: {settings.EMAIL_HOST}")
        self.stdout.write(f"EMAIL_PORT: {settings.EMAIL_PORT}")
        self.stdout.write(f"EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"EMAIL_HOST_USER: {settings.EMAIL_HOST_USER}")
        self.stdout.write(f"DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"ADMIN_EMAILS: {settings.ADMIN_EMAILS}")
        
        # Test sending
        self.stdout.write('\nAttempting to send test email to saad.sayyed@actin.co.in...')
        try:
            sent = send_mail(
                'SyncArchitect System Test',
                'This is a diagnostic test email from the SyncArchitect system.',
                settings.DEFAULT_FROM_EMAIL,
                ['saad.sayyed@actin.co.in'],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f'Successfully sent {sent} email(s)!'))
        except smtplib.SMTPServerDisconnected:
            self.stdout.write(self.style.ERROR('Error: Connection unexpectedly closed by the server. This usually means the server rejected your credentials.'))
        except smtplib.SMTPAuthenticationError as e:
            self.stdout.write(self.style.ERROR(f'Authentication Error: {e}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to send email: {type(e).__name__}: {str(e)}'))
