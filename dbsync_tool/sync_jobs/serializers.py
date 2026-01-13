"""
REST API serializers
"""
from rest_framework import serializers
from sync_jobs.models import SyncJob, SyncExecution, SyncJobTable, SyncSchedule
from connections.models import DatabaseConnection


class SyncJobSerializer(serializers.ModelSerializer):
    """Serializer for SyncJob"""
    source_connection_name = serializers.CharField(source='source_connection.name', read_only=True)
    target_connection_name = serializers.CharField(source='target_connection.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = SyncJob
        fields = [
            'id', 'name', 'source_connection', 'target_connection',
            'source_connection_name', 'target_connection_name',
            'sync_type', 'status', 'created_by', 'created_by_username',
            'created_at', 'updated_at', 'last_run_at', 'next_run_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']


class SyncJobCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating SyncJob"""
    class Meta:
        model = SyncJob
        fields = [
            'name', 'source_connection', 'target_connection',
            'sync_type',
        ]
    
    def create(self, validated_data):
        # Set created_by from request user
        validated_data['created_by'] = self.context['request'].user
        job = SyncJob.objects.create(**validated_data)
        return job


class SyncExecutionSerializer(serializers.ModelSerializer):
    """Serializer for SyncExecution"""
    job_name = serializers.CharField(source='job.name', read_only=True)
    
    class Meta:
        model = SyncExecution
        fields = [
            'id', 'job', 'job_name', 'status',
            'started_at', 'completed_at',
            'total_tables', 'completed_tables',
            'total_rows_synced', 'error_message',
        ]
        read_only_fields = ['id']

