from datetime import timedelta
from uuid import UUID

from django.middleware.csrf import get_token
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone

from .models import Album, Note
from .usage import usage_for_user

ROLL_NAV_VIEWS = frozenset({"list", "library", "albums"})


def app_shell(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {}

    try:
        notes = Note.objects.filter(user=user)
        now = timezone.localtime(timezone.now())
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        usage = usage_for_user(user)
        remaining_seconds = max(0, int(usage["remaining_minutes"] * 60))
        roll_url = reverse("notes:list")
        ctx = {
            "has_today": notes.filter(
                created_at__gte=start, created_at__lt=start + timedelta(days=1)
            ).exists(),
            "has_favourites": notes.filter(is_starred=True).exists(),
            "show_app_roll_nav": False,
            "show_albums_library": False,
            "album": "recents",
            "current_album": None,
            "app_config": {
                "developUrl": reverse("api-notes-develop"),
                "notesUrl": "/api/notes/",
                "albumsUrl": "/api/albums/",
                "listUrl": roll_url,
                "todayUrl": f"{roll_url}?album=today",
                "starredUrl": f"{roll_url}?album=starred",
                "albumsPageUrl": reverse("notes:albums"),
                "settingsUrl": reverse("settings"),
                "usedMinutes": usage["used_minutes"],
                "capMinutes": usage["cap_minutes"],
                "remainingSeconds": remaining_seconds,
                "takeMaxSeconds": 5 * 60,
                "isExhausted": usage["is_exhausted"],
                "remainingCopy": usage["remaining_copy"],
                "csrfToken": get_token(request),
            },
        }
        try:
            match = resolve(request.path)
        except Resolver404:
            return ctx

        if match.url_name not in ROLL_NAV_VIEWS:
            return ctx

        ctx["show_app_roll_nav"] = True
        ctx["show_albums_library"] = match.url_name == "albums"
        if match.url_name == "library":
            ctx["album"] = "library"
        elif match.url_name == "list":
            album_param = request.GET.get("album", "recents")
            ctx["album"] = album_param
            if album_param not in ("recents", "today", "starred", "library"):
                try:
                    album_id = UUID(str(album_param))
                except (TypeError, ValueError):
                    album_id = None
                if album_id is not None:
                    ctx["current_album"] = (
                        Album.objects.filter(pk=album_id, user=user).first()
                    )
        return ctx
    except Exception:
        return {}
