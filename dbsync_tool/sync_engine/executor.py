"""
Main sync executor that orchestrates sync operations
"""
from typing import Optional
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncExecution
from connections.models import DatabaseConnection, APIConnection
from connections.connectors.factory import get_connector
from connections.connectors.zoho import ZohoConnector
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_engine.api_sync import APISyncExecutor
from sync_engine.exceptions import SyncExecutionError, TableSyncError
import logging
import time

logger = logging.getLogger(__name__)

class SyncExecutor:
    """Main executor for sync jobs"""
    
    def __init__(self, job: SyncJob):
        """
        Initialize sync executor
        
        Args:
            job: SyncJob instance to execute
        """
        self.job = job
        self.execution: Optional[SyncExecution] = None
    
    def create_execution(self) -> SyncExecution:
        """
        Create execution record
        
        Returns:
            SyncExecution instance
        """
        execution = SyncExecution.objects.create(
            job=self.job,
            status='pending',
            total_tables=self.job.tables.filter(is_enabled=True).count()
        )
        self.execution = execution
        logger.info(f"Created execution {execution.id} for job {self.job.id}")
        return execution
    
    def execute(self):
        """
        Execute the sync job with error recovery
        
        Raises:
            SyncExecutionError: If execution fails
        """
        source_connector = None
        target_connector = None
        
        try:
            # Create execution record
            execution = self.create_execution()
            
            # Update job status
            self.job.status = 'running'
            self.job.save()
            
            # Check if source is API or Database
            if self.job.is_api_source():
                # API source - use APISyncExecutor
                logger.info(f"Job {self.job.id} has API source, using APISyncExecutor")
                
                # Get API connector
                api_connection = self.job.source_api_connection
                if not api_connection:
                    raise SyncExecutionError("API connection not found for API source job")
                
                api_connector = ZohoConnector(api_connection)
                
                # Get target database connector
                target_connector = self._get_connector_with_retry(self.job.target_connection)
                
                # Execute API sync
                executor = APISyncExecutor(
                    job=self.job,
                    execution=execution,
                    api_connector=api_connector,
                    target_connector=target_connector
                )
                executor.execute()
                
                # Close API connector (it doesn't have a close method, but we can clean up)
                # API connectors don't maintain persistent connections
                
            else:
                # Database source - use existing executors
                logger.info(f"Job {self.job.id} has database source, using database sync executors")
                
                # Get connectors with retry
                source_connector = self._get_connector_with_retry(self.job.source_connection)
                target_connector = self._get_connector_with_retry(self.job.target_connection)
                
                # Execute based on sync type
                if self.job.sync_type == 'full':
                    executor = FullSyncExecutor(
                        job=self.job,
                        execution=execution,
                        source_connector=source_connector,
                        target_connector=target_connector
                    )
                    executor.execute()
                elif self.job.sync_type == 'incremental':
                    executor = IncrementalSyncExecutor(
                        job=self.job,
                        execution=execution,
                        source_connector=source_connector,
                        target_connector=target_connector
                    )
                    executor.execute()
                else:
                    raise SyncExecutionError(f"Unknown sync type: {self.job.sync_type}")
            
            # Mark execution as completed
            execution.status = 'completed'
            execution.completed_at = timezone.now()
            execution.save()
            
            # Update job status
            self.job.status = 'completed'
            self.job.last_run_at = timezone.now()
            self.job.save()
            
            # Recalculate next_run_at for scheduled jobs
            try:
                if hasattr(self.job, 'schedule') and self.job.schedule and self.job.schedule.is_enabled:
                    from scheduler.utils import schedule_job_execution
                    schedule_job_execution(self.job)
                    logger.info(f"Updated next_run_at for job {self.job.id}: {self.job.next_run_at}")
            except Exception as e:
                logger.warning(f"Error updating next_run_at after execution: {str(e)}")
            
            logger.info(f"Successfully completed execution {execution.id} for job {self.job.id}")
            
            # Send completion notification
            try:
                from sync_jobs.notifications import NotificationService
                NotificationService.send_job_completed_notification(self.job, execution)
            except Exception as e:
                logger.warning(f"Failed to send completion notification: {str(e)}")
            
        except TableSyncError as e:
            # Table-level errors are handled by FullSyncExecutor
            # Just log and update status
            logger.warning(
                f"Table sync errors occurred for job {self.job.id}: {str(e)}"
            )
            # Execution status is already updated by FullSyncExecutor
            # Job status remains 'running' if some tables succeeded
            
        except ConnectionError as e:
            # Retry with exponential backoff
            logger.error(f"Connection error for job {self.job.id}: {str(e)}")
            self._handle_connection_error(e)
            
        except Exception as e:
            logger.error(
                f"Sync execution failed for job {self.job.id}: {str(e)}",
                exc_info=True
            )
            
            if self.execution:
                self.execution.status = 'failed'
                self.execution.error_message = str(e)
                self.execution.completed_at = timezone.now()
                self.execution.save()
                
                # Send failure notification
                try:
                    from sync_jobs.notifications import NotificationService
                    NotificationService.send_job_failed_notification(self.job, self.execution)
                except Exception as e:
                    logger.warning(f"Failed to send failure notification: {str(e)}")
            
            self.job.status = 'failed'
            self.job.save()
            
            # Recalculate next_run_at even on failure (for retry scheduling)
            try:
                if hasattr(self.job, 'schedule') and self.job.schedule and self.job.schedule.is_enabled:
                    from scheduler.utils import schedule_job_execution
                    schedule_job_execution(self.job)
                    logger.info(f"Updated next_run_at for failed job {self.job.id}: {self.job.next_run_at}")
            except Exception as e:
                logger.warning(f"Error updating next_run_at after failure: {str(e)}")
            
            raise SyncExecutionError(f"Sync execution failed: {str(e)}") from e
        finally:
            # Close connections (only for database connectors)
            # Note: source_connector may not be set for API sources
            if hasattr(self, 'source_connector') and self.source_connector:
                try:
                    self.source_connector.close()
                except Exception as e:
                    logger.warning(f"Error closing source connection: {str(e)}")
            if 'target_connector' in locals() and target_connector:
                try:
                    target_connector.close()
                except Exception as e:
                    logger.warning(f"Error closing target connection: {str(e)}")
    
    def _get_connector_with_retry(self, connection, max_retries=3):
        """
        Get connector with retry logic for transient connection errors
        
        Args:
            connection: DatabaseConnection instance
            max_retries: Maximum number of retry attempts
        
        Returns:
            DBConnector instance
        """
        for attempt in range(max_retries):
            try:
                connector = get_connector(connection)
                # Test connection
                connector.connect()
                connector.close()
                return connector
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        f"Connection attempt {attempt + 1} failed for {connection.name}: {str(e)}. "
                        f"Retrying in {wait_time} seconds..."
                    )
                    time.sleep(wait_time)
                else:
                    raise ConnectionError(
                        f"Failed to connect to {connection.name} after {max_retries} attempts: {str(e)}"
                    ) from e
    
    def _handle_connection_error(self, error):
        """
        Handle connection errors with appropriate recovery
        
        Args:
            error: ConnectionError instance
        """
        if self.execution:
            self.execution.status = 'failed'
            self.execution.error_message = f"Connection error: {str(error)}"
            self.execution.completed_at = timezone.now()
            self.execution.save()
            
            # Send failure notification
            try:
                from sync_jobs.notifications import NotificationService
                NotificationService.send_job_failed_notification(self.job, self.execution)
            except Exception as e:
                logger.warning(f"Failed to send failure notification: {str(e)}")
        
        self.job.status = 'failed'
        self.job.save()

