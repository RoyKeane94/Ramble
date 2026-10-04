from django.db import migrations, models
from django.db.models import Q, Sum


def backfill_billed_seconds(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Usage = apps.get_model("core", "ModelUsageLog")
    for user in User.objects.all().iterator():
        seconds = (
            Usage.objects.filter(
                user_id=user.pk,
                operation="assembly_cloud",
                audio_seconds__gt=0,
            )
            .filter(Q(success=True) | Q(metadata__transcript_id__gt=""))
            .aggregate(total=Sum("audio_seconds"))["total"]
        )
        user.billed_seconds = max(0.0, float(seconds or 0))
        user.save(update_fields=["billed_seconds"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_minute_cap"),
        ("core", "0002_model_usage_log"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="billed_seconds",
            field=models.FloatField(
                default=0,
                help_text="AssemblyAI audio already counted against this account, in seconds.",
            ),
        ),
        migrations.RunPython(backfill_billed_seconds, migrations.RunPython.noop),
    ]
