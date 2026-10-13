import logging

from notes.usage import usage_for_user

logger = logging.getLogger("ramble.usage")


def minute_usage(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    try:
        return {"minute_usage": usage_for_user(user)}
    except Exception:
        logger.exception("minute_usage context processor failed for user pk=%s", getattr(user, "pk", None))
        return {}
