"""Cookieless counts for public pages.

A visitor is a daily hash of IP and user agent. The hash is not reversible and
changes the next day, so the same person on two days counts as two visitors.

Source labels stored on ``TrafficHit.referrer``:

- ``""`` — Direct (no referrer, no campaign param)
- ``internal`` — same-site Referer (in-app navigation between pages)
- campaign token — ``utm_source`` / ``src`` / ``ref``, or a click-id fallback
- hostname — external Referer host (e.g. ``google.com``)
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Case, Count, F, Max, Min, Sum, Value, When
from django.utils import timezone

from .models import TrafficHit

RETENTION_DAYS = 90
TOP_LIMIT = 8

SOURCE_DIRECT = ""
SOURCE_INTERNAL = "internal"

_SOURCE_LABELS = {
    SOURCE_DIRECT: "Direct",
    SOURCE_INTERNAL: "Internal",
}

_CAMPAIGN_KEYS = ("utm_source", "src", "ref")
_CLICK_ID_SOURCES = (
    ("gclid", "google-ads"),
    ("fbclid", "facebook"),
    ("msclkid", "microsoft-ads"),
)
_SOURCE_TOKEN = re.compile(r"[^a-z0-9._+-]+")

TRACKED_PATHS = frozenset(
    {
        "/",
        "/login/",
        "/signup/",
        "/signup/success/",
        "/signup/cancel/",
        "/privacy/",
        "/terms/",
        "/support/",
    }
)

_BOT_MARKERS = (
    "bot",
    "spider",
    "crawl",
    "slurp",
    "headless",
    "lighthouse",
    "pagespeed",
    "pingdom",
    "uptime",
    "wget",
    "curl",
    "python-requests",
    "python-urllib",
    "go-http-client",
    "httpx",
    "scrapy",
    "semrush",
    "ahrefs",
    "petalbot",
    "bytespider",
    "facebookexternalhit",
    "embedly",
)


def record_page_view(request, response) -> None:
    if not _should_record(request, response):
        return

    today = timezone.localdate()
    visitor = visitor_hash(
        _client_ip(request),
        request.META.get("HTTP_USER_AGENT", ""),
        today,
    )
    source = _session_source(request, today, visitor)
    _increment(today, request.path, source, visitor)
    if cache.add(f"traffic-pruned-{today.isoformat()}", 1, 60 * 60 * 24):
        prune_traffic(today)


def visitor_hash(ip: str, user_agent: str, day: date) -> str:
    key = settings.SECRET_KEY.encode()
    message = f"{day.isoformat()}|{ip}|{user_agent[:300]}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:32]


def prune_traffic(today: date | None = None) -> None:
    today = today or timezone.localdate()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    TrafficHit.objects.filter(day__lt=cutoff).delete()


def traffic_report(today: date | None = None) -> dict:
    today = today or timezone.localdate()
    return {
        "windows": [_window(today, 7), _window(today, 30)],
        "pages": _top_pages(today, 30),
        "sources": _top_sources(today, 30),
    }


def _should_record(request, response) -> bool:
    if request.method != "GET":
        return False
    if request.path not in TRACKED_PATHS:
        return False
    if getattr(response, "status_code", None) != 200:
        return False
    content_type = response.get("Content-Type", "")
    if not content_type.startswith("text/html"):
        return False
    purpose = (
        request.META.get("HTTP_SEC_PURPOSE", "")
        or request.META.get("HTTP_PURPOSE", "")
    ).lower()
    if purpose == "prefetch":
        return False
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return False
    if _is_bot(request.META.get("HTTP_USER_AGENT", "")):
        return False
    return True


def _is_bot(user_agent: str) -> bool:
    ua = user_agent.lower()
    return any(marker in ua for marker in _BOT_MARKERS)


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.META.get("REMOTE_ADDR", "")[:64]


def _site_hosts(request) -> set[str]:
    hosts: set[str] = set()

    def add(host: str) -> None:
        host = host.split(":")[0].lower().strip(".")
        if not host:
            return
        hosts.add(host)
        if host.startswith("www."):
            hosts.add(host[4:])

    add(request.get_host())
    public = getattr(settings, "PUBLIC_BASE_URL", "")
    add(urlparse(public).hostname or "")
    return hosts


def source_label(referrer: str) -> str:
    """Human label for a stored source token."""
    return _SOURCE_LABELS.get(referrer, referrer or "Direct")


def _clean_source_token(value: str) -> str:
    cleaned = _SOURCE_TOKEN.sub("-", value.strip().lower()).strip(".-")
    return cleaned[:64]


def _campaign_source(request) -> str:
    """Attribution from share/ad links when Referer is often stripped."""
    for key in _CAMPAIGN_KEYS:
        raw = request.GET.get(key, "")
        if not raw:
            continue
        token = _clean_source_token(raw)
        if token and token != SOURCE_INTERNAL:
            return token
    for param, label in _CLICK_ID_SOURCES:
        if request.GET.get(param):
            return label
    return SOURCE_DIRECT


def _referrer_source(request) -> str:
    raw = request.META.get("HTTP_REFERER", "")
    if not raw:
        return SOURCE_DIRECT
    host = (urlparse(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return SOURCE_DIRECT
    if host in _site_hosts(request):
        return SOURCE_INTERNAL
    return host[:255]


def _resolve_source(request) -> str:
    """Campaign params beat Referer; same-site Referer is Internal, not Direct."""
    campaign = _campaign_source(request)
    if campaign:
        return campaign
    return _referrer_source(request)


def _session_source(request, today: date, visitor: str) -> str:
    """Keep the first non-Direct source for this visitor for the rest of the day.

    Direct landings can still upgrade to Internal (in-site clicks) or an
    external/campaign source later the same day.
    """
    existing = (
        TrafficHit.objects.filter(day=today, visitor_hash=visitor)
        .exclude(referrer=SOURCE_DIRECT)
        .values_list("referrer", flat=True)
        .first()
    )
    if existing:
        return existing
    return _resolve_source(request)


def _increment(day: date, path: str, referrer: str, visitor: str) -> None:
    now = timezone.now()
    path = path[:200]
    _close_previous_page(day, visitor, path, now)
    bucket = {
        "day": day,
        "path": path,
        "referrer": referrer[:255],
        "visitor_hash": visitor,
    }
    updated = _bump_hit(bucket, now)
    if updated:
        return
    try:
        TrafficHit.objects.create(
            **bucket, views=1, first_seen=now, last_seen=now
        )
    except IntegrityError:
        _bump_hit(bucket, now)


def _close_previous_page(
    day: date, visitor: str, current_path: str, now
) -> None:
    """Mark departure from the visitor's last other page (time-on-page approx)."""
    previous = (
        TrafficHit.objects.filter(day=day, visitor_hash=visitor)
        .exclude(path=current_path)
        .order_by("-last_seen", "-pk")
        .first()
    )
    if previous is None or previous.last_seen is None:
        return
    if previous.last_seen >= now:
        return
    TrafficHit.objects.filter(pk=previous.pk).update(last_seen=now)


def _bump_hit(bucket: dict, now) -> int:
    """Increment views and extend last_seen; set first_seen if missing."""
    return TrafficHit.objects.filter(**bucket).update(
        views=F("views") + 1,
        last_seen=now,
        first_seen=Case(
            When(first_seen__isnull=True, then=Value(now)),
            default=F("first_seen"),
        ),
    )


def format_stay(seconds: float | None) -> str:
    """Human label for average session span (first → last page view)."""
    if seconds is None:
        return "-"
    total = max(0, int(round(seconds)))
    if total < 1:
        return "<1s"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        if secs:
            return f"{minutes}m {secs}s"
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h"


def _window(today: date, days: int) -> dict:
    qs = _span(today, days)
    pageviews, visitors = _totals(qs)
    avg_stay = _avg_stay_seconds(qs)
    return {
        "label": f"{days} days",
        "visitors": visitors,
        "visitor_label": "visitor" if visitors == 1 else "visitors",
        "pageviews_label": "1 page view" if pageviews == 1 else f"{pageviews} page views",
        "avg_stay_seconds": avg_stay,
        "avg_stay_label": format_stay(avg_stay),
    }


def _avg_stay_seconds(qs) -> float | None:
    """Mean site stay: first → last page view that day per visitor."""
    return _mean_stay(_stay_spans(qs, "day", "visitor_hash"))


def _avg_stay_by(qs, *group_fields: str) -> dict:
    """Mean stay keyed by group field values (e.g. path or referrer)."""
    spans = _stay_spans(qs, *group_fields, "day", "visitor_hash")
    buckets: dict[tuple, list[float]] = {}
    for row in spans:
        key = tuple(row[field] for field in group_fields)
        buckets.setdefault(key, []).append(row["seconds"])
    return {
        key: sum(values) / len(values)
        for key, values in buckets.items()
        if values
    }


def _stay_spans(qs, *group_fields: str) -> list[dict]:
    sessions = (
        qs.filter(first_seen__isnull=False, last_seen__isnull=False)
        .values(*group_fields)
        .annotate(start=Min("first_seen"), end=Max("last_seen"))
    )
    rows: list[dict] = []
    for row in sessions:
        if row["start"] is None or row["end"] is None:
            continue
        entry = {field: row[field] for field in group_fields}
        entry["seconds"] = max(0.0, (row["end"] - row["start"]).total_seconds())
        rows.append(entry)
    return rows


def _mean_stay(spans: list[dict]) -> float | None:
    if not spans:
        return None
    return sum(row["seconds"] for row in spans) / len(spans)


def _span(today: date, days: int):
    start = today - timedelta(days=days - 1)
    return TrafficHit.objects.filter(day__gte=start, day__lte=today)


def _totals(qs) -> tuple[int, int]:
    pageviews = qs.aggregate(total=Sum("views"))["total"] or 0
    visitors = qs.values("day", "visitor_hash").distinct().count()
    return pageviews, visitors


def _top_pages(today: date, days: int) -> list[dict]:
    qs = _span(today, days)
    stays = _avg_stay_by(qs, "path")
    rows = (
        qs.values("path")
        .annotate(views=Sum("views"), visitors=Count("visitor_hash", distinct=True))
        .order_by("-views", "path")[:TOP_LIMIT]
    )
    return [
        {
            "path": row["path"],
            "views": row["views"],
            "visitors": row["visitors"],
            "avg_stay_label": format_stay(stays.get((row["path"],))),
        }
        for row in rows
    ]


def _top_sources(today: date, days: int) -> list[dict]:
    qs = _span(today, days)
    stays = _avg_stay_by(qs, "referrer")
    rows = (
        qs.values("referrer")
        .annotate(views=Sum("views"))
        .order_by("-views", "referrer")[:TOP_LIMIT]
    )
    return [
        {
            "label": source_label(row["referrer"]),
            "views": row["views"],
            "avg_stay_label": format_stay(stays.get((row["referrer"],))),
        }
        for row in rows
    ]
