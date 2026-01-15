"""
Management command to delete all users, connections, and sync jobs
Use with caution - this will delete ALL data!
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import UserProfile
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncSchedule, SyncExecution, SyncCheckpoint
from django.db import transaction
import sys


class Command(BaseCommand):
    help = 'Delete all users (including superadmin), connections, and sync jobs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion (required to prevent accidental deletion)',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(
                self.style.ERROR(
                    'This command will delete ALL users, connections, and sync jobs!\n'
                    'To confirm, run: python manage.py clear_all_data --confirm'
                )
            )
            sys.exit(1)

        self.stdout.write(self.style.WARNING('Starting data deletion...'))

        with transaction.atomic():
            # Delete in correct order to handle foreign key constraints
            
            # 1. Delete sync job related data first
            self.stdout.write('Deleting sync job executions...')
            execution_count = SyncExecution.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {execution_count} execution(s)'))

            self.stdout.write('Deleting sync checkpoints...')
            checkpoint_count = SyncCheckpoint.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {checkpoint_count} checkpoint(s)'))

            self.stdout.write('Deleting sync job tables...')
            job_table_count = SyncJobTable.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {job_table_count} job table(s)'))

            self.stdout.write('Deleting sync schedules...')
            schedule_count = SyncSchedule.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {schedule_count} schedule(s)'))

            self.stdout.write('Deleting sync jobs...')
            job_count = SyncJob.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {job_count} sync job(s)'))

            # 2. Delete connections
            self.stdout.write('Deleting database connections...')
            connection_count = DatabaseConnection.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {connection_count} connection(s)'))

            # 3. Delete user profiles (must be deleted before users due to foreign key)
            self.stdout.write('Deleting user profiles...')
            profile_count = UserProfile.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {profile_count} user profile(s)'))

            # 4. Delete all users (including superadmin)
            self.stdout.write('Deleting all users (including superadmin)...')
            user_count = User.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'  Deleted {user_count} user(s)'))

        self.stdout.write(
            self.style.SUCCESS(
                '\nAll data deleted successfully!\n'
                'You can now start fresh by creating a new superadmin user.'
            )
        )

