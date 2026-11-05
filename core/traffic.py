"""Cookieless counts for public pages.

A visitor is a daily hash of IP and user agent. The hash is not reversible and
changes the next day, so the same person on two days counts as two visitors.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Count, F, Sum
from django.utils import timezone

from .models import TrafficHit

RETENTION_DAYS = 90
TOP_LIMIT = 8

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
    referrer = _session_referrer(request, today, visitor)
    _increment(today, request.path, referrer, visitor)
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


def _external_referrer(request) -> str:
    raw = request.META.get("HTTP_REFERER", "")
    if not raw:
        return ""
    host = (urlparse(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or host in _site_hosts(request):
        return ""
    return host[:255]


def _session_referrer(request, today: date, visitor: str) -> str:
    """Keep the first external source for this visitor for the rest of the day."""
    existing = (
        TrafficHit.objects.filter(day=today, visitor_hash=visitor)
        .exclude(referrer="")
        .values_list("referrer", flat=True)
        .first()
    )
    if existing:
        return existing
    return _external_referrer(request)


def _increment(day: date, path: str, referrer: str, visitor: str) -> None:
    bucket = {
        "day": day,
        "path": path[:200],
        "referrer": referrer[:255],
        "visitor_hash": visitor,
    }
    updated = TrafficHit.objects.filter(**bucket).update(views=F("views") + 1)
    if updated:
        return
    try:
        TrafficHit.objects.create(**bucket, views=1)
    except IntegrityError:
        TrafficHit.objects.filter(**bucket).update(views=F("views") + 1)


def _window(today: date, days: int) -> dict:
    pageviews, visitors = _totals(_span(today, days))
    return {
        "label": f"{days} days",
        "visitors": visitors,
        "visitor_label": "visitor" if visitors == 1 else "visitors",
        "pageviews_label": "1 page view" if pageviews == 1 else f"{pageviews} page views",
    }


def _span(today: date, days: int):
    start = today - timedelta(days=days - 1)
    return TrafficHit.objects.filter(day__gte=start, day__lte=today)


def _totals(qs) -> tuple[int, int]:
    pageviews = qs.aggregate(total=Sum("views"))["total"] or 0
    visitors = qs.values("day", "visitor_hash").distinct().count()
    return pageviews, visitors


def _top_pages(today: date, days: int) -> list[dict]:
    rows = (
        _span(today, days)
        .values("path")
        .annotate(views=Sum("views"), visitors=Count("visitor_hash", distinct=True))
        .order_by("-views", "path")[:TOP_LIMIT]
    )
    return [
        {"path": row["path"], "views": row["views"], "visitors": row["visitors"]}
        for row in rows
    ]


def _top_sources(today: date, days: int) -> list[dict]:
    rows = (
        _span(today, days)
        .values("referrer")
        .annotate(views=Sum("views"))
        .order_by("-views", "referrer")[:TOP_LIMIT]
    )
    return [
        {"label": row["referrer"] or "Direct", "views": row["views"]}
        for row in rows
    ]
