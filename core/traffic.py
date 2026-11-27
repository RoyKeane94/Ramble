"""Cookieless counts for public pages (Plausible / Fathom style).

Browsers send a tiny JS beacon; scrapers that never run JS are ignored.
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
import json
import logging
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Case, Count, F, Max, Min, Sum, Value, When
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import TrafficHit

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
TOP_LIMIT = 8
LIVE_WINDOW = timedelta(minutes=5)

PERIOD_CHOICES = (
    ("1", 1, "1 day"),
    ("7", 7, "7 days"),
    ("30", 30, "30 days"),
    ("all", None, "All time"),
)
PERIOD_KEYS = frozenset(key for key, _days, _label in PERIOD_CHOICES)
DEFAULT_PERIOD = "30"

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
        "/blog/",
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
    "preview",
    "prerender",
    "discordbot",
    "twitterbot",
    "linkedinbot",
    "slackbot",
    "whatsapp",
    "telegrambot",
    "applebot",
    "bingbot",
    "yandex",
    "duckduck",
    "baidu",
    "gptbot",
    "claudebot",
    "anthropic",
    "perplexity",
    "amazonbot",
    "phantomjs",
    "selenium",
    "webdriver",
    "puppeteer",
    "playwright",
    "httpclient",
    "libwww",
    "okhttp",
    "postman",
    "insomnia",
    "statuscake",
    "newrelic",
    "datadog",
    "monitor",
    "httrack",
    "mechanize",
)


@csrf_exempt
@require_POST
def traffic_beacon(request: HttpRequest) -> HttpResponse:
    """Record one page view from the public JS beacon. Always 204."""
    try:
        record_beacon(request)
    except Exception:
        logger.exception("Failed to record traffic beacon")
    return HttpResponse(status=204)


@require_GET
def traffic_live(request: HttpRequest) -> JsonResponse:
    """Superuser JSON snapshot of people active in the last few minutes."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_superuser:
        raise PermissionDenied
    return JsonResponse(live_snapshot())


def record_beacon(request: HttpRequest) -> bool:
    """Parse a browser beacon and count it when it looks like a real visit."""
    if not _visitor_allowed(request):
        return False

    payload = _beacon_payload(request)
    path = _normalize_path(payload.get("path") or "")
    if path not in TRACKED_PATHS:
        return False

    today = timezone.localdate()
    visitor = visitor_hash(
        _client_ip(request),
        request.META.get("HTTP_USER_AGENT", ""),
        today,
    )
    kind = (payload.get("kind") or "pageview").strip().lower()
    if kind == "heartbeat":
        return _touch_heartbeat(today, path, visitor)

    query = _query_from_payload(payload)
    page_referrer = (payload.get("referrer") or "").strip()[:2000]
    source = _session_source(
        request,
        today,
        visitor,
        query=query,
        page_referrer=page_referrer,
    )
    _increment(today, path, source, visitor)
    if cache.add(f"traffic-pruned-{today.isoformat()}", 1, 60 * 60 * 24):
        prune_traffic(today)
    return True


def live_snapshot(now=None) -> dict:
    """People with a pageview/heartbeat inside the live window."""
    now = now or timezone.now()
    cutoff = now - LIVE_WINDOW
    recent = list(
        TrafficHit.objects.filter(last_seen__gte=cutoff)
        .order_by("-last_seen", "-pk")
        .values("visitor_hash", "path", "referrer", "last_seen")
    )
    seen: set[str] = set()
    viewers: list[dict] = []
    for row in recent:
        visitor = row["visitor_hash"]
        if visitor in seen:
            continue
        seen.add(visitor)
        last_seen = row["last_seen"]
        age = max(0, int((now - last_seen).total_seconds())) if last_seen else 0
        viewers.append(
            {
                "path": row["path"],
                "source": source_label(row["referrer"]),
                "seconds_ago": age,
                "ago_label": format_ago(age),
            }
        )
    count = len(viewers)
    return {
        "count": count,
        "label": "person viewing" if count == 1 else "people viewing",
        "window_minutes": int(LIVE_WINDOW.total_seconds() // 60),
        "viewers": viewers,
    }


def visitor_hash(ip: str, user_agent: str, day: date) -> str:
    key = settings.SECRET_KEY.encode()
    message = f"{day.isoformat()}|{ip}|{user_agent[:300]}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:32]


def prune_traffic(today: date | None = None) -> None:
    today = today or timezone.localdate()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    TrafficHit.objects.filter(day__lt=cutoff).delete()


def normalize_period(raw: str | None) -> str:
    key = (raw or DEFAULT_PERIOD).strip().lower()
    return key if key in PERIOD_KEYS else DEFAULT_PERIOD


def period_days(period: str) -> int | None:
    for key, days, _label in PERIOD_CHOICES:
        if key == period:
            return days
    return period_days(DEFAULT_PERIOD)


def traffic_report(
    today: date | None = None,
    *,
    period: str | None = None,
) -> dict:
    today = today or timezone.localdate()
    selected = normalize_period(period)
    days = period_days(selected)
    label = next(
        label for key, _days, label in PERIOD_CHOICES if key == selected
    )
    return {
        "period": selected,
        "period_label": label,
        "periods": [
            {
                "key": key,
                "label": choice_label,
                "selected": key == selected,
            }
            for key, _days, choice_label in PERIOD_CHOICES
        ],
        "summary": _window(today, days, label=label),
        "live": live_snapshot(),
        "windows": [_window(today, 7), _window(today, 30)],
        "pages": _top_pages(today, days),
        "sources": _top_sources(today, days),
        "series": _daily_series(today, days),
    }


def _visitor_allowed(request: HttpRequest) -> bool:
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return False
    purpose = (
        request.META.get("HTTP_SEC_PURPOSE", "")
        or request.META.get("HTTP_PURPOSE", "")
    ).lower()
    if purpose == "prefetch":
        return False
    ua = request.META.get("HTTP_USER_AGENT", "")
    if not ua.strip():
        return False
    if _is_bot(ua):
        return False
    return True


def _is_bot(user_agent: str) -> bool:
    ua = user_agent.lower()
    return any(marker in ua for marker in _BOT_MARKERS)


def _beacon_payload(request: HttpRequest) -> dict:
    content_type = (request.META.get("CONTENT_TYPE") or "").lower()
    if "application/json" in content_type:
        try:
            raw = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}
    return {
        "path": request.POST.get("path", ""),
        "referrer": request.POST.get("referrer", ""),
        "search": request.POST.get("search", ""),
        "kind": request.POST.get("kind", "pageview"),
    }


def _normalize_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        return ""
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc:
        path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if len(path) > 1 and path.endswith("/"):
        # keep trailing slash to match TRACKED_PATHS / Django APPEND_SLASH
        pass
    elif path != "/" and not path.endswith("/"):
        # allow either; prefer Django-style trailing slash for known pages
        slashed = f"{path}/"
        if slashed in TRACKED_PATHS:
            return slashed[:200]
    return path[:200]


def _query_from_payload(payload: dict) -> QueryDict:
    search = (payload.get("search") or "").strip()
    if search.startswith("?"):
        search = search[1:]
    if not search and payload.get("url"):
        search = urlparse(str(payload["url"])).query
    return QueryDict(search, mutable=False)


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


def _campaign_source(query: QueryDict) -> str:
    """Attribution from share/ad links when Referer is often stripped."""
    for key in _CAMPAIGN_KEYS:
        raw = query.get(key, "")
        if not raw:
            continue
        token = _clean_source_token(raw)
        if token and token != SOURCE_INTERNAL:
            return token
    for param, label in _CLICK_ID_SOURCES:
        if query.get(param):
            return label
    return SOURCE_DIRECT


def _referrer_source(page_referrer: str, site_hosts: set[str]) -> str:
    raw = (page_referrer or "").strip()
    if not raw:
        return SOURCE_DIRECT
    host = (urlparse(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return SOURCE_DIRECT
    if host in site_hosts:
        return SOURCE_INTERNAL
    return host[:255]


def _resolve_source(request, query: QueryDict, page_referrer: str) -> str:
    """Campaign params beat Referer; same-site Referer is Internal, not Direct."""
    campaign = _campaign_source(query)
    if campaign:
        return campaign
    return _referrer_source(page_referrer, _site_hosts(request))


def _session_source(
    request,
    today: date,
    visitor: str,
    *,
    query: QueryDict,
    page_referrer: str,
) -> str:
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
    return _resolve_source(request, query, page_referrer)


def _touch_heartbeat(day: date, path: str, visitor: str) -> bool:
    """Refresh last_seen for an existing visit without adding pageviews."""
    now = timezone.now()
    updated = (
        TrafficHit.objects.filter(day=day, path=path, visitor_hash=visitor)
        .order_by("-last_seen", "-pk")
        .values_list("pk", flat=True)[:1]
    )
    pk = next(iter(updated), None)
    if pk is None:
        return False
    TrafficHit.objects.filter(pk=pk).update(last_seen=now)
    return True


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


def format_ago(seconds: int | float) -> str:
    """Short relative time for live viewers (e.g. ``just now``, ``45s ago``)."""
    total = max(0, int(round(seconds)))
    if total < 5:
        return "just now"
    if total < 60:
        return f"{total}s ago"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago"


def _window(today: date, days: int | None, *, label: str | None = None) -> dict:
    qs = _span(today, days)
    pageviews, visitors = _totals(qs)
    avg_stay = _avg_stay_seconds(qs)
    if label is None:
        if days is None:
            label = "All time"
        elif days == 1:
            label = "1 day"
        else:
            label = f"{days} days"
    return {
        "label": label,
        "visitors": visitors,
        "visitor_label": "visitor" if visitors == 1 else "visitors",
        "pageviews": pageviews,
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


def _span(today: date, days: int | None):
    qs = TrafficHit.objects.filter(day__lte=today)
    if days is None:
        return qs
    start = today - timedelta(days=days - 1)
    return qs.filter(day__gte=start)


def _totals(qs) -> tuple[int, int]:
    pageviews = qs.aggregate(total=Sum("views"))["total"] or 0
    visitors = qs.values("day", "visitor_hash").distinct().count()
    return pageviews, visitors


def _day_label(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def _daily_series(today: date, days: int | None) -> list[dict]:
    qs = _span(today, days)
    if days is None:
        earliest = qs.order_by("day").values_list("day", flat=True).first()
        if earliest is None:
            return []
        start = earliest
    else:
        start = today - timedelta(days=days - 1)

    by_day = {
        row["day"]: row
        for row in qs.values("day").annotate(
            views=Sum("views"),
            visitors=Count("visitor_hash", distinct=True),
        )
    }
    series: list[dict] = []
    cursor = start
    while cursor <= today:
        row = by_day.get(cursor)
        series.append(
            {
                "day": cursor.isoformat(),
                "label": _day_label(cursor),
                "views": int(row["views"]) if row else 0,
                "visitors": int(row["visitors"]) if row else 0,
            }
        )
        cursor += timedelta(days=1)
    return series


def _top_pages(today: date, days: int | None) -> list[dict]:
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


def _top_sources(today: date, days: int | None) -> list[dict]:
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
