"""
SAP sync state helpers for storing and retrieving record hashes per job/endpoint.
Used by SAPSyncExecutor for hash-based incremental change detection.
"""
from sync_jobs.models import APISyncState


def get_hashes(job, endpoint_name: str) -> dict:
    """
    Get stored record hashes for a job and endpoint.

    Args:
        job: SyncJob instance
        endpoint_name: Endpoint name (e.g. JournalEntries)

    Returns:
        Dict mapping record_id -> hash string; empty dict if no state or no hashes
    """
    state = APISyncState.get_for_module(job, endpoint_name)
    if state is None:
        return {}
    return state.record_hashes or {}


def save_hashes(job, endpoint_name: str, hashes_dict: dict):
    """
    Save record hashes for a job and endpoint.

    Args:
        job: SyncJob instance
        endpoint_name: Endpoint name
        hashes_dict: Dict mapping record_id -> hash string
    """
    state, created = APISyncState.objects.get_or_create(
        job=job,
        module_name=endpoint_name,
        defaults={'record_hashes': hashes_dict},
    )
    if not created:
        state.record_hashes = hashes_dict
        state.save(update_fields=['record_hashes', 'updated_at'])


def get_or_create_state(job, endpoint_name: str):
    """
    Get or create APISyncState for (job, endpoint_name).

    Args:
        job: SyncJob instance
        endpoint_name: Endpoint name

    Returns:
        APISyncState instance
    """
    state, _ = APISyncState.objects.get_or_create(
        job=job,
        module_name=endpoint_name,
        defaults={}
    )
    return state
