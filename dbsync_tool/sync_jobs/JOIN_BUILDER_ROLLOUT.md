# Join Builder Rollout Notes

## What changed
- Step 3 Model Data now supports a visual builder mode:
  - `single_table`
  - `join` (`INNER`, `LEFT`, `RIGHT`, `FULL`)
  - `union`
  - `lookup`
  - `custom_sql` (admin-only)
- Builder payloads are compiled server-side into canonical transform plans.
- Existing JSON plans remain supported and still validate through the same contract.

## Safety rules
- Physical column validation remains enforced during preview and submit.
- Incremental and runtime constraints are unchanged.
- `custom_sql` is admin-only and preview-safe:
  - must be one `SELECT`
  - no semicolons
  - blocks DDL/DML keywords

## Backward compatibility
- Existing `sync_job_transform_plan` session and persisted job data continue to work.
- Builder state is stored separately in `sync_job_transform_builder`.
- Submit compiles builder payloads into the existing plan contract before Step 3 mapping.

## Operational checklist
- Verify Step 3 page renders mode selector and panels per table.
- Validate preview works for join builder with suggested keys.
- Confirm non-admin users cannot use `custom_sql`.
- Confirm admin can preview `custom_sql` safely.
- Run focused test suites:
  - `sync_jobs.tests.test_wizard_model_step`
  - `sync_engine.tests.test_transform_runtime`

## Fallback plan
- If builder behavior is unexpected, users can still edit and submit JSON plans.
- Remove/hide builder controls in template while preserving backend compatibility.
