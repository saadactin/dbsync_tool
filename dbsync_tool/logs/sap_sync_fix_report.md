# SAP Sync Failure Report & Resolution
Job: sap222
Execution: fd2b740...
Date: 2026-03-17 10:36:55

## Failure Diagnosis
The sync job failed almost immediately with the following error:
`Error: You cannot call this from an async context - use a thread or sync_to_async.`

### Root Cause
This is a `SynchronousOnlyOperation` error triggered by Django. It occurred because the new "Ultra-Optimized" SAP sync engine uses an asynchronous event loop (to allow for parallel page fetching), but it was attempting to perform synchronous database operations (like creating execution logs or reading job tables) directly within that async loop. 

Django protects the database from unsafe access by preventing synchronous ORM calls from running inside an async event loop without explicit wrapping.

## Resolution Steps
1.  **ORM Wrapping**: All direct calls to the Django database (creating logs, updating row counts, etc.) in `sap_optimized.py` have been wrapped with `asgiref.sync.sync_to_async`.
2.  **Credential Safety**: The retrieval of connection parameters in the `AsyncSAPConnector` has also been wrapped to ensure it safely accesses the model data from the async thread.
3.  **Bridge Maintenance**: The bridge between the synchronous sync job framework and the asynchronous optimization logic is now thread-safe.

## Impact
The `sap222` job (and all future SAP syncs) can now benefit from both high-performance parallel fetching and reliable Django logging without triggering context errors.

**Status: FIXED**
Recommended Action: Please re-run the `sap222` job.
