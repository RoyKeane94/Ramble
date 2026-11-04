"""Per-user habit KPIs for the superuser dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Min, Prefetch
from django.utils import timezone

from notes.models import Note

User = get_user_model()


@dataclass
class UserKpi:
    email: str
    date_joined: datetime
    take_count: int
    first_take_at: Optional[datetime]
    second_take_at: Optional[datetime]
    last_take_at: Optional[datetime]
    signup_to_first: Optional[timedelta]
    first_to_second: Optional[timedelta]
    active_days: int
    current_streak: int
    takes_per_week: Optional[float]
    days_since_last: Optional[int]


EMPTY = "-"


def format_duration(delta: Optional[timedelta]) -> str:
    if delta is None:
        return EMPTY
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        if hours:
            return f"{days}d {hours}h"
        return f"{days}d"
    if hours:
        if minutes:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def _current_streak(take_dates: list[date], today: date) -> int:
    if not take_dates:
        return 0
    unique = sorted(set(take_dates), reverse=True)
    # Streak must include today or yesterday (still "active").
    if unique[0] < today - timedelta(days=1):
        return 0
    streak = 0
    expected = unique[0]
    for d in unique:
        if d == expected:
            streak += 1
            expected = expected - timedelta(days=1)
        elif d < expected:
            break
    return streak


def _takes_per_week(
    take_count: int,
    first_take_at: Optional[datetime],
    now: datetime,
) -> Optional[float]:
    if take_count <= 0 or first_take_at is None:
        return None
    elapsed = max((now - first_take_at).total_seconds(), 0)
    weeks = max(elapsed / (7 * 86400), 1 / 7)  # floor at ~1 day so early users aren't huge
    return round(take_count / weeks, 1)


def user_kpis() -> list[UserKpi]:
    now = timezone.now()
    today = timezone.localdate()

    users = (
        User.objects.annotate(
            take_count=Count("notes"),
            first_take_at=Min("notes__created_at"),
            last_take_at=Max("notes__created_at"),
        )
        .prefetch_related(
            Prefetch(
                "notes",
                queryset=Note.objects.order_by("created_at").only(
                    "id", "user_id", "created_at"
                ),
                to_attr="takes_asc",
            )
        )
        .order_by("-date_joined")
    )

    rows: list[UserKpi] = []
    for user in users:
        takes = getattr(user, "takes_asc", [])
        first = takes[0] if takes else None
        second = takes[1] if len(takes) > 1 else None
        first_at = first.created_at if first else None
        second_at = second.created_at if second else None
        last_at = user.last_take_at

        take_dates = [timezone.localtime(n.created_at).date() for n in takes]
        active_days = len(set(take_dates))
        days_since_last = (today - take_dates[-1]).days if take_dates else None

        rows.append(
            UserKpi(
                email=user.email,
                date_joined=user.date_joined,
                take_count=user.take_count,
                first_take_at=first_at,
                second_take_at=second_at,
                last_take_at=last_at,
                signup_to_first=(first_at - user.date_joined) if first_at else None,
                first_to_second=(second_at - first_at) if first_at and second_at else None,
                active_days=active_days,
                current_streak=_current_streak(take_dates, today),
                takes_per_week=_takes_per_week(user.take_count, first_at, now),
                days_since_last=days_since_last,
            )
        )
    return rows
