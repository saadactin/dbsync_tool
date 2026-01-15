from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
import os
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Creates the initial admin user (saadsayyed)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            type=str,
            help='Password for admin user (or set ADMIN_PASSWORD env var)',
        )
        parser.add_argument(
            '--email',
            type=str,
            default='saadsayyed@example.com',
            help='Email for admin user',
        )
    
    def handle(self, *args, **options):
        username = 'saadsayyed'
        email = options.get('email', 'saadsayyed@example.com')
        password = options.get('password') or os.environ.get('ADMIN_PASSWORD')
        
        # Check if user exists
        if User.objects.filter(username=username).exists():
            logger.info(f'Admin user "{username}" already exists. Skipping creation.')
            self.stdout.write(
                self.style.WARNING(f'Admin user "{username}" already exists.')
            )
            return
        
        # Get password
        if not password:
            logger.error('Admin user creation failed: Password required')
            self.stdout.write(
                self.style.ERROR('Password required. Use --password or set ADMIN_PASSWORD env var.')
            )
            raise CommandError('Password required')
        
        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=True,
                is_superuser=True,
            )
            logger.info(f'Successfully created admin user "{username}" with email "{email}"')
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created admin user "{username}"')
            )
        except Exception as e:
            logger.error(f'Error creating admin user: {str(e)}', exc_info=True)
            raise CommandError(f'Error creating admin user: {str(e)}')

