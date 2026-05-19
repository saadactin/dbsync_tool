"""
Sync job models
"""
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from connections.models import DatabaseConnection, APIConnection, FileSourceConnection
from core.constants import SCHEDULE_TYPE_CHOICES


def default_retry_policy():
    """Default per-table retry policy used by SyncJobTable.retry_policy.

    Kept as a module-level callable so Django migrations and data backfills
    can reference the same canonical defaults.
    """
    return {
        "max_retries": 3,
        "initial_delay": 1.0,
        "backoff": 2.0,
        "retryable_errors": ["timeout", "conn_reset", "deadlock"],
    }


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
        related_name='source_jobs',
        null=True,  # Nullable for API sources
        blank=True
    )
    source_api_connection = models.ForeignKey(
        APIConnection,
        on_delete=models.CASCADE,
        related_name='api_source_jobs',
        null=True,  # Nullable for database sources
        blank=True
    )
    source_file_connection = models.ForeignKey(
        FileSourceConnection,
        on_delete=models.CASCADE,
        related_name='file_source_jobs',
        null=True,  # Nullable for database/api sources
        blank=True
    )
    source_connection_type = models.CharField(
        max_length=20,
        choices=[('database', 'Database'), ('api', 'API'), ('flat_file', 'Flat file')],
        null=True,  # Nullable for backward compatibility
        blank=True,
        help_text="Type of source connection (database, API, or flat file)"
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
    no_delete_propagation = models.BooleanField(
        default=True,
        help_text="When true, incremental sync will not propagate source-side deletes to target.",
    )
    incremental_overlap_seconds = models.PositiveIntegerField(
        default=120,
        help_text=(
            "Safety overlap window for incremental re-reads (seconds). "
            "Used to reduce missed rows around equal/low-precision watermark boundaries."
        ),
    )
    verification_mode = models.CharField(
        max_length=20,
        choices=[
            ('off', 'Off'),
            ('sampled', 'Sampled (count only)'),
            ('strict', 'Strict (count + hash, fail-on-drift)'),
        ],
        default='sampled',
        help_text=(
            "Post-run verification policy. 'strict' fails the run on parity mismatch; "
            "'sampled' logs counts only; 'off' disables verification."
        ),
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
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    target_table_prefix = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Optional prefix for target table names (e.g. POST → POST_tablename)"
    )
    
    class Meta:
        db_table = 'sync_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['tenant']),
            models.Index(fields=['tenant', 'status']),
        ]
    
    def get_source_connection(self):
        """
        Get source connection (database or API)
        
        Returns:
            DatabaseConnection, APIConnection, or FileSourceConnection instance
        """
        if self.source_connection_type == 'api':
            return self.source_api_connection
        if self.source_connection_type == 'flat_file':
            return self.source_file_connection
        return self.source_connection
    
    def is_api_source(self):
        """
        Check if source is API connection
        
        Returns:
            bool: True if source is API connection, False otherwise
        """
        return self.source_connection_type == 'api'

    def is_flat_file_source(self):
        """
        Check if source is flat-file connection.

        Returns:
            bool: True if source is flat-file connection, False otherwise
        """
        return self.source_connection_type == 'flat_file'
    
    def clean(self):
        """Validate model data"""
        super().clean()
        
        # Ensure exactly one source connection is set
        if self.source_connection_type == 'api':
            if not self.source_api_connection:
                raise ValidationError("source_api_connection is required when source_connection_type is 'api'")
            if self.source_connection:
                raise ValidationError("source_connection must be null when source_connection_type is 'api'")
            if self.source_file_connection:
                raise ValidationError("source_file_connection must be null when source_connection_type is 'api'")
        elif self.source_connection_type == 'database':
            if not self.source_connection:
                raise ValidationError("source_connection is required when source_connection_type is 'database'")
            if self.source_api_connection:
                raise ValidationError("source_api_connection must be null when source_connection_type is 'database'")
            if self.source_file_connection:
                raise ValidationError("source_file_connection must be null when source_connection_type is 'database'")
        elif self.source_connection_type == 'flat_file':
            if not self.source_file_connection:
                raise ValidationError("source_file_connection is required when source_connection_type is 'flat_file'")
            if self.source_connection:
                raise ValidationError("source_connection must be null when source_connection_type is 'flat_file'")
            if self.source_api_connection:
                raise ValidationError("source_api_connection must be null when source_connection_type is 'flat_file'")
        else:
            # Backward compatibility: if type is not set, assume database
            source_count = sum([
                bool(self.source_connection),
                bool(self.source_api_connection),
                bool(self.source_file_connection),
            ])
            if source_count == 0:
                raise ValidationError("One source connection must be set.")
            if source_count > 1:
                raise ValidationError("Only one of source_connection, source_api_connection, or source_file_connection can be set")
    
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
    incremental_key_columns = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text=(
            "Optional ordered key columns for incremental upsert policy. "
            "If empty, runtime uses source PK or fallback policy."
        ),
    )
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Transformation fields (Phase 1)
    transformation_query = models.TextField(
        null=True,
        blank=True,
        help_text="WHERE clause for data filtering (e.g., \"date_col >= '2010-01-01'\")"
    )
    column_transformations = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Column-level transformations (e.g., {\"name\": \"TRIM\", \"email\": \"UPPER\"})"
    )
    column_type_overrides = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Per-column target data type overrides (e.g., {\"id\": \"NUMBER(10)\", \"name\": \"VARCHAR2(100)\"})"
    )

    # Step 3: Persist target-side column renames (only for non-PK / non-protected columns).
    # Shape: { "<src_col_lower>": "<target_col_name>" }
    column_name_overrides = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Per-column target column name overrides (e.g., {\"id\": \"customer_id\"})"
    )
    excluded_columns = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text="List of source column names excluded from migration (lowercased).",
    )
    protected_columns = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text="Resolved protected source columns always included in migration (lowercased).",
    )
    transform_plan = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Model-data transform contract: mode (single_table|join|union|lookup), base_table, "
            "join_nodes, union_branches, union_select_columns, lookup block, "
            "selected_output_columns, structured_filters (no raw SQL), order_by, source_db_type."
        ),
    )
    flat_file_incremental_mode = models.CharField(
        max_length=40,
        choices=[
            ("legacy_mtime", "Legacy mtime"),
            ("hybrid_hash_control", "Hybrid hash + control table"),
        ],
        default="legacy_mtime",
        help_text=(
            "Flat-file incremental strategy. "
            "'legacy_mtime' keeps existing checkpoint watermark behavior; "
            "'hybrid_hash_control' enables file-hash control tracking and row-hash change detection."
        ),
    )
    flat_file_hash_columns = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text=(
            "Optional source-column allowlist used to build deterministic row hashes "
            "for flat-file hybrid incremental mode. Empty means all effective columns."
        ),
    )
    flat_file_hash_algorithm = models.CharField(
        max_length=20,
        default="sha256",
        help_text="Hash algorithm for flat-file row/file hashing (default: sha256).",
    )
    flat_file_allow_hash_only_without_key = models.BooleanField(
        default=False,
        help_text=(
            "Allow hash-only dedup semantics when stable key columns are not configured "
            "for flat-file hybrid incremental mode."
        ),
    )

    # Reliability / DQ foundations (Day 1 of the 7-day plan).
    # Schema for retry_policy:
    # {
    #   "max_retries": int,
    #   "initial_delay": float,
    #   "backoff": float,
    #   "retryable_errors": [str]
    # }
    retry_policy = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Per-table retry policy. Schema: "
            "{'max_retries': int, 'initial_delay': float, 'backoff': float, "
            "'retryable_errors': [str]}"
        ),
    )
    dead_letter_max_pct = models.FloatField(
        default=0.001,
        help_text=(
            "Maximum allowed dead-letter rate per run for this table "
            "(fraction of rows seen). 0 = fail-fast on first bad row."
        ),
    )

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
    interval_hours = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text="For hourly schedules: run every N hours on the first-run anchor grid (1-24).",
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
    # Reliability foundations (Day 1).
    # Dual-pointer resume model:
    #   last_seen_value     -> high-water mark observed at source (advances eagerly)
    #   last_committed_value -> high-water mark whose batch was durably committed at target
    # checkpoint_status drives resume behavior on the next run; existing executor
    # paths keep using last_value until Day-2 cuts them over.
    last_seen_value = models.TextField(null=True, blank=True)
    last_committed_value = models.TextField(null=True, blank=True)
    checkpoint_status = models.CharField(
        max_length=20,
        choices=[
            ("clean", "Clean"),
            ("dirty", "Dirty"),
            ("recovering", "Recovering"),
        ],
        default="clean",
        db_index=True,
    )
    last_successful_batch_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
    )
    last_status_reason = models.CharField(
        max_length=255,
        null=True,
        blank=True,
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


class MongoCdcCheckpoint(models.Model):
    """
    Checkpoint for MongoDB Change Streams (resume token per job+db+collection).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name="mongo_cdc_checkpoints",
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    resume_token = models.TextField(
        null=True,
        blank=True,
        help_text="MongoDB resume token (stored as JSON/text) for Change Streams resumption",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mongo_cdc_checkpoints"
        unique_together = [["job", "schema_name", "table_name"]]
        indexes = [
            models.Index(fields=["job", "schema_name", "table_name"]),
        ]

    def __str__(self):
        return f"MongoCDC checkpoint for {self.job.name} - {self.schema_name}.{self.table_name}"


class FlatFileIngestionControl(models.Model):
    """Per-file control/audit records for flat-file hybrid incremental sync."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name="flat_file_controls",
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    file_name = models.CharField(max_length=1024)
    file_hash = models.CharField(max_length=128)
    file_size_bytes = models.BigIntegerField(default=0)
    file_mtime_utc = models.DateTimeField(null=True, blank=True)
    rows_read = models.BigIntegerField(default=0)
    rows_inserted = models.BigIntegerField(default=0)
    rows_updated = models.BigIntegerField(default=0)
    rows_skipped = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=[("success", "Success"), ("failed", "Failed")],
        default="success",
    )
    error_message = models.TextField(null=True, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "flat_file_ingestion_controls"
        ordering = ["-processed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "schema_name", "table_name", "file_name", "file_hash"],
                name="uniq_flat_file_control_job_table_file_hash",
            )
        ]
        indexes = [
            models.Index(fields=["job", "-processed_at"]),
            models.Index(fields=["job", "schema_name", "table_name"]),
            models.Index(fields=["file_name", "file_hash"]),
            models.Index(fields=["status", "-processed_at"]),
        ]

    def __str__(self):
        return (
            f"{self.job.name} | {self.schema_name}.{self.table_name} | "
            f"{self.file_name} [{self.status}]"
        )


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
    total_source_bytes = models.BigIntegerField(default=0)
    total_target_bytes = models.BigIntegerField(default=0)
    source_database_size_bytes = models.BigIntegerField(null=True, blank=True)
    target_database_size_bytes = models.BigIntegerField(null=True, blank=True)
    size_collected_at = models.DateTimeField(null=True, blank=True)
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
    source_size_bytes = models.BigIntegerField(default=0)
    target_size_bytes = models.BigIntegerField(default=0)
    batch_number = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    # Verification summary for post-migration accuracy (e.g. "Rows: 100/100, Perfect accuracy: Yes")
    # Used by job/execution UI; Oracle-inclusive flows surface expected/actual counts and perfect_accuracy here.
    verification_summary = models.TextField(null=True, blank=True)
    # Reliability foundations (Day 1) - retry + dead-letter visibility.
    # These are written to by Day 3 (retry classifier) and Day 4 (dead-letter collector).
    # Today they only exist as columns with safe defaults so importers remain stable.
    attempts = models.IntegerField(default=0)
    last_error_code = models.CharField(max_length=64, null=True, blank=True)
    dead_letter_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sync_execution_logs'
        ordering = ['started_at']
        indexes = [
            models.Index(fields=['execution', '-started_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"Log for {self.schema_name}.{self.table_name} - {self.get_status_display()}"


class APISyncState(models.Model):
    """
    Track incremental sync state for API source modules
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name='api_sync_states'
    )
    module_name = models.CharField(max_length=255, help_text="Name of the API module being synced")
    last_sync_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this module was synced"
    )
    last_modified_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last modified time from API (for incremental sync)"
    )
    records_synced = models.BigIntegerField(
        default=0,
        help_text="Total number of records synced for this module"
    )
    record_hashes = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Map of record_id -> hash for hash-based change detection (e.g. SAP incremental)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'api_sync_states'
        unique_together = [['job', 'module_name']]
        indexes = [
            models.Index(fields=['job', 'module_name']),
            models.Index(fields=['job']),
        ]
        ordering = ['job', 'module_name']
    
    def __str__(self):
        return f"Sync state for {self.job.name} - {self.module_name}"
    
    @classmethod
    def get_for_job(cls, job):
        """
        Get all sync states for a job
        
        Args:
            job: SyncJob instance
            
        Returns:
            QuerySet of APISyncState objects
        """
        return cls.objects.filter(job=job)
    
    @classmethod
    def get_for_module(cls, job, module_name):
        """
        Get sync state for a specific module
        
        Args:
            job: SyncJob instance
            module_name: Module name
            
        Returns:
            APISyncState instance or None
        """
        try:
            return cls.objects.get(job=job, module_name=module_name)
        except cls.DoesNotExist:
            return None
    
    def update_sync_time(self, records_count: int, last_modified=None):
        """
        Update sync state after successful sync
        
        Args:
            records_count: Number of records synced in this operation
            last_modified: Optional datetime of last modified time from API
        """
        from django.utils import timezone
        self.last_sync_time = timezone.now()
        if last_modified:
            self.last_modified_time = last_modified
        self.records_synced += records_count
        self.save()
    
    def get_data_freshness(self):
        """
        Get time since last successful sync
        
        Returns:
            timedelta or None if never synced
        """
        from django.utils import timezone
        from datetime import timedelta
        if self.last_sync_time:
            return timezone.now() - self.last_sync_time
        return None


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


class SyncVerificationReport(models.Model):
    """Per-table parity report between source and target after a sync run.

    Used by the verification framework to prove SQL Server -> Postgres parity
    (count, optional hash) and to drive repair-full on drift.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name='verification_reports',
    )
    execution = models.ForeignKey(
        SyncExecution,
        on_delete=models.CASCADE,
        related_name='verification_reports',
        null=True,
        blank=True,
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    sync_mode = models.CharField(
        max_length=20,
        choices=[('full', 'Full'), ('incremental', 'Incremental')],
        default='full',
    )
    source_count = models.BigIntegerField(default=0)
    target_count = models.BigIntegerField(default=0)
    sample_hash_match = models.BooleanField(null=True, blank=True)
    decision = models.CharField(
        max_length=20,
        choices=[
            ('ok', 'OK'),
            ('repair_full', 'Repair Full'),
            ('repair_incremental', 'Repair Incremental'),
            ('warning', 'Warning'),
        ],
        default='ok',
    )
    details = models.TextField(null=True, blank=True)
    # Structured DQ metrics (Day 1 of reliability + DQ plan).
    # Written by Days 5-6 alongside the existing `details` text for back-compat.
    metrics_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sync_verification_reports'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job', '-created_at']),
            models.Index(fields=['job', 'schema_name', 'table_name']),
            models.Index(fields=['decision']),
        ]

    def __str__(self):
        return (
            f"VerificationReport {self.schema_name}.{self.table_name} "
            f"[{self.sync_mode}] -> {self.decision}"
        )


class ProcessedBatch(models.Model):
    """Idempotency marker per (execution, schema, table, batch_id).

    Reliability foundations (Day 1). Day-2's BatchCoordinator inserts a row
    in `started` state before write, then flips to `committed` inside the
    same atomic txn that commits the rows. A duplicate attempt at the same
    (execution, schema, table, batch_id) hits the unique constraint and the
    coordinator interprets that as "already done" -> safe replay.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name="processed_batches",
    )
    execution = models.ForeignKey(
        SyncExecution,
        on_delete=models.CASCADE,
        related_name="processed_batches",
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    batch_id = models.CharField(max_length=64)
    row_count = models.BigIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("started", "Started"),
            ("committed", "Committed"),
            ("failed", "Failed"),
        ],
        default="started",
        db_index=True,
    )

    class Meta:
        db_table = "processed_batches"
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "schema_name", "table_name", "batch_id"],
                name="uniq_processed_batch_per_run",
            )
        ]
        indexes = [
            models.Index(fields=["job", "schema_name", "table_name"]),
            models.Index(fields=["execution", "status"]),
        ]

    def __str__(self):
        return (
            f"ProcessedBatch {self.schema_name}.{self.table_name} "
            f"batch={self.batch_id} status={self.status}"
        )


class SyncDeadLetterRow(models.Model):
    """Per-row failure capture for non-fatal data quality issues.

    Reliability foundations (Day 1). Day-4's DeadLetterCollector writes
    one row here every time a single source row fails to apply but the
    run is allowed to continue (under the per-table `dead_letter_max_pct`
    budget). Today this table is created empty and is not yet written to.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        SyncExecution,
        on_delete=models.CASCADE,
        related_name="dead_letter_rows",
    )
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name="dead_letter_rows",
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    batch_id = models.CharField(max_length=64, null=True, blank=True)
    source_pk_text = models.CharField(max_length=512, null=True, blank=True)
    source_row_hash = models.CharField(max_length=128, null=True, blank=True)
    raw_row_json = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=64)
    error_message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sync_dead_letter_rows"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["execution", "schema_name", "table_name"]),
            models.Index(fields=["job", "-created_at"]),
            models.Index(fields=["error_code"]),
        ]

    def __str__(self):
        return (
            f"DeadLetter {self.schema_name}.{self.table_name} "
            f"pk={self.source_pk_text} code={self.error_code}"
        )


class ReconciliationReport(models.Model):
    """Per-table per-execution structured DQ artifact.

    Reliability foundations (Day 1). Days 5-6 build this. We define the
    schema today so callers (UI, admin, exporters) can be wired in
    parallel without later schema churn.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        SyncExecution,
        on_delete=models.CASCADE,
        related_name="reconciliation_reports",
    )
    job = models.ForeignKey(
        SyncJob,
        on_delete=models.CASCADE,
        related_name="reconciliation_reports",
    )
    schema_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    decision = models.CharField(
        max_length=24,
        choices=[
            ("ok", "OK"),
            ("warning", "Warning"),
            ("repair_full", "Repair Full"),
            ("repair_incremental", "Repair Incremental"),
        ],
        default="ok",
        db_index=True,
    )
    confidence = models.FloatField(default=1.0)
    source_metrics_json = models.JSONField(default=dict, blank=True)
    target_metrics_json = models.JSONField(default=dict, blank=True)
    drift_json = models.JSONField(default=dict, blank=True)
    dq_pre_json = models.JSONField(default=dict, blank=True)
    dq_post_json = models.JSONField(default=dict, blank=True)
    snapshots_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reconciliation_reports"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "schema_name", "table_name"],
                name="uniq_reconciliation_report_per_table",
            )
        ]
        indexes = [
            models.Index(fields=["job", "-created_at"]),
            models.Index(fields=["decision"]),
        ]

    def __str__(self):
        return (
            f"ReconciliationReport {self.schema_name}.{self.table_name} "
            f"-> {self.decision} (confidence={self.confidence:.2f})"
        )