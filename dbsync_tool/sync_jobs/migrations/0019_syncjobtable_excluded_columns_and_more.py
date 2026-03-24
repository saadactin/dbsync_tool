from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sync_jobs", "0018_syncjob_source_file_connection_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="syncjobtable",
            name="excluded_columns",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of source column names excluded from migration (lowercased).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="syncjobtable",
            name="protected_columns",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Resolved protected source columns always included in migration (lowercased).",
                null=True,
            ),
        ),
    ]
