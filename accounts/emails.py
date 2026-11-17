import logging
import re
from datetime import timedelta, timezone as dt_timezone

import resend
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

log = logging.getLogger("ramble.email")

WELCOME_SUBJECT = "You're in. Here's how to start"
CHECK_IN_SUBJECT = "Quick check-in"
CHECK_IN_DELAY = timedelta(days=3)


def greeting_name(email: str) -> str:
    local = (email or "").split("@", 1)[0]
    token = local.split("+", 1)[0]
    token = re.sub(r"[._\-]+", " ", token).strip()
    parts = [part for part in token.split() if part.isalpha()]
    if not parts:
        return "there"
    return " ".join(part.capitalize() for part in parts)


def _email_context(*, email: str) -> dict:
    base = getattr(settings, "PUBLIC_BASE_URL", "https://yourramble.com").rstrip("/")
    app_store_url = getattr(
        settings,
        "APP_STORE_URL",
        "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
    )
    return {
        "first_name": greeting_name(email),
        "email": email,
        "app_store_url": app_store_url,
        "site_url": base,
        "billing_url": f"{base}/settings/",
        "privacy_url": f"{base}/privacy/",
    }


def _send_resend(
    *,
    email: str,
    subject: str,
    html_template: str,
    text_template: str,
    scheduled_at: str | None = None,
) -> bool:
    api_key = getattr(settings, "RESEND_API_KEY", "").strip()
    if not api_key:
        log.warning("Skipping email (%s) — RESEND_API_KEY is not configured", subject)
        return False

    context = _email_context(email=email)
    payload = {
        "from": getattr(
            settings,
            "DEFAULT_FROM_EMAIL",
            "Tom <hello@mail.yourramble.com>",
        ),
        "to": [email],
        "reply_to": getattr(settings, "EMAIL_REPLY_TO", "tom@yourramble.com"),
        "subject": subject,
        "html": render_to_string(html_template, context),
        "text": render_to_string(text_template, context),
    }
    if scheduled_at:
        payload["scheduled_at"] = scheduled_at

    resend.api_key = api_key
    try:
        resend.Emails.send(payload)
    except Exception:
        log.exception("Failed to send email subject=%s to=%s", subject, email)
        return False

    if scheduled_at:
        log.info("Scheduled email subject=%s to=%s at=%s", subject, email, scheduled_at)
    else:
        log.info("Sent email subject=%s to=%s", subject, email)
    return True


def send_welcome_email(*, email: str) -> bool:
    """Send the post-signup welcome email via Resend. Returns True on success."""
    return _send_resend(
        email=email,
        subject=WELCOME_SUBJECT,
        html_template="emails/welcome.html",
        text_template="emails/welcome.txt",
    )


def send_check_in_email(*, email: str, scheduled_at: str | None = None) -> bool:
    """Send (or schedule) the day-3 check-in email via Resend."""
    return _send_resend(
        email=email,
        subject=CHECK_IN_SUBJECT,
        html_template="emails/check_in.html",
        text_template="emails/check_in.txt",
        scheduled_at=scheduled_at,
    )


def schedule_check_in_email_for_user(user) -> bool:
    """
    Queue the day-3 check-in for a user if not already scheduled.

    Uses Resend scheduled_at when the user is still within the first 3 days;
    sends immediately once that window has passed.
    """
    if getattr(user, "check_in_email_scheduled_at", None) is not None:
        return False

    now = timezone.now()
    due_at = user.date_joined + CHECK_IN_DELAY
    if due_at > now:
        scheduled_at = due_at.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        scheduled_at = None

    if not send_check_in_email(email=user.email, scheduled_at=scheduled_at):
        return False

    user.check_in_email_scheduled_at = now
    user.save(update_fields=["check_in_email_scheduled_at"])
    return True
