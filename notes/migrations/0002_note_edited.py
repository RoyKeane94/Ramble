from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="edited_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="note",
            name="edited_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
