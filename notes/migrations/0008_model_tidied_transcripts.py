from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0007_dual_transcripts"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="gpt_transcribe_tidied_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="note",
            name="whisper_1_tidied_text",
            field=models.TextField(blank=True, default=""),
        ),
    ]
