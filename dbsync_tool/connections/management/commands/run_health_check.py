"""
Management command to run health check on all connections.

Usage:
    python manage.py run_health_check
    python manage.py run_health_check --tenant-id=<uuid>
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from connections.health_check import run_health_check
from connections.models import ConnectionHealthCheckLog


class Command(BaseCommand):
    help = 'Run health check on all database, API, and file connections'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=str,
            help='Test connections for specific user/tenant only',
        )

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        user = None

        if user_id:
            try:
                user = User.objects.get(id=user_id)
                self.stdout.write(f"Running health check for user: {user.username}")
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User {user_id} not found"))
                return
        else:
            self.stdout.write("Running health check for all connections...")

        # Run health check
        results = run_health_check(tenant=user)

        # Save results to database
        from django.utils.dateparse import parse_datetime
        log = ConnectionHealthCheckLog.objects.create(
            tested_at=parse_datetime(results['tested_at']),
            total_tested=results['total_tested'],
            total_passed=results['total_passed'],
            total_failed=results['total_failed'],
            results_json=results,
            tenant=user
        )

        # Print summary
        self.stdout.write(self.style.SUCCESS(f"\n{'='*60}"))
        self.stdout.write(self.style.SUCCESS(f"Health Check Summary"))
        self.stdout.write(self.style.SUCCESS(f"{'='*60}"))
        self.stdout.write(f"Tested at: {results['tested_at']}")
        self.stdout.write(f"Total connections tested: {results['total_tested']}")
        self.stdout.write(self.style.SUCCESS(f"[OK] Passed: {results['total_passed']}"))

        if results['total_failed'] > 0:
            self.stdout.write(self.style.ERROR(f"[FAIL] Failed: {results['total_failed']}"))
        else:
            self.stdout.write(f"[FAIL] Failed: 0")

        # Print failed connections
        if results['total_failed'] > 0:
            self.stdout.write(f"\n{self.style.ERROR('Failed Connections:')}")
            self.stdout.write(f"{'-'*60}")

            for conn_type in ['database', 'api', 'file']:
                failed_conns = [c for c in results[conn_type] if c['status'] == 'failed']
                if failed_conns:
                    self.stdout.write(f"\n{conn_type.upper()} Connections:")
                    for conn in failed_conns:
                        self.stdout.write(f"  [X] {conn['name']} ({conn['type']})")
                        self.stdout.write(f"     Error: {conn['error']}")

        # Print passed connections (if verbose)
        if options.get('verbosity', 1) >= 2:
            self.stdout.write(f"\n{self.style.SUCCESS('Passed Connections:')}")
            self.stdout.write(f"{'-'*60}")

            for conn_type in ['database', 'api', 'file']:
                passed_conns = [c for c in results[conn_type] if c['status'] == 'passed']
                if passed_conns:
                    self.stdout.write(f"\n{conn_type.upper()} Connections:")
                    for conn in passed_conns:
                        self.stdout.write(f"  [OK] {conn['name']} ({conn['type']})")

        self.stdout.write(f"\n{self.style.SUCCESS('='*60)}")
        self.stdout.write(self.style.SUCCESS(f"Health check log ID: {log.id}"))
        self.stdout.write(self.style.SUCCESS(f"Health check complete!"))
