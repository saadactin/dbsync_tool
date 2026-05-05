"""Add multi-format fields to FileSourceConnection."""
from django.db import migrations, models


def _set_default_format(apps, schema_editor):
    FileSourceConnection = apps.get_model('connections', 'FileSourceConnection')
    FileSourceConnection.objects.filter(file_format='').update(file_format='csv')


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("connections", "0012_alter_databaseconnection_db_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="filesourceconnection",
            name="file_format",
            field=models.CharField(
                choices=[
                    ("csv", "CSV"),
                    ("tsv", "TSV"),
                    ("txt", "Plain Text (delimited)"),
                    ("json", "JSON"),
                    ("jsonl", "JSON Lines (NDJSON)"),
                    ("xml", "XML"),
                    ("xlsx", "Excel Workbook (XLSX)"),
                ],
                default="csv",
                help_text="File format used by the parser engine.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="filesourceconnection",
            name="record_path",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "JSON: dotted path to a list of records (e.g. data.items). "
                    "XML: XPath-like record path (e.g. /root/items/item)."
                ),
                max_length=512,
            ),
        ),
        migrations.AddField(
            model_name="filesourceconnection",
            name="sheet_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="XLSX sheet name. Empty = first sheet.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="filesourceconnection",
            name="nested_strategy",
            field=models.CharField(
                choices=[
                    ("flatten", "Flatten with dot-paths"),
                    ("json_blob", "Keep nested values as JSON blobs"),
                ],
                default="flatten",
                help_text="How to handle nested JSON/XML structures.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="filesourceconnection",
            name="flatten_separator",
            field=models.CharField(
                default=".",
                help_text=(
                    "Separator for dot-path flattening "
                    "(only used when nested_strategy=flatten)."
                ),
                max_length=4,
            ),
        ),
        migrations.AlterField(
            model_name="filesourceconnection",
            name="delimiter",
            field=models.CharField(
                blank=True,
                default=",",
                help_text=(
                    "Delimiter character for CSV/TSV/TXT "
                    "(ignored for JSON/XML/XLSX)."
                ),
                max_length=1,
            ),
        ),
        migrations.AlterField(
            model_name="filesourceconnection",
            name="encoding",
            field=models.CharField(
                default="utf-8",
                help_text="File encoding (e.g., utf-8, utf-16, latin-1). Ignored for XLSX.",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="filesourceconnection",
            name="has_header",
            field=models.BooleanField(
                default=True,
                help_text="Whether the first row contains column headers (CSV/TSV/TXT/XLSX).",
            ),
        ),
        migrations.RunPython(_set_default_format, _noop),
    ]
