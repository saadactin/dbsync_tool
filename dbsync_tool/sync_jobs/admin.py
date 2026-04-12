from django.contrib import admin
from .models import (
    FlatFileIngestionControl,
    SyncCheckpoint,
    SyncExecution,
    SyncExecutionLog,
    SyncJob,
    SyncJobTable,
    SyncSchedule,
)

@admin.register(SyncJob)
class SyncJobAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'source_connection',
        'target_connection',
        'sync_type',
        'no_delete_propagation',
        'incremental_overlap_seconds',
        'status',
        'created_by',
        'created_at',
    ]
    list_filter = ['sync_type', 'status', 'created_at']
    search_fields = ['name']
    readonly_fields = ['id', 'created_at', 'updated_at']

@admin.register(SyncJobTable)
class SyncJobTableAdmin(admin.ModelAdmin):
    list_display = [
        'job',
        'schema_name',
        'table_name',
        'incremental_column',
        'incremental_key_columns',
        'flat_file_incremental_mode',
        'flat_file_hash_algorithm',
        'is_enabled',
    ]
    list_filter = ['is_enabled', 'job']
    search_fields = ['table_name', 'schema_name']

@admin.register(SyncSchedule)
class SyncScheduleAdmin(admin.ModelAdmin):
    list_display = ['job', 'schedule_type', 'interval_hours', 'is_enabled', 'next_run_at']
    list_filter = ['schedule_type', 'is_enabled']

@admin.register(SyncCheckpoint)
class SyncCheckpointAdmin(admin.ModelAdmin):
    list_display = ['job', 'schema_name', 'table_name', 'last_value', 'updated_at']
    list_filter = ['job']
    search_fields = ['table_name', 'schema_name']

@admin.register(SyncExecution)
class SyncExecutionAdmin(admin.ModelAdmin):
    list_display = ['job', 'status', 'started_at', 'completed_at', 'total_tables', 'completed_tables', 'total_rows_synced']
    list_filter = ['status', 'started_at']
    search_fields = ['job__name']
    readonly_fields = ['id', 'started_at', 'created_at']
    date_hierarchy = 'started_at'

@admin.register(SyncExecutionLog)
class SyncExecutionLogAdmin(admin.ModelAdmin):
    list_display = ['execution', 'schema_name', 'table_name', 'status', 'rows_fetched', 'rows_inserted', 'verification_summary', 'error_message', 'started_at', 'completed_at']
    list_filter = ['status', 'execution']
    search_fields = ['schema_name', 'table_name', 'execution__job__name']
    readonly_fields = ['id']


@admin.register(FlatFileIngestionControl)
class FlatFileIngestionControlAdmin(admin.ModelAdmin):
    list_display = [
        "job",
        "schema_name",
        "table_name",
        "file_name",
        "file_hash",
        "rows_read",
        "rows_inserted",
        "rows_updated",
        "rows_skipped",
        "status",
        "processed_at",
    ]
    list_filter = ["status", "processed_at", "job"]
    search_fields = ["file_name", "file_hash", "schema_name", "table_name", "job__name"]
    readonly_fields = ["id", "processed_at"]
