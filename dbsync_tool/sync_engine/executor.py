"""
Main sync executor that orchestrates sync operations
"""
from typing import Optional
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncExecution
from connections.models import DatabaseConnection, APIConnection
from connections.connectors.factory import get_connector
from connections.connectors import get_api_connector
from sync_engine.full_sync import FullSyncExecutor
from sync_engine.incremental_sync import IncrementalSyncExecutor
from sync_engine.mongo_cdc_runner import MongoCdcRunner
from sync_engine.mongo_cdc_applier import apply_mongo_cdc_event_to_sql
from sync_engine.api_sync import APISyncExecutor
from sync_engine.sap_sync import SAPSyncExecutor
from sync_engine.zoho_runner import run_zoho_sync
from sync_engine.azure_devops_runner import run_azure_devops_sync
from sync_engine.sap_b1_runner import run_sap_b1_sync
from sync_engine.flat_file_sync import FlatFileSyncExecutor
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
                # API source - route based on api_type
                logger.info(f"Job {self.job.id} has API source")
                api_connection = self.job.source_api_connection
                if not api_connection:
                    raise SyncExecutionError("API connection not found for API source job")

                # Azure DevOps uses external scripts via AzureDevOpsRunner
                if api_connection.api_type == "azure_devops":
                    run_azure_devops_sync(
                        job=self.job,
                        execution=execution,
                        mode=self.job.sync_type or "full",
                    )
                # Zoho jobs (full + incremental) use external scripts via ZohoRunner
                elif api_connection.api_type == "zoho_crm":
                    run_zoho_sync(
                        job=self.job,
                        execution=execution,
                        mode=self.job.sync_type or "full",
                    )
                else:
                    # Other APIs (Zoho, SAP) use API connectors
                    api_connector = get_api_connector(api_connection)
                    target_connector = self._get_connector_with_retry(self.job.target_connection)

                    if api_connection.api_type == "zoho_crm":
                        executor = APISyncExecutor(
                            job=self.job,
                            execution=execution,
                            api_connector=api_connector,
                            target_connector=target_connector,
                        )
                        executor.execute()
                    elif api_connection.api_type == "sap_b1":
                        run_sap_b1_sync(
                            job=self.job,
                            execution=execution,
                            mode=self.job.sync_type or "full",
                        )
                    else:
                        raise SyncExecutionError(f"Unsupported API type: {api_connection.api_type}")

            elif self.job.is_flat_file_source():
                logger.info(f"Job {self.job.id} has flat-file source, using flat-file executor")
                target_connector = self._get_connector_with_retry(self.job.target_connection)
                executor = FlatFileSyncExecutor(
                    job=self.job,
                    execution=execution,
                    target_connector=target_connector,
                )
                executor.execute()
            else:
                # Database source - use existing executors
                logger.info(f"Job {self.job.id} has database source, using database sync executors")

                # Get connectors with retry
                source_connector = self._get_connector_with_retry(self.job.source_connection)
                target_connector = self._get_connector_with_retry(self.job.target_connection)

                # Check for PostgreSQL → ClickHouse migration (production engine)
                source_db_type = getattr(self.job.source_connection, 'db_type', '').lower()
                target_db_type = getattr(self.job.target_connection, 'db_type', '').lower()

                if source_db_type == 'postgres' and target_db_type == 'clickhouse':
                    # Use production PostgreSQL → ClickHouse engine
                    logger.info(f"PostgreSQL → ClickHouse migration detected, using production engine")
                    from sync_engine.postgres_clickhouse_executor import PostgresClickHouseExecutor
                    executor = PostgresClickHouseExecutor(
                        job=self.job,
                        execution=execution,
                        source_connector=source_connector,
                        target_connector=target_connector
                    )
                    executor.execute()
                # Execute based on sync type
                elif self.job.sync_type == 'full':
                    executor = FullSyncExecutor(
                        job=self.job,
                        execution=execution,
                        source_connector=source_connector,
                        target_connector=target_connector
                    )
                    executor.execute()
                elif self.job.sync_type == 'incremental':
                    # MongoDB source incremental uses Change Streams (resume token checkpoints).
                    if "MongoDB" in source_connector.__class__.__name__:
                        runner = MongoCdcRunner(job=self.job, source_connector=source_connector)
                        # Day 4: process events until stream ends; production can run continuously.
                        for evt in runner.iter_events():
                            apply_mongo_cdc_event_to_sql(
                                job=self.job,
                                event=evt,
                                source_connector=source_connector,
                                target_connector=target_connector,
                            )
                        # Mark execution complete (no table logs yet for CDC path; added Day 6 hardening).
                        execution.status = "completed"
                        execution.completed_at = timezone.now()
                        execution.save()
                    else:
                        executor = IncrementalSyncExecutor(
                            job=self.job,
                            execution=execution,
                            source_connector=source_connector,
                            target_connector=target_connector
                        )
                        executor.execute()
                else:
                    raise SyncExecutionError(f"Unknown sync type: {self.job.sync_type}")
            
            # Execution status was set by FullSyncExecutor/IncrementalSyncExecutor (failed vs completed). Refresh and act on it.
            # API/SAP executors may leave status as 'running'; treat that as success.
            execution.refresh_from_db()
            if execution.status == 'failed':
                # All or some tables failed — do not mark job completed
                self.job.status = 'failed'
                self.job.last_run_at = timezone.now()
                self.job.save()
                logger.warning(f"Execution {execution.id} finished with status 'failed' for job {self.job.id}")
                self._send_summary_email(execution)
                try:
                    if hasattr(self.job, 'schedule') and self.job.schedule and self.job.schedule.is_enabled:
                        from scheduler.utils import schedule_job_execution
                        schedule_job_execution(self.job)
                except Exception as e:
                    logger.warning(f"Error updating next_run_at after failure: {str(e)}")
            else:
                # completed or still running (API/SAP path) — mark success
                if execution.status != 'completed':
                    execution.status = 'completed'
                    execution.completed_at = timezone.now()
                    execution.save()
                self.job.status = 'completed'
                self.job.last_run_at = timezone.now()
                self.job.save()
                try:
                    if hasattr(self.job, 'schedule') and self.job.schedule and self.job.schedule.is_enabled:
                        from scheduler.utils import schedule_job_execution
                        schedule_job_execution(self.job)
                        logger.info(f"Updated next_run_at for job {self.job.id}: {self.job.next_run_at}")
                except Exception as e:
                    logger.warning(f"Error updating next_run_at after execution: {str(e)}")
                logger.info(f"Successfully completed execution {execution.id} for job {self.job.id}")
                try:
                    from sync_engine.size_collector import collect_and_persist_sizes
                    collect_and_persist_sizes(self.job, execution)
                except Exception as e:
                    logger.warning(f"Size collection failed for execution {execution.id}: {e}")
                self._send_summary_email(execution)
            
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
                self._send_summary_email(self.execution)
            
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
            self._send_summary_email(self.execution)
        
        self.job.status = 'failed'
        self.job.save()

    def _send_summary_email(self, execution: SyncExecution) -> None:
        """
        Send post-execution summary email without affecting execution outcome.
        """
        try:
            from sync_jobs.services.sync_email_service import send_execution_summary_email

            result = send_execution_summary_email(execution)
            if not result.get("sent"):
                logger.warning(
                    "Sync summary email not sent. execution=%s job=%s error=%s",
                    execution.id,
                    execution.job_id,
                    result.get("error_message", ""),
                )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "Unexpected summary email exception for execution=%s job=%s: %s",
                execution.id,
                execution.job_id,
                str(e),
            )

        # Day-6: send a single batched drift alert (or log a no-drift line)
        # *after* the summary email so a misconfigured SMTP cannot suppress
        # the per-execution summary.  Failures here never affect sync outcome.
        try:
            from sync_jobs.services.sync_email_service import send_drift_alert

            send_drift_alert(execution)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "Unexpected drift alert exception for execution=%s job=%s: %s",
                execution.id,
                execution.job_id,
                str(e),
            )

        # Day-7: streak-gated SLO breach detector.  Runs *after* the drift
        # alert so the operator always sees the per-execution context first.
        # Wrapped in its own try/except for belt-and-braces - the executor
        # must never fail because of an alerting side-effect.
        try:
            from sync_jobs.services.ops_metrics_service import detect_slo_breach
            from sync_jobs.services.sync_email_service import send_slo_breach_email

            breaches = detect_slo_breach(execution)
            if breaches:
                send_slo_breach_email(execution, breaches)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "Unexpected SLO breach detector exception for execution=%s job=%s: %s",
                execution.id,
                execution.job_id,
                str(e),
            )

