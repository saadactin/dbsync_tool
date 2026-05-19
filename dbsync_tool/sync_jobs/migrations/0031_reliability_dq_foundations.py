"""Day 1 of the 7-day reliability + DQ plan.

Adds the data-layer surfaces only - new fields with safe defaults and
three new tables that no existing code path touches yet. No runtime
behavior changes.

Operations grouped in this order (kept atomic in one migration so
deploy/rollback is a single hop):

  1. AddField  on SyncJobTable        (retry_policy, dead_letter_max_pct)
  2. AddField  on SyncCheckpoint      (dual-pointer + status fields)
  3. AddField  on SyncExecutionLog    (attempts, last_error_code, dead_letter_count)
  4. AddField  on SyncVerificationReport (metrics_json)
  5. CreateModel ProcessedBatch
  6. CreateModel SyncDeadLetterRow
  7. CreateModel ReconciliationReport
  8. RunPython backfill_checkpoint_pointers   (existing rows -> dual-pointer + status='clean')
  9. RunPython backfill_default_retry_policy  (existing rows with empty policy -> defaults)
"""

from django.db import migrations, models
import django.db.models.deletion
import uuid


def _default_retry_policy():
    return {
        "max_retries": 3,
        "initial_delay": 1.0,
        "backoff": 2.0,
        "retryable_errors": ["timeout", "conn_reset", "deadlock"],
    }


def backfill_checkpoint_pointers(apps, schema_editor):
    """Seed the new dual-pointer fields from the existing ``last_value``.

    Idempotent: only writes rows where the new pointers are still NULL.
    """
    SyncCheckpoint = apps.get_model("sync_jobs", "SyncCheckpoint")
    db_alias = schema_editor.connection.alias

    qs = SyncCheckpoint.objects.using(db_alias).filter(
        last_seen_value__isnull=True,
        last_committed_value__isnull=True,
    )
    for cp in qs.iterator(chunk_size=500):
        cp.last_seen_value = cp.last_value
        cp.last_committed_value = cp.last_value
        if not cp.checkpoint_status:
            cp.checkpoint_status = "clean"
        cp.save(
            update_fields=[
                "last_seen_value",
                "last_committed_value",
                "checkpoint_status",
            ]
        )


def backfill_default_retry_policy(apps, schema_editor):
    """Populate ``retry_policy`` for existing tables that have an empty dict."""
    SyncJobTable = apps.get_model("sync_jobs", "SyncJobTable")
    db_alias = schema_editor.connection.alias

    default_policy = _default_retry_policy()
    for tbl in SyncJobTable.objects.using(db_alias).iterator(chunk_size=500):
        # JSONField default=dict gives {} on existing rows post-AddField; only
        # backfill when the field is empty/None to avoid stomping any value
        # already configured by an operator.
        if not tbl.retry_policy:
            tbl.retry_policy = default_policy
            tbl.save(update_fields=["retry_policy"])


class Migration(migrations.Migration):

    dependencies = [
        ("sync_jobs", "0030_add_verification_mode"),
    ]

    operations = [
        # ----- Step 1: SyncJobTable -----
        migrations.AddField(
            model_name="syncjobtable",
            name="retry_policy",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Per-table retry policy. Schema: "
                    "{'max_retries': int, 'initial_delay': float, 'backoff': float, "
                    "'retryable_errors': [str]}"
                ),
            ),
        ),
        migrations.AddField(
            model_name="syncjobtable",
            name="dead_letter_max_pct",
            field=models.FloatField(
                default=0.001,
                help_text=(
                    "Maximum allowed dead-letter rate per run for this table "
                    "(fraction of rows seen). 0 = fail-fast on first bad row."
                ),
            ),
        ),
        # ----- Step 2: SyncCheckpoint -----
        migrations.AddField(
            model_name="synccheckpoint",
            name="last_seen_value",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="synccheckpoint",
            name="last_committed_value",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="synccheckpoint",
            name="checkpoint_status",
            field=models.CharField(
                choices=[
                    ("clean", "Clean"),
                    ("dirty", "Dirty"),
                    ("recovering", "Recovering"),
                ],
                db_index=True,
                default="clean",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="synccheckpoint",
            name="last_successful_batch_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="synccheckpoint",
            name="last_status_reason",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        # ----- Step 3: SyncExecutionLog -----
        migrations.AddField(
            model_name="syncexecutionlog",
            name="attempts",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="syncexecutionlog",
            name="last_error_code",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="syncexecutionlog",
            name="dead_letter_count",
            field=models.IntegerField(default=0),
        ),
        # ----- Step 4: SyncVerificationReport -----
        migrations.AddField(
            model_name="syncverificationreport",
            name="metrics_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        # ----- Step 5: ProcessedBatch -----
        migrations.CreateModel(
            name="ProcessedBatch",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("schema_name", models.CharField(max_length=255)),
                ("table_name", models.CharField(max_length=255)),
                ("batch_id", models.CharField(max_length=64)),
                ("row_count", models.BigIntegerField(default=0)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("committed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("started", "Started"),
                            ("committed", "Committed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="started",
                        max_length=20,
                    ),
                ),
                (
                    "execution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="processed_batches",
                        to="sync_jobs.syncexecution",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="processed_batches",
                        to="sync_jobs.syncjob",
                    ),
                ),
            ],
            options={
                "db_table": "processed_batches",
            },
        ),
        migrations.AddIndex(
            model_name="processedbatch",
            index=models.Index(
                fields=["job", "schema_name", "table_name"],
                name="processed_b_job_id_2751e8_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="processedbatch",
            index=models.Index(
                fields=["execution", "status"],
                name="processed_b_executi_a18430_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="processedbatch",
            constraint=models.UniqueConstraint(
                fields=["execution", "schema_name", "table_name", "batch_id"],
                name="uniq_processed_batch_per_run",
            ),
        ),
        # ----- Step 6: SyncDeadLetterRow -----
        migrations.CreateModel(
            name="SyncDeadLetterRow",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("schema_name", models.CharField(max_length=255)),
                ("table_name", models.CharField(max_length=255)),
                ("batch_id", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "source_pk_text",
                    models.CharField(blank=True, max_length=512, null=True),
                ),
                (
                    "source_row_hash",
                    models.CharField(blank=True, max_length=128, null=True),
                ),
                ("raw_row_json", models.JSONField(blank=True, null=True)),
                ("error_code", models.CharField(max_length=64)),
                ("error_message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "execution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dead_letter_rows",
                        to="sync_jobs.syncexecution",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dead_letter_rows",
                        to="sync_jobs.syncjob",
                    ),
                ),
            ],
            options={
                "db_table": "sync_dead_letter_rows",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="syncdeadletterrow",
            index=models.Index(
                fields=["execution", "schema_name", "table_name"],
                name="sync_dead_l_executi_3c2b06_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="syncdeadletterrow",
            index=models.Index(
                fields=["job", "-created_at"],
                name="sync_dead_l_job_id_b123bd_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="syncdeadletterrow",
            index=models.Index(
                fields=["error_code"],
                name="sync_dead_l_error_c_8b9a1f_idx",
            ),
        ),
        # ----- Step 7: ReconciliationReport -----
        migrations.CreateModel(
            name="ReconciliationReport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("schema_name", models.CharField(max_length=255)),
                ("table_name", models.CharField(max_length=255)),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("ok", "OK"),
                            ("warning", "Warning"),
                            ("repair_full", "Repair Full"),
                            ("repair_incremental", "Repair Incremental"),
                        ],
                        db_index=True,
                        default="ok",
                        max_length=24,
                    ),
                ),
                ("confidence", models.FloatField(default=1.0)),
                ("source_metrics_json", models.JSONField(blank=True, default=dict)),
                ("target_metrics_json", models.JSONField(blank=True, default=dict)),
                ("drift_json", models.JSONField(blank=True, default=dict)),
                ("dq_pre_json", models.JSONField(blank=True, default=dict)),
                ("dq_post_json", models.JSONField(blank=True, default=dict)),
                ("snapshots_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "execution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reconciliation_reports",
                        to="sync_jobs.syncexecution",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reconciliation_reports",
                        to="sync_jobs.syncjob",
                    ),
                ),
            ],
            options={
                "db_table": "reconciliation_reports",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="reconciliationreport",
            index=models.Index(
                fields=["job", "-created_at"],
                name="reconciliat_job_id_95e7b2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="reconciliationreport",
            index=models.Index(
                fields=["decision"],
                name="reconciliat_decisio_4b4fc4_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="reconciliationreport",
            constraint=models.UniqueConstraint(
                fields=["execution", "schema_name", "table_name"],
                name="uniq_reconciliation_report_per_table",
            ),
        ),
        # ----- Steps 8 & 9: data backfills -----
        migrations.RunPython(
            backfill_checkpoint_pointers,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            backfill_default_retry_policy,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
