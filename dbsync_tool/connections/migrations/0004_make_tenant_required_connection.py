from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('connections', '0005_fix_null_tenants'),  # Run fix migration first
    ]

    operations = [
        migrations.AlterField(
            model_name='databaseconnection',
            name='tenant',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='tenant_connections',
                to='auth.user',
                null=False,
                db_index=True,
                help_text='Tenant (Admin user) who owns this connection'
            ),
        ),
    ]

