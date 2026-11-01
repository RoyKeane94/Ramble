from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_user_mcp_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="take_ready_webhook_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="user",
            name="take_ready_webhook_key",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="user",
            name="take_ready_webhook_saved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
