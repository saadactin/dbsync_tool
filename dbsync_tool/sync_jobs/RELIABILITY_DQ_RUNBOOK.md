# Reliability + DQ Runbook (Day 1-7)

## Scope
Operational guidance for the reliability stack implemented across Day 1-7:
- retry policy and transient failure handling
- idempotent batch commits and rerun safety
- dead-letter thresholding and row triage
- DQ pre/post packs and reconciliation artifacts
- drift and SLO breach alerting
- ops health dashboard and smoke command

## Core Signals
- **Execution summary email**: always sent (best effort) at execution close.
- **Drift alert email**: sent when per-table decision is non-OK or confidence below floor.
- **SLO breach email**: sent only when the same SLO is breached for `N` consecutive terminal executions.
- **Structured drift logger**: `sync_jobs.drift`.

## Retries (Day 3)
- Table-level retries are controlled by retry policy.
- `attempts` and `last_error_code` are persisted in `SyncExecutionLog`.
- Elevated `attempts_p95` is a signal of upstream instability.

### Actions
1. Identify top noisy tables via execution logs (high `attempts`).
2. Validate source/target connectivity and lock contention.
3. Tune source query complexity and batch size before widening retry budget.

## Dead-letter Threshold (Day 4)
- Row-level failures are captured in `SyncDeadLetterRow`.
- Threshold (max %) prevents silent data loss and fails table when exceeded.

### Actions
1. Compare `dead_letter_count` with `rows_fetched`.
2. If under threshold: continue run, triage rows post-run.
3. If consistently near threshold: inspect transform/schema mismatches and malformed rows.
4. Do **not** blindly increase threshold without root-cause confirmation.

## Reconciliation Report (Day 5/6)
- Download from execution detail page:
  - `Report (JSON)`
  - `Report (CSV)`
- Source of truth:
  - `ReconciliationReport` rows (per table, per execution)
  - plus `SyncExecutionLog` merge for operational counters.

### Interpret Decisions
- `ok`: no action.
- `warning`: inspect parity/distribution drift and confidence.
- `repair_incremental`: targeted replay recommended.
- `repair_full`: full-table repair required.

## snapshots_json Backfill (Day 7)
- For non-OK post-pack decisions, up to 50 dead-letter rows are mirrored into `snapshots_json`.
- Purpose: quick triage context without opening raw dead-letter table.

### Actions
1. Open report JSON and inspect `snapshots_json.rows`.
2. Use `source_pk_text`, `error_code`, `error_message` to classify failure type.
3. Execute targeted remediation and rerun.

## Ops Health Page (Day 7)
- URL: `/sync-jobs/ops/health/`
- Windows:
  - default `24h`
  - `7d` toggle
- Includes:
  - rollup cards (OK rate, dead-letter %, retry p95, confidence floor)
  - per-job grid with decision chips and drift counters.

## SLO Definitions
Configured in `settings.py` (env override supported):
- `SLO_RECONCILIATION_OK_RATE` (default `0.99`)
- `SLO_DEAD_LETTER_PCT_MAX` (default `0.001`)
- `SLO_RETRY_ATTEMPT_P95` (default `1`)
- `SLO_DRIFT_CONFIDENCE_FLOOR` (default `0.8`)
- `SLO_BREACH_STREAK_N` (default `3`)

### Breach Semantics
- Detector checks latest terminal executions for a job.
- Breach emitted only when the same SLO is violated across the full streak window.
- Single-run spikes should not page.

## Smoke Command
Run:

```bash
python manage.py reliability_smoke
```

Quick checklist-only mode:

```bash
python manage.py reliability_smoke --skip-tests
```

The smoke command executes focused reliability/DQ test labels and exits non-zero on any failure.

## Incident Triage Flow
1. Check execution detail and reconciliation decision chip.
2. Download report JSON and inspect drift/parity/confidence.
3. If dead-letter present, inspect `snapshots_json` and dead-letter rows.
4. Validate retry behavior (`attempts`, error codes, connector health).
5. Confirm tenant-scoped ops health trend (`24h` then `7d`).
6. If SLO breach email fired, verify breach streak and isolate repeated failure mode.

## Glossary
- **DQ Pack**: pre/post structured quality metrics block.
- **Drift**: measurable mismatch in parity/distribution/confidence.
- **Dead-letter row**: single failed row captured non-fatally.
- **SLO**: service-level objective threshold for reliability health.
- **Streak breach**: same SLO violated across `N` recent terminal executions.
- **Terminal execution**: execution status in `{completed, failed}`.
