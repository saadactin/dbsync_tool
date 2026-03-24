from django.contrib import admin
from .models import SyncJob, SyncJobTable, SyncSchedule, SyncCheckpoint, SyncExecution, SyncExecutionLog

@admin.register(SyncJob)
class SyncJobAdmin(admin.ModelAdmin):
    list_display = ['name', 'source_connection', 'target_connection', 'sync_type', 'status', 'created_by', 'created_at']
    list_filter = ['sync_type', 'status', 'created_at']
    search_fields = ['name']
    readonly_fields = ['id', 'created_at', 'updated_at']

@admin.register(SyncJobTable)
class SyncJobTableAdmin(admin.ModelAdmin):
    list_display = ['job', 'schema_name', 'table_name', 'incremental_column', 'is_enabled']
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
    list_display = ['execution', 'schema_name', 'table_name', 'status', 'rows_fetched', 'rows_inserted', 'started_at', 'completed_at']
    list_filter = ['status', 'execution']
    search_fields = ['schema_name', 'table_name', 'execution__job__name']
    readonly_fields = ['id']
