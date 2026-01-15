"""
Sync job models
"""
import uuid
from django.db import models
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from core.constants import SCHEDULE_TYPE_CHOICES


class SyncJob(models.Model):
    """
    Main sync job model
    Full implementation in Day 11
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    source_connection = models.ForeignKey(
        DatabaseConnection,
        on_delete=models.CASCADE,
        related_name='source_jobs'
    )
    target_connection = models.ForeignKey(
        DatabaseConnection,
        on_delete=models.CASCADE,
        related_name='target_jobs'
    )
    sync_type = models.CharField(
        max_length=20,
        choices=[('full', 'Full Sync'), ('incremental', 'Incremental Sync')],
        default='full'
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('paused', 'Paused'),
        ],
        default='pending'
    )
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sync_jobs')
    tenant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='tenant_jobs',
        null=True,  # Nullable initially
        blank=True,
        db_index=True,
        help_text='Tenant (Admin user) who owns this job'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'sync_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['tenant']),
            models.Index(fields=['tenant', 'status']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_sync_type_display()})"


class SyncJobTable(models.Model):
    """
    Tables included in a sync job
    Full implementation in Day 11
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, related_name='tables')
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    incremental_column = models.CharField(max_length=255, null=True, blank=True)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sync_job_tables'
        unique_together = [['job', 'schema_name', 'table_name']]
    
    def __str__(self):
        return f"{self.job.name} - {self.schema_name}.{self.table_name}"


class SyncSchedule(models.Model):
    """
    Schedule configuration for sync jobs
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        SyncJob,
        on_delete=models.CASCADE,
        related_name='schedule',
        null=True,
        blank=True
    )
    schedule_type = models.CharField(
        max_length=20,
        choices=SCHEDULE_TYPE_CHOICES,
        default='once'
    )
    cron_expression = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Cron expression for custom schedules (e.g., '0 0 * * *' for daily at midnight)"
    )
    tenant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='tenant_schedules',
        null=True,  # Nullable initially
        blank=True,
        db_index=True,
        help_text='Tenant (Admin user) who owns this schedule'
    )
    is_enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sync_schedules'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant']),
            models.Index(fields=['tenant', 'is_enabled']),
        ]
    
    def save(self, *args, **kwargs):
        """Set tenant from job if not set"""
        if self.job and not self.tenant:
            self.tenant = self.job.tenant
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Schedule for {self.job.name if self.job else 'Unknown'} ({self.get_schedule_type_display()})"


class SyncCheckpoint(models.Model):
    """
    Checkpoint for incremental sync to track last synced value
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name='checkpoints'
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    last_value = models.TextField(
        null=True,
        blank=True,
        help_text="Last synced value (timestamp or ID) for incremental sync"
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sync_checkpoints'
        unique_together = [['job', 'schema_name', 'table_name']]
        indexes = [
            models.Index(fields=['job', 'schema_name', 'table_name']),
        ]
    
    def __str__(self):
        return f"Checkpoint for {self.job.name} - {self.schema_name}.{self.table_name}"


class SyncExecution(models.Model):
    """
    Execution record for a sync job run
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name='executions'
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending'
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_tables = models.IntegerField(default=0)
    completed_tables = models.IntegerField(default=0)
    total_rows_synced = models.BigIntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    memory_peak_mb = models.FloatField(null=True, blank=True)
    query_count = models.IntegerField(null=True, blank=True)
    avg_batch_time_ms = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sync_executions'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['job', '-started_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"Execution {self.id} for {self.job.name} - {self.get_status_display()}"


class SyncExecutionLog(models.Model):
    """
    Per-table execution log for detailed tracking
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        SyncExecution,
        on_delete=models.CASCADE,
        related_name='logs'
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending'
    )
    rows_fetched = models.BigIntegerField(default=0)
    rows_inserted = models.BigIntegerField(default=0)
    batch_number = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'sync_execution_logs'
        ordering = ['started_at']
        indexes = [
            models.Index(fields=['execution', '-started_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"Log for {self.schema_name}.{self.table_name} - {self.get_status_display()}"


class NotificationPreference(models.Model):
    """
    User notification preferences
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    email_enabled = models.BooleanField(default=True)
    notify_on_job_completed = models.BooleanField(default=True)
    notify_on_job_failed = models.BooleanField(default=True)
    notify_on_job_paused = models.BooleanField(default=False)
    notify_on_schedule_missed = models.BooleanField(default=True)
    email_address = models.EmailField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'notification_preferences'
    
    def __str__(self):
        return f"Notifications for {self.user.username}"


class NotificationLog(models.Model):
    """
    Log of sent notifications
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(
        max_length=50,
        choices=[
            ('job_completed', 'Job Completed'),
            ('job_failed', 'Job Failed'),
            ('job_paused', 'Job Paused'),
            ('schedule_missed', 'Schedule Missed'),
        ]
    )
    job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, null=True, blank=True)
    execution = models.ForeignKey(SyncExecution, on_delete=models.CASCADE, null=True, blank=True)
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'notification_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['notification_type']),
        ]
    
    def __str__(self):
        return f"{self.notification_type} - {self.user.username}"


class JobTemplate(models.Model):
    """
    Template for creating sync jobs
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    source_connection = models.ForeignKey(
        DatabaseConnection,
        on_delete=models.SET_NULL,
        null=True,
        related_name='source_templates'
    )
    target_connection = models.ForeignKey(
        DatabaseConnection,
        on_delete=models.SET_NULL,
        null=True,
        related_name='target_templates'
    )
    sync_type = models.CharField(max_length=20, default='full')
    table_config = models.JSONField(default=dict)  # Store table selections
    schedule_config = models.JSONField(default=dict)  # Store schedule settings
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    is_public = models.BooleanField(default=False)  # Share with other users
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'job_templates'
    
    def __str__(self):
        return self.name