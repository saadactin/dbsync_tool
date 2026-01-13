"""
Management command to check scheduler status and refresh job schedules
"""
from django.core.management.base import BaseCommand
from scheduler.service import get_scheduler, start_scheduler, load_all_jobs
from scheduler.utils import schedule_job_execution
from sync_jobs.models import SyncJob
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check scheduler status and refresh job schedules'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh',
            action='store_true',
            help='Refresh next_run_at for all scheduled jobs',
        )
        parser.add_argument(
            '--start',
            action='store_true',
            help='Start scheduler if not running',
        )
    
    def handle(self, *args, **options):
        scheduler = get_scheduler()
        
        if scheduler is None:
            self.stdout.write(self.style.WARNING('Scheduler is not initialized'))
            if options['start']:
                self.stdout.write('Starting scheduler...')
                try:
                    start_scheduler()
                    scheduler = get_scheduler()
                    if scheduler and scheduler.running:
                        self.stdout.write(self.style.SUCCESS('Scheduler started successfully'))
                    else:
                        self.stdout.write(self.style.ERROR('Failed to start scheduler'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error starting scheduler: {str(e)}'))
            return
        
        if not scheduler.running:
            self.stdout.write(self.style.WARNING('Scheduler is not running'))
            if options['start']:
                self.stdout.write('Starting scheduler...')
                try:
                    start_scheduler()
                    self.stdout.write(self.style.SUCCESS('Scheduler started successfully'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error starting scheduler: {str(e)}'))
            return
        
        self.stdout.write(self.style.SUCCESS('Scheduler is running'))
        
        # List scheduled jobs
        jobs = scheduler.get_jobs()
        self.stdout.write(f'\nScheduled jobs in APScheduler: {len(jobs)}')
        for job in jobs:
            self.stdout.write(f'  - {job.name} (ID: {job.id}, Next run: {job.next_run_time})')
        
        # Refresh next_run_at if requested
        if options['refresh']:
            self.stdout.write('\nRefreshing next_run_at for all scheduled jobs...')
            db_jobs = SyncJob.objects.filter(
                status__in=['pending', 'completed', 'failed']
            ).select_related('schedule')
            
            refreshed_count = 0
            for job in db_jobs:
                if hasattr(job, 'schedule') and job.schedule and job.schedule.is_enabled:
                    try:
                        schedule_job_execution(job)
                        job.refresh_from_db()
                        self.stdout.write(
                            f'  - {job.name}: next_run_at = {job.next_run_at}'
                        )
                        refreshed_count += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'  - Error refreshing {job.name}: {str(e)}')
                        )
            
            self.stdout.write(
                self.style.SUCCESS(f'\nRefreshed {refreshed_count} job(s)')
            )

