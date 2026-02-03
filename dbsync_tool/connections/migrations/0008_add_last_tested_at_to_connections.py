# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0007_alter_apiconnection_selected_modules'),
    ]

    operations = [
        migrations.AddField(
            model_name='databaseconnection',
            name='last_tested_at',
            field=models.DateTimeField(blank=True, help_text='Last time this connection was successfully tested', null=True),
        ),
        migrations.AddField(
            model_name='apiconnection',
            name='last_tested_at',
            field=models.DateTimeField(blank=True, help_text='Last time this connection was successfully tested', null=True),
        ),
    ]
