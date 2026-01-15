from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import UserProfile, Role
import os
import getpass
import sys

class Command(BaseCommand):
    help = 'Creates the initial super admin user (root)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='root',
            help='Username for super admin (default: root)'
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password (or set SUPER_ADMIN_PASSWORD env var)'
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Email address (default: username@example.com)'
        )
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Run non-interactively (requires --password or env var)'
        )
    
    def handle(self, *args, **options):
        username = options['username']
        email = options.get('email') or f'{username}@example.com'
        no_input = options.get('no_input', False)
        
        # Get password FIRST before any other operations
        password = options.get('password') or os.environ.get('SUPER_ADMIN_PASSWORD')
        
        if not password:
            if no_input:
                self.stdout.write(
                    self.style.ERROR('Password required. Use --password or set SUPER_ADMIN_PASSWORD env var.')
                )
                return
            
            # Ask for password first - flush output to ensure prompt is clear
            self.stdout.write(f'Creating super admin user: {username}')
            self.stdout.flush()
            sys.stdout.flush()
            
            # Use getpass with explicit prompt
            try:
                password = getpass.getpass(prompt='Password: ')
            except (KeyboardInterrupt, EOFError):
                self.stdout.write(self.style.ERROR('\nOperation cancelled.'))
                return
            
            if not password:
                self.stdout.write(self.style.ERROR('Password cannot be empty.'))
                return
            
            # Ask for confirmation
            self.stdout.flush()
            sys.stdout.flush()
            try:
                password_confirm = getpass.getpass(prompt='Password (again): ')
            except (KeyboardInterrupt, EOFError):
                self.stdout.write(self.style.ERROR('\nOperation cancelled.'))
                return
            
            if password != password_confirm:
                self.stdout.write(self.style.ERROR('Passwords do not match.'))
                return
        
        # Now check if user already exists
        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(f'User "{username}" already exists. Skipping creation.')
            )
            # Update profile if needed
            user = User.objects.get(username=username)
            if not hasattr(user, 'userprofile'):
                UserProfile.objects.create(
                    user=user,
                    role=Role.SUPER_ADMIN,
                    tenant=None
                )
                self.stdout.write(
                    self.style.SUCCESS(f'Created UserProfile for existing user "{username}"')
                )
            return
        
        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=True,
                is_superuser=True
            )
            
            # Create profile (signal will also create it, but ensure it's correct)
            profile, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': Role.SUPER_ADMIN,
                    'tenant': None
                }
            )
            if not created:
                # Update existing profile
                profile.role = Role.SUPER_ADMIN
                profile.tenant = None
                profile.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully created super admin user "{username}" with role {Role.SUPER_ADMIN}'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating super admin: {str(e)}')
            )
            raise

