import os
import sys
import django

# Set up Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from sync_jobs.models import SyncJob, SyncExecution, SyncExecutionLog

def check_errors():
    try:
        # Find the post_increment job
        job = SyncJob.objects.filter(name='post_increment').first()
        if not job:
            print("Job 'post_increment' not found")
            return

        # Get latest execution
        execution = SyncExecution.objects.filter(job=job).order_by('-started_at').first()
        if not execution:
            print("No executions found for this job")
            return

        print(f"Latest Execution: {execution.id}")
        print(f"Status: {execution.status}")
        
        # Get logs for this execution
        logs = SyncExecutionLog.objects.filter(execution=execution)
        
        for log in logs:
            if log.status == 'failed':
                print(f"\n--- Detailed error for {log.schema_name}.{log.table_name} ---")
                print(log.error_message)
                print("---------------------------------------------------")

    except Exception as e:
        print(f"Error running script: {e}")

if __name__ == "__main__":
    check_errors()
