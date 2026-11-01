import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction

log = logging.getLogger("ramble.webhooks")


def note_is_ready(note):
    if note is None:
        return False
    if note.is_processing or note.processing_failed:
        return False
    return bool((note.display_text or "").strip())


def notify_take_ready(note, *, previously_ready=False):
    """One wake-up ping to the user's Grok Bot webhook when a take first becomes ready."""
    if previously_ready or not note_is_ready(note):
        return

    user = getattr(note, "user", None)
    if user is None:
        return
    if not user.has_mcp_token or not user.has_take_ready_webhook:
        return

    url = user.take_ready_webhook_url.strip()
    key = user.take_ready_webhook_key.strip()
    payload = {
        "event": "take.ready",
        "take_id": str(note.id),
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Ramble/1.0",
    }

    def _send():
        request = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = getattr(response, "status", 200)
                if status not in (200, 202):
                    log.warning(
                        "take.ready webhook unexpected status=%s take_id=%s",
                        status,
                        note.id,
                    )
                else:
                    log.info("take.ready webhook accepted take_id=%s status=%s", note.id, status)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            log.warning(
                "take.ready webhook failed take_id=%s status=%s detail=%s",
                note.id,
                exc.code,
                detail,
            )
        except Exception:
            log.exception("take.ready webhook error take_id=%s", note.id)

    def _dispatch():
        if getattr(settings, "TAKE_READY_WEBHOOK_INLINE", False):
            _send()
        else:
            threading.Thread(target=_send, daemon=True).start()

    transaction.on_commit(_dispatch)
