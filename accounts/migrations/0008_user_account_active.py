from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_processed_stripe_event"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="account_active",
            field=models.BooleanField(
                default=True,
                help_text="False after Stripe subscription ends; user can still sign in.",
            ),
        ),
    ]
