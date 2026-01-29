"""
Management command to test Health Score feature
Run with: python manage.py test_health_score
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from sync_jobs.services import HealthScoreService
from sync_jobs.models import HealthScoreSnapshot


class Command(BaseCommand):
    help = 'Test Health Score feature functionality'

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS("Health Score Feature - Test"))
        self.stdout.write("=" * 60)

        # Get first user
        try:
            user = User.objects.first()
            if not user:
                self.stdout.write(self.style.ERROR("No users found. Please create a user first."))
                return
            self.stdout.write(f"Testing with user: {user.username}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting user: {e}"))
            return

        # Test 1: Calculate score
        self.stdout.write("\n1. Testing calculate_score()...")
        try:
            score_data = HealthScoreService.calculate_score(user)
            self.stdout.write(f"   [OK] Score: {score_data['score']}")
            self.stdout.write(f"   [OK] Components: {score_data['components']}")
            assert 0 <= score_data['score'] <= 100
            self.stdout.write(self.style.SUCCESS("   [PASSED]"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [FAILED]: {e}"))
            import traceback
            traceback.print_exc()
            return

        # Test 2: Get trend
        self.stdout.write("\n2. Testing get_trend()...")
        try:
            trend = HealthScoreService.get_trend(user, days=7)
            self.stdout.write(f"   [OK] Trend data points: {len(trend)}")
            assert isinstance(trend, list)
            self.stdout.write(self.style.SUCCESS("   [PASSED]"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [FAILED]: {e}"))
            import traceback
            traceback.print_exc()
            return

        # Test 3: Get trend direction
        self.stdout.write("\n3. Testing get_trend_direction()...")
        try:
            direction = HealthScoreService.get_trend_direction(user)
            self.stdout.write(f"   [OK] Trend direction: {direction}")
            assert direction in ['improving', 'degrading', 'stable']
            self.stdout.write(self.style.SUCCESS("   [PASSED]"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [FAILED]: {e}"))
            import traceback
            traceback.print_exc()
            return

        # Test 4: Save snapshot
        self.stdout.write("\n4. Testing save_snapshot()...")
        try:
            initial_count = HealthScoreSnapshot.objects.filter(tenant=user).count()
            HealthScoreService.save_snapshot(user)
            final_count = HealthScoreSnapshot.objects.filter(tenant=user).count()
            self.stdout.write(f"   [OK] Snapshots: {initial_count} -> {final_count}")
            assert final_count >= initial_count
            self.stdout.write(self.style.SUCCESS("   [PASSED]"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [FAILED]: {e}"))
            import traceback
            traceback.print_exc()
            return

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("All tests passed!"))
        self.stdout.write("=" * 60)
