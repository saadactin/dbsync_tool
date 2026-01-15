from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from accounts.models import UserProfile, Role
import os
import getpass
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Creates the initial admin user (saadsayyed)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            type=str,
            help='Password for admin user (or set ADMIN_PASSWORD env var, or enter interactively)',
        )
        parser.add_argument(
            '--email',
            type=str,
            default='saadsayyed@example.com',
            help='Email for admin user',
        )
        parser.add_argument(
            '--username',
            type=str,
            default='saadsayyed',
            help='Username for admin user (default: saadsayyed)',
        )
    
    def handle(self, *args, **options):
        username = options.get('username', 'saadsayyed')
        email = options.get('email', 'saadsayyed@example.com')
        password = options.get('password') or os.environ.get('ADMIN_PASSWORD')
        
        # Check if user exists
        if User.objects.filter(username=username).exists():
            logger.info(f'Admin user "{username}" already exists. Skipping creation.')
            self.stdout.write(
                self.style.WARNING(f'Admin user "{username}" already exists.')
            )
            return
        
        # Get password interactively if not provided
        if not password:
            try:
                password = getpass.getpass('Enter password for admin user: ')
                if not password:
                    logger.error('Admin user creation failed: Password required')
                    self.stdout.write(
                        self.style.ERROR('Password cannot be empty.')
                    )
                    raise CommandError('Password required')
                # Confirm password
                password_confirm = getpass.getpass('Confirm password: ')
                if password != password_confirm:
                    logger.error('Admin user creation failed: Passwords do not match')
                    self.stdout.write(
                        self.style.ERROR('Passwords do not match.')
                    )
                    raise CommandError('Passwords do not match')
            except (KeyboardInterrupt, EOFError):
                self.stdout.write(self.style.ERROR('\nOperation cancelled.'))
                raise CommandError('Operation cancelled')
        
        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=True,
                is_superuser=True,
            )
            
            # Create UserProfile with Super Admin role
            UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': Role.SUPER_ADMIN,
                    'tenant': None,  # Super Admin has no tenant
                }
            )
            
            logger.info(f'Successfully created admin user "{username}" with email "{email}" and Super Admin role')
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created admin user "{username}" with Super Admin role')
            )
        except Exception as e:
            logger.error(f'Error creating admin user: {str(e)}', exc_info=True)
            raise CommandError(f'Error creating admin user: {str(e)}')

