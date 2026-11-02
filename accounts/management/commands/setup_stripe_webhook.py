from django.core.management.base import BaseCommand, CommandError

from accounts.stripe_billing import (
    WEBHOOK_EVENTS,
    StripeNotConfigured,
    ensure_webhook_endpoint,
)


class Command(BaseCommand):
    help = (
        "Create or update the Stripe webhook event destination for Ramble billing. "
        "Prints the signing secret when a new endpoint is created."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            required=True,
            help="Public HTTPS URL for /api/stripe/webhook/ (e.g. https://yourramble.com/api/stripe/webhook/)",
        )

    def handle(self, *args, **options):
        url = options["url"].strip()
        if not url.startswith("https://"):
            raise CommandError("Webhook URL must be https://…")
        if not url.rstrip("/").endswith("/api/stripe/webhook"):
            self.stdout.write(
                self.style.WARNING(
                    "URL does not end with /api/stripe/webhook — make sure this is intentional."
                )
            )

        try:
            endpoint, created = ensure_webhook_endpoint(url)
        except StripeNotConfigured as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(f"Stripe API error: {exc}") from exc

        self.stdout.write(f"Endpoint id: {endpoint.id}")
        self.stdout.write(f"URL: {endpoint.url}")
        self.stdout.write("Events:")
        for name in WEBHOOK_EVENTS:
            self.stdout.write(f"  - {name}")

        if created:
            secret = getattr(endpoint, "secret", None) or ""
            self.stdout.write(self.style.SUCCESS("Created new webhook destination."))
            if secret:
                self.stdout.write(
                    self.style.NOTICE(
                        f"Add this to STRIPE_WEBHOOK_SECRET (shown once):\n{secret}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "No signing secret returned. Check the Stripe Dashboard for the endpoint secret."
                    )
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Updated existing webhook destination events. "
                    "Keep your current STRIPE_WEBHOOK_SECRET."
                )
            )
