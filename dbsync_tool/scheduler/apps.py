"""
Scheduler app configuration
"""
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class SchedulerConfig(AppConfig):
    """Scheduler app configuration"""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'scheduler'
    
    def ready(self):
        """Called when Django starts - Initialize scheduler service"""
        import os
        import threading
        
        # Use threading to delay startup slightly to avoid issues with Django initialization
        def start_scheduler_delayed():
            import time
            time.sleep(2)  # Wait 2 seconds for Django to fully initialize
            
            try:
                from scheduler.service import start_scheduler, get_scheduler
                start_scheduler()
                
                # Verify scheduler started
                scheduler = get_scheduler()
                if scheduler and scheduler.running:
                    logger.info("Scheduler service successfully started and running")
                else:
                    logger.error("Scheduler service failed to start")
            except Exception as e:
                logger.error(f"Error initializing scheduler service: {str(e)}", exc_info=True)
        
        # Start scheduler in background thread
        thread = threading.Thread(target=start_scheduler_delayed, daemon=True)
        thread.start()
