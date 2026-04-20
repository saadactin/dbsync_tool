from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sync_jobs", "0025_syncexecution_total_source_bytes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="syncexecutionlog",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]

