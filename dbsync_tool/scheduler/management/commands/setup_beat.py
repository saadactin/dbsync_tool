"""
Management command to setup Celery Beat schedule
"""
from django.core.management.base import BaseCommand
from scheduler.beat_schedule import setup_beat_schedule, verify_beat_schedule
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Setup Celery Beat schedule for periodic tasks'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--verify',
            action='store_true',
            help='Only verify beat schedule, do not create',
        )
    
    def handle(self, *args, **options):
        if options['verify']:
            self.stdout.write('Verifying Celery Beat schedule...')
            is_valid = verify_beat_schedule()
            if is_valid:
                self.stdout.write(self.style.SUCCESS('Celery Beat schedule is properly configured'))
            else:
                self.stdout.write(self.style.ERROR('Celery Beat schedule is NOT properly configured'))
        else:
            self.stdout.write('Setting up Celery Beat schedule...')
            try:
                task, created = setup_beat_schedule()
                action = 'Created' if created else 'Updated'
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{action} periodic task: {task.name} (enabled: {task.enabled})'
                    )
                )
                
                # Verify
                is_valid = verify_beat_schedule()
                if is_valid:
                    self.stdout.write(self.style.SUCCESS('Celery Beat schedule verified successfully'))
                else:
                    self.stdout.write(self.style.WARNING('Celery Beat schedule verification failed'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error setting up beat schedule: {str(e)}'))
                raise

