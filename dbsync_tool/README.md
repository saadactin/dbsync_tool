# dbsync_tool

## Azure DevOps → ClickHouse (subprocess scripts)

Jobs with source **Azure DevOps** run `scripts/devops_Full_sync.py` (full) or `scripts/devops_Increment_sync.py` (incremental) via `sync_engine.azure_devops_runner`. Credentials are **not** embedded in the scripts: the runner sets environment variables from `APIConnection` (Azure) and `DatabaseConnection` (ClickHouse).

- Optional **`target_table_prefix`** on `SyncJob` is passed as `TARGET_TABLE_PREFIX`. Table names become `{prefix}_DEVOPS_WORKITEMS_MAIN`, `{prefix}_DEVOPS_SPRINTS`, etc. (same rule as `get_target_table_name` elsewhere).
- Incremental runs set `STRICT_INCREMENTAL_EXISTING_TABLES=1` so missing prefixed work-item tables fail fast.
- **Redis** (incremental resume/progress): set `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_KEY_PREFIX` on the Django process environment if not using defaults (`localhost:6379`). See `scripts/devops_config.py`.

### Manual verification checklist

1. Configure API + ClickHouse connections and create a DevOps sync job (optionally set table prefix).
2. Run **full** sync; confirm eight tables exist (`DEVOPS_WORKITEMS_*`, `DEVOPS_PROJECTS`, `DEVOPS_TEAMS`, `DEVOPS_SPRINTS` or prefixed).
3. Run **incremental** with no work-item changes; confirm `DEVOPS_SPRINTS` still refreshes (full replace each run).
4. Run **incremental** after a work-item change; confirm main/child tables update.

Rotate any credentials previously committed in git history.

## Sync job scheduling (hourly / daily)

- Schedules use Django’s default timezone (`TIME_ZONE` in settings). **Start Date/Time** on Step 4 (and job edit) is stored as `SyncSchedule.next_run_at` and defines the **wall-clock anchor** (hour and minute).
- **Hourly**: runs at the **same minute** every hour (e.g. `:07` → 00:07, 01:07, …). The first run is the next eligible slot after “now” with that minute.
- **Daily**: runs at the **same time every calendar day** (e.g. 14:05 daily). After each completed run, the next run is **+24 hours** at that time.
- **Weekly**: same local time on **Monday** (anchor from `next_run_at` when set).
- APScheduler registers cron triggers from that anchor; a **per-minute** due-job checker also picks up due jobs. `next_run_at` is updated when a run **finishes** in `SyncExecutor` (not when the trigger fires).
