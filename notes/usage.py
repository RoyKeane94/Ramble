from django.db.models import Q, Sum

DEFAULT_MINUTE_CAP = 600
ASSEMBLY_OPERATION = "assembly_cloud"


def cap_for_user(user):
    cap = getattr(user, "minute_cap", None)
    if cap is None or cap <= 0:
        return DEFAULT_MINUTE_CAP
    return int(cap)


def allowance_seconds(operation, success, audio_seconds, metadata):
    """Seconds that count against the account. Zero when this event should not bill."""
    if operation != ASSEMBLY_OPERATION:
        return 0.0
    try:
        seconds = float(audio_seconds or 0)
    except (TypeError, ValueError):
        return 0.0
    if seconds <= 0:
        return 0.0
    transcript_id = ""
    if isinstance(metadata, dict):
        transcript_id = str(metadata.get("transcript_id") or "").strip()
    if success or transcript_id:
        return seconds
    return 0.0


def logged_assembly_seconds(user):
    from core.models import ModelUsageLog

    if not getattr(user, "pk", None):
        return 0.0
    seconds = (
        ModelUsageLog.objects.filter(
            user=user,
            operation=ASSEMBLY_OPERATION,
            audio_seconds__gt=0,
        )
        .filter(Q(success=True) | Q(metadata__transcript_id__gt=""))
        .aggregate(total=Sum("audio_seconds"))["total"]
    )
    return max(0.0, float(seconds or 0))


def assembly_seconds_for_user(user):
    stored = max(0.0, float(getattr(user, "billed_seconds", 0) or 0))
    logged = logged_assembly_seconds(user)
    total = max(stored, logged)
    if logged > stored and getattr(user, "pk", None):
        type(user).objects.filter(pk=user.pk, billed_seconds__lt=logged).update(billed_seconds=logged)
    return total


def usage_for_user(user):
    used = assembly_seconds_for_user(user) / 60.0
    cap = cap_for_user(user)
    remaining = max(0.0, cap - used)
    used_clamped = min(float(cap), used)
    remaining_clamped = max(0.0, remaining)

    def _label(value):
        if value >= 10:
            return str(int(value))
        return f"{value:.1f}"

    remaining_label = _label(remaining_clamped)
    if remaining <= 0:
        remaining_copy = f"You've used your {cap} minutes."
    elif remaining_label == "1":
        remaining_copy = "1 minute left"
    else:
        remaining_copy = f"{remaining_label} minutes left"

    return {
        "cap_minutes": cap,
        "used_minutes": used,
        "remaining_minutes": remaining,
        "used_minutes_label": _label(used_clamped),
        "remaining_minutes_label": remaining_label,
        "remaining_copy": remaining_copy,
        "used_percent": min(100.0, (used / cap) * 100.0) if cap else 0.0,
        "is_exhausted": remaining <= 0,
    }
