"""
Management command to fix encrypted passwords that can't be decrypted.
This re-encrypts all passwords with the current encryption key.
WARNING: This assumes you have the correct encryption key or want to reset passwords.
"""
from django.core.management.base import BaseCommand
from connections.models import DatabaseConnection
from core.encryption import EncryptionService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix encrypted passwords by re-encrypting them with current key'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually doing it',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-encryption even if password appears to be encrypted',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        self.stdout.write(self.style.WARNING('Starting password fix process...'))
        
        connections = DatabaseConnection.objects.all()
        fixed_count = 0
        error_count = 0
        
        encryption_service = EncryptionService()
        
        for conn in connections:
            try:
                # Try to decrypt current password
                try:
                    current_password = encryption_service.decrypt(conn.password)
                    if not force:
                        self.stdout.write(
                            self.style.SUCCESS(f'[OK] Connection "{conn.name}": Password decrypts successfully')
                        )
                        continue
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'[FORCE] Connection "{conn.name}": Re-encrypting')
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'[ERROR] Connection "{conn.name}": Cannot decrypt - {str(e)}')
                    )
                    self.stdout.write(
                        self.style.WARNING(f'  -> You will need to re-enter the password for this connection')
                    )
                    if not dry_run:
                        # Mark password as requiring reset using direct SQL update to bypass validation
                        from django.db import connection as db_connection
                        with db_connection.cursor() as cursor:
                            cursor.execute(
                                "UPDATE database_connections SET password = %s WHERE id = %s",
                                ['RESET_REQUIRED', str(conn.id)]
                            )
                        self.stdout.write(
                            self.style.WARNING(f'  -> Password cleared. Please edit connection to set new password.')
                        )
                    error_count += 1
                    continue
                
                # Re-encrypt with current key
                if not dry_run:
                    encrypted = encryption_service.encrypt(current_password)
                    conn.password = encrypted
                    conn.save()
                    fixed_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'[OK] Connection "{conn.name}": Re-encrypted successfully')
                    )
                else:
                    fixed_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'[DRY RUN] Would re-encrypt connection "{conn.name}"')
                    )
                    
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'[ERROR] Connection "{conn.name}": Error - {str(e)}')
                )
        
        self.stdout.write(self.style.SUCCESS(f'\nCompleted: {fixed_count} fixed, {error_count} errors'))
        if dry_run:
            self.stdout.write(self.style.WARNING('This was a dry run. Run without --dry-run to apply changes.'))

