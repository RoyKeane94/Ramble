from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0005_note_next_action_text"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "UPDATE notes_note SET next_action_text = '' "
                "WHERE next_action_text IS NULL;"
                "ALTER TABLE notes_note "
                "ALTER COLUMN next_action_text SET DEFAULT '';"
            ),
            reverse_sql=(
                "ALTER TABLE notes_note "
                "ALTER COLUMN next_action_text DROP DEFAULT;"
            ),
        ),
        migrations.AlterField(
            model_name="note",
            name="next_action_text",
            field=models.TextField(blank=True, default=""),
        ),
    ]
