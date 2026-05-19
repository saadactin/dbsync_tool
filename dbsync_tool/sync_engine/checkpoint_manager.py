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

    def maybe_advance_checkpoint(
        self,
        schema_name: str,
        table_name: str,
        *,
        did_advance: bool,
        value: Any,
    ) -> bool:
        """
        Advance checkpoint only when the caller decides it is safe.

        Returns:
            bool: True if the checkpoint advanced (created/updated), else False.
        """
        if not did_advance:
            logger.info(
                "Skipping checkpoint advance for %s.%s (did_advance=False, value=%s)",
                schema_name,
                table_name,
                value,
            )
            return False

        self.create_or_update_checkpoint(
            schema_name=schema_name,
            table_name=table_name,
            value=value,
        )
        return True

    # ------------------------------------------------------------------
    # Day 2 - dual-pointer + status transitions
    # ------------------------------------------------------------------
    # These methods write only the new fields shipped by Day 1's
    # 0031_reliability_dq_foundations migration. Existing callers
    # continue to use last_value via maybe_advance_checkpoint.
    # set_committed additionally keeps last_value in sync so legacy
    # readers see the same boundary the new code is committing to.
    # ------------------------------------------------------------------

    def set_seen(
        self,
        schema_name: str,
        table_name: str,
        value: Any,
    ) -> SyncCheckpoint:
        """Eagerly advance ``last_seen_value``.

        Tracks the highest watermark the executor has *observed* in the
        source. Writing this carries no commit guarantee on the target.
        """
        if not schema_name or not table_name:
            raise ValueError("Schema name and table name are required")
        try:
            value_str = str(value) if value is not None else None
            checkpoint, _ = SyncCheckpoint.objects.update_or_create(
                job=self.job,
                schema_name=schema_name,
                table_name=table_name,
                defaults={
                    "last_seen_value": value_str,
                    "updated_at": timezone.now(),
                },
            )
            logger.debug(
                "Checkpoint %s.%s last_seen_value=%s",
                schema_name,
                table_name,
                value_str,
            )
            return checkpoint
        except Exception as e:
            logger.error(
                "Error setting last_seen_value for %s.%s: %s",
                schema_name,
                table_name,
                e,
                exc_info=True,
            )
            raise CheckpointError(
                f"Failed to set last_seen_value: {str(e)}"
            ) from e

    def set_committed(
        self,
        schema_name: str,
        table_name: str,
        value: Any,
        batch_id: Optional[str],
    ) -> SyncCheckpoint:
        """Atomically advance the committed pointer + legacy ``last_value``.

        Called only by ``BatchCoordinator.commit_batch`` after the target
        write has succeeded and we are inside its metadata transaction.

        ``value=None`` semantics:
            Used by full sync where there is no incremental watermark.
            Only ``last_successful_batch_id`` and ``updated_at`` are
            written, and the legacy ``last_value`` field is left alone.
        """
        if not schema_name or not table_name:
            raise ValueError("Schema name and table name are required")
        try:
            defaults = {"updated_at": timezone.now()}
            if value is not None:
                value_str = str(value)
                defaults["last_committed_value"] = value_str
                defaults["last_value"] = value_str
            if batch_id is not None:
                defaults["last_successful_batch_id"] = str(batch_id)[:64]
            checkpoint, _ = SyncCheckpoint.objects.update_or_create(
                job=self.job,
                schema_name=schema_name,
                table_name=table_name,
                defaults=defaults,
            )
            logger.debug(
                "Checkpoint %s.%s last_committed_value=%s batch_id=%s",
                schema_name,
                table_name,
                defaults.get("last_committed_value"),
                batch_id,
            )
            return checkpoint
        except Exception as e:
            logger.error(
                "Error setting last_committed_value for %s.%s: %s",
                schema_name,
                table_name,
                e,
                exc_info=True,
            )
            raise CheckpointError(
                f"Failed to set last_committed_value: {str(e)}"
            ) from e

    def mark_dirty(
        self,
        schema_name: str,
        table_name: str,
        reason: Optional[str] = None,
    ) -> SyncCheckpoint:
        """Set ``checkpoint_status='dirty'`` and record the reason.

        Does not touch any of the value pointers; only signals that the
        most recent attempt at this table failed and a recovery pass is
        needed before the values can be trusted again.
        """
        return self._set_status(
            schema_name=schema_name,
            table_name=table_name,
            status="dirty",
            reason=reason,
        )

    def mark_recovering(
        self,
        schema_name: str,
        table_name: str,
        reason: Optional[str] = None,
    ) -> SyncCheckpoint:
        """Set ``checkpoint_status='recovering'`` (Day-2 recovery sweep)."""
        return self._set_status(
            schema_name=schema_name,
            table_name=table_name,
            status="recovering",
            reason=reason,
        )

    def mark_clean(
        self,
        schema_name: str,
        table_name: str,
    ) -> SyncCheckpoint:
        """Reset ``checkpoint_status`` to ``clean`` and clear the reason."""
        return self._set_status(
            schema_name=schema_name,
            table_name=table_name,
            status="clean",
            reason=None,
        )

    def _set_status(
        self,
        *,
        schema_name: str,
        table_name: str,
        status: str,
        reason: Optional[str],
    ) -> SyncCheckpoint:
        if not schema_name or not table_name:
            raise ValueError("Schema name and table name are required")
        try:
            defaults = {
                "checkpoint_status": status,
                "last_status_reason": (reason or None) if reason is not None else None,
                "updated_at": timezone.now(),
            }
            # Truncate reason to fit the 255-char column.
            if defaults["last_status_reason"]:
                defaults["last_status_reason"] = defaults["last_status_reason"][:255]
            checkpoint, _ = SyncCheckpoint.objects.update_or_create(
                job=self.job,
                schema_name=schema_name,
                table_name=table_name,
                defaults=defaults,
            )
            logger.debug(
                "Checkpoint %s.%s checkpoint_status=%s reason=%s",
                schema_name,
                table_name,
                status,
                defaults["last_status_reason"],
            )
            return checkpoint
        except Exception as e:
            logger.error(
                "Error setting checkpoint_status=%s for %s.%s: %s",
                status,
                schema_name,
                table_name,
                e,
                exc_info=True,
            )
            raise CheckpointError(
                f"Failed to set checkpoint_status={status}: {str(e)}"
            ) from e
    
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

