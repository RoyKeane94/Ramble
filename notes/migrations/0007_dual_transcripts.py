from django.db import migrations, models


def copy_legacy_gpt_transcript(apps, schema_editor):
    Note = apps.get_model("notes", "Note")
    for note in Note.objects.all().iterator():
        legacy = (note.gpt_transcript or "").strip()
        if legacy and not (note.gpt_transcribe_transcript or "").strip():
            note.gpt_transcribe_transcript = note.gpt_transcript
            note.save(update_fields=["gpt_transcribe_transcript"])


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0006_note_next_action_text_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="gpt_transcribe_transcript",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="note",
            name="whisper_1_transcript",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(copy_legacy_gpt_transcript, migrations.RunPython.noop),
    ]
