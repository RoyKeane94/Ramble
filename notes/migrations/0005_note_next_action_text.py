from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0004_album"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="next_action_text",
            field=models.TextField(blank=True, default=""),
        ),
    ]
