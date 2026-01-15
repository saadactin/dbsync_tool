from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import UserProfile, Role
import os
import getpass

class Command(BaseCommand):
    help = 'Creates an admin user (tenant owner)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            required=True,
            help='Username for admin user'
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password (or set ADMIN_PASSWORD env var)'
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
        password = options.get('password') or os.environ.get('ADMIN_PASSWORD')
        email = options.get('email') or f'{username}@example.com'
        no_input = options.get('no_input', False)
        
        # Check if user already exists
        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(f'User "{username}" already exists. Skipping creation.')
            )
            # Update profile if needed
            user = User.objects.get(username=username)
            if not hasattr(user, 'userprofile'):
                UserProfile.objects.create(
                    user=user,
                    role=Role.ADMIN,
                    tenant=user
                )
                self.stdout.write(
                    self.style.SUCCESS(f'Created UserProfile for existing user "{username}"')
                )
            return
        
        # Get password
        if not password:
            if no_input:
                self.stdout.write(
                    self.style.ERROR('Password required. Use --password or set ADMIN_PASSWORD env var.')
                )
                return
            password = getpass.getpass('Password: ')
            password_confirm = getpass.getpass('Password (again): ')
            if password != password_confirm:
                self.stdout.write(self.style.ERROR('Passwords do not match.'))
                return
        
        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=True,
                is_superuser=False
            )
            
            # Create profile (signal will also create it, but ensure it's correct)
            profile, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': Role.ADMIN,
                    'tenant': user  # Admin is their own tenant
                }
            )
            if not created:
                # Update existing profile
                profile.role = Role.ADMIN
                profile.tenant = user
                profile.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully created admin user "{username}" with role {Role.ADMIN} (tenant: {username})'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating admin: {str(e)}')
            )
            raise

