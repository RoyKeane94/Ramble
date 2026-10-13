from django.db.models import Q, Sum
from django.utils import timezone

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


def billing_period_bounds(now=None):
    """
    Current calendar month in the project timezone (settings.TIME_ZONE).
    Returns (start, end) as aware datetimes with end exclusive.
    """
    now = now or timezone.now()
    local = timezone.localtime(now)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def logged_assembly_seconds(user, *, period_start=None, period_end=None):
    from core.models import ModelUsageLog

    if not getattr(user, "pk", None):
        return 0.0
    if period_start is None or period_end is None:
        period_start, period_end = billing_period_bounds()

    qs = ModelUsageLog.objects.filter(
        user=user,
        operation=ASSEMBLY_OPERATION,
        audio_seconds__gt=0,
        created_at__gte=period_start,
        created_at__lt=period_end,
    ).filter(Q(success=True) | Q(metadata__transcript_id__gt=""))

    seconds = qs.aggregate(total=Sum("audio_seconds"))["total"]
    return max(0.0, float(seconds or 0))


def assembly_seconds_for_user(user, now=None):
    """Assembly audio billed against the current monthly allowance."""
    return logged_assembly_seconds(user, *billing_period_bounds(now))


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

    if remaining <= 0:
        remaining_copy = "0 minutes left this month"
    elif remaining < 1:
        remaining_copy = "1 minute left this month"
    else:
        left = int(remaining)
        remaining_copy = (
            "1 minute left this month" if left == 1 else f"{left} minutes left this month"
        )

    remaining_label = str(int(remaining_clamped)) if remaining_clamped >= 1 else _label(remaining_clamped)

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
