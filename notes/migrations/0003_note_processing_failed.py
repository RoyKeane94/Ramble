from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0002_note_edited"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="processing_failed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="note",
            name="processing_error",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
