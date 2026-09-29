from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0008_model_tidied_transcripts"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="chosen_transcription_model",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
        migrations.AddField(
            model_name="note",
            name="transcription_route_summary",
            field=models.TextField(blank=True, default=""),
        ),
    ]
