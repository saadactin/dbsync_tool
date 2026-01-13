"""
Checkpoint management for incremental sync
Manages checkpoints that track the last synced value for each table in a job
"""
from typing import Optional, Any, List
from django.utils import timezone
from sync_jobs.models import SyncJob, SyncCheckpoint
from sync_engine.exceptions import CheckpointError
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class CheckpointManager:
    """Manages checkpoints for incremental sync"""
    
    def __init__(self, job: SyncJob):
        """
        Initialize checkpoint manager
        
        Args:
            job: SyncJob instance
        """
        if not job:
            raise ValueError("Job cannot be None")
        self.job = job
    
    def get_checkpoint(
        self,
        schema_name: str,
        table_name: str
    ) -> Optional[SyncCheckpoint]:
        """
        Get checkpoint for a table
        
        Args:
            schema_name: Schema name
            table_name: Table name
            
        Returns:
            SyncCheckpoint instance or None if not exists
            
        Raises:
            CheckpointError: If database error occurs
        """
        if not schema_name or not table_name:
            raise ValueError("Schema name and table name are required")
        
        try:
            checkpoint = SyncCheckpoint.objects.get(
                job=self.job,
                schema_name=schema_name,
                table_name=table_name
            )
            logger.debug(
                f"Retrieved checkpoint for {schema_name}.{table_name}: "
                f"{checkpoint.last_value}"
            )
            return checkpoint
        except SyncCheckpoint.DoesNotExist:
            logger.debug(f"No checkpoint found for {schema_name}.{table_name}")
            return None
        except Exception as e:
            logger.error(
                f"Error getting checkpoint for {schema_name}.{table_name}: {str(e)}",
                exc_info=True
            )
            raise CheckpointError(f"Failed to get checkpoint: {str(e)}") from e
    
    def get_checkpoint_value(
        self,
        schema_name: str,
        table_name: str
    ) -> Optional[Any]:
        """
        Get checkpoint value for a table (parsed from string storage)
        
        Args:
            schema_name: Schema name
            table_name: Table name
            
        Returns:
            Checkpoint value (timestamp string, ID, etc.) or None
        """
        checkpoint = self.get_checkpoint(schema_name, table_name)
        if checkpoint and checkpoint.last_value:
            return checkpoint.last_value
        return None
    
    def create_or_update_checkpoint(
        self,
        schema_name: str,
        table_name: str,
        value: Any
    ) -> SyncCheckpoint:
        """
        Create or update checkpoint for a table
        
        Args:
            schema_name: Schema name
            table_name: Table name
            value: Checkpoint value (timestamp, ID, etc.)
            
        Returns:
            SyncCheckpoint instance
            
        Raises:
            CheckpointError: If checkpoint update fails
        """
        if not schema_name or not table_name:
            raise ValueError("Schema name and table name are required")
        
        try:
            # Convert value to string for storage
            value_str = str(value) if value is not None else None
            
            checkpoint, created = SyncCheckpoint.objects.update_or_create(
                job=self.job,
                schema_name=schema_name,
                table_name=table_name,
                defaults={
                    'last_value': value_str,
                    'updated_at': timezone.now()
                }
            )
            
            action = "Created" if created else "Updated"
            logger.info(
                f"{action} checkpoint for {schema_name}.{table_name}: {value_str}"
            )
            return checkpoint
        except Exception as e:
            logger.error(
                f"Error updating checkpoint for {schema_name}.{table_name}: {str(e)}",
                exc_info=True
            )
            raise CheckpointError(f"Failed to update checkpoint: {str(e)}") from e
    
    def delete_checkpoint(
        self,
        schema_name: str,
        table_name: str
    ) -> bool:
        """
        Delete checkpoint for a table
        
        Args:
            schema_name: Schema name
            table_name: Table name
            
        Returns:
            True if deleted, False if not found
        """
        try:
            deleted, _ = SyncCheckpoint.objects.filter(
                job=self.job,
                schema_name=schema_name,
                table_name=table_name
            ).delete()
            if deleted > 0:
                logger.info(
                    f"Deleted checkpoint for {schema_name}.{table_name}"
                )
            return deleted > 0
        except Exception as e:
            logger.error(
                f"Error deleting checkpoint for {schema_name}.{table_name}: {str(e)}",
                exc_info=True
            )
            return False
    
    def reset_all_checkpoints(self) -> int:
        """
        Reset all checkpoints for the job
        
        Returns:
            Number of checkpoints deleted
            
        Raises:
            CheckpointError: If reset fails
        """
        try:
            count = SyncCheckpoint.objects.filter(job=self.job).delete()[0]
            logger.info(f"Reset {count} checkpoints for job {self.job.id}")
            return count
        except Exception as e:
            logger.error(f"Error resetting checkpoints: {str(e)}", exc_info=True)
            raise CheckpointError(f"Failed to reset checkpoints: {str(e)}") from e
    
    def get_all_checkpoints(self) -> List[SyncCheckpoint]:
        """
        Get all checkpoints for the job
        
        Returns:
            List of SyncCheckpoint instances
        """
        return list(SyncCheckpoint.objects.filter(job=self.job))

