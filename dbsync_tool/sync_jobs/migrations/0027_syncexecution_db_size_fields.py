from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sync_jobs", "0026_syncexecutionlog_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="syncexecution",
            name="source_database_size_bytes",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="syncexecution",
            name="target_database_size_bytes",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="syncexecution",
            name="size_collected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
