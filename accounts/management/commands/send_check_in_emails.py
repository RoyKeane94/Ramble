from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.emails import schedule_check_in_email_for_user

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Queue day-3 check-in emails via Resend for users who have not received one yet. "
        "Schedules for date_joined + 3 days when still upcoming; otherwise sends now."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List eligible users without sending.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max users to process (0 = no limit).",
        )

    def handle(self, *args, **options):
        qs = (
            User.objects.filter(
                is_active=True,
                account_active=True,
                check_in_email_scheduled_at__isnull=True,
            )
            .exclude(email="")
            .order_by("date_joined")
        )
        limit = options["limit"]
        if limit:
            qs = qs[:limit]

        dry_run = options["dry_run"]
        queued = 0
        skipped = 0
        for user in qs:
            if dry_run:
                self.stdout.write(f"would queue {user.email} (joined {user.date_joined.isoformat()})")
                queued += 1
                continue
            if schedule_check_in_email_for_user(user):
                queued += 1
                self.stdout.write(self.style.SUCCESS(f"queued {user.email}"))
            else:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"skipped {user.email}"))

        self.stdout.write(
            self.style.NOTICE(f"done queued={queued} skipped={skipped} dry_run={dry_run}")
        )
