from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="minute_cap",
            field=models.PositiveIntegerField(
                default=600,
                help_text="Recording allowance for this account, in minutes.",
            ),
        ),
    ]
