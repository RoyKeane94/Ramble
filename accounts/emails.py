import logging
import re

import resend
from django.conf import settings
from django.template.loader import render_to_string

log = logging.getLogger("ramble.email")

WELCOME_SUBJECT = "You're in. Here's how to start"


def greeting_name(email: str) -> str:
    local = (email or "").split("@", 1)[0]
    token = local.split("+", 1)[0]
    token = re.sub(r"[._\-]+", " ", token).strip()
    parts = [part for part in token.split() if part.isalpha()]
    if not parts:
        return "there"
    return " ".join(part.capitalize() for part in parts)


def send_welcome_email(*, email: str) -> bool:
    """Send the post-signup welcome email via Resend. Returns True on success."""
    api_key = getattr(settings, "RESEND_API_KEY", "").strip()
    if not api_key:
        log.warning("Skipping welcome email — RESEND_API_KEY is not configured")
        return False

    base = getattr(settings, "PUBLIC_BASE_URL", "https://yourramble.com").rstrip("/")
    app_store_url = getattr(
        settings,
        "APP_STORE_URL",
        "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
    )
    context = {
        "first_name": greeting_name(email),
        "email": email,
        "app_store_url": app_store_url,
        "site_url": base,
        "billing_url": f"{base}/settings/",
        "privacy_url": f"{base}/privacy/",
    }
    html = render_to_string("emails/welcome.html", context)
    text = render_to_string("emails/welcome.txt", context)

    resend.api_key = api_key
    try:
        resend.Emails.send(
            {
                "from": getattr(
                    settings,
                    "DEFAULT_FROM_EMAIL",
                    "Tom <hello@mail.yourramble.com>",
                ),
                "to": [email],
                "reply_to": getattr(settings, "EMAIL_REPLY_TO", "tom@yourramble.com"),
                "subject": WELCOME_SUBJECT,
                "html": html,
                "text": text,
            }
        )
    except Exception:
        log.exception("Failed to send welcome email to=%s", email)
        return False

    log.info("Sent welcome email to=%s", email)
    return True
