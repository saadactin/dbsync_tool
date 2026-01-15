"""
Management command to delete all data from the database
Use with caution - this will delete ALL users, connections, sync jobs, etc.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncSchedule, SyncExecution, SyncExecutionLog, SyncCheckpoint
from accounts.models import UserProfile
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Delete all data from the database (users, connections, sync jobs, etc.)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep-super-admin',
            action='store_true',
            help='Keep the super admin user (if exists)',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion (required to actually delete)',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(
                self.style.ERROR(
                    'This command will delete ALL data. Use --confirm to proceed.'
                )
            )
            return

        self.stdout.write(self.style.WARNING('Starting data deletion...'))

        # Delete in order to respect foreign key constraints
        
        # 1. Delete sync execution logs
        self.stdout.write('Deleting sync execution logs...')
        deleted_logs = SyncExecutionLog.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_logs[0]} sync execution logs'))

        # 2. Delete sync checkpoints
        self.stdout.write('Deleting sync checkpoints...')
        deleted_checkpoints = SyncCheckpoint.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_checkpoints[0]} sync checkpoints'))

        # 3. Delete sync executions
        self.stdout.write('Deleting sync executions...')
        deleted_executions = SyncExecution.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_executions[0]} sync executions'))

        # 4. Delete sync schedules
        self.stdout.write('Deleting sync schedules...')
        deleted_schedules = SyncSchedule.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_schedules[0]} sync schedules'))

        # 5. Delete sync jobs
        self.stdout.write('Deleting sync jobs...')
        deleted_jobs = SyncJob.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_jobs[0]} sync jobs'))

        # 6. Delete database connections
        self.stdout.write('Deleting database connections...')
        deleted_connections = DatabaseConnection.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_connections[0]} database connections'))

        # 7. Delete user profiles
        self.stdout.write('Deleting user profiles...')
        deleted_profiles = UserProfile.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_profiles[0]} user profiles'))

        # 8. Delete users (except super admin if requested)
        self.stdout.write('Deleting users...')
        if options['keep_super_admin']:
            # Find super admin users
            super_admins = UserProfile.objects.filter(role='super_admin')
            super_admin_user_ids = [profile.user_id for profile in super_admins]
            
            users_to_delete = User.objects.exclude(id__in=super_admin_user_ids)
            deleted_users = users_to_delete.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Deleted {deleted_users[0]} users (kept {len(super_admin_user_ids)} super admin(s))'
                )
            )
        else:
            deleted_users = User.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_users[0]} users'))

        self.stdout.write(self.style.SUCCESS('\nAll data has been deleted successfully!'))
        self.stdout.write(self.style.WARNING('You can now start fresh with new data.'))

