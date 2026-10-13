import inspect
import json
from datetime import datetime, time, timedelta
from uuid import UUID

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from notes.models import Album, Note
from notes.search import text_search_q

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
PREVIEW_CHARS = 240
STARRED_ALBUM_NAMES = {"starred", "favourites", "favorites"}


class ToolError(Exception):
    pass


def search_takes(
    user,
    query="",
    album="",
    starred=None,
    since="",
    until="",
    updated_since="",
    limit=DEFAULT_LIMIT,
):
    """Search takes by words, album, starred, and date range."""
    notes = _base_notes(user)
    query = (query or "").strip()
    if query:
        notes = notes.filter(text_search_q(query))
    notes = _apply_album(notes, user, album)
    notes = _apply_starred(notes, starred)
    notes = _apply_created_range(notes, since, until)
    notes = _apply_updated_since(notes, updated_since)
    rows = list(notes[:_clamp_limit(limit)])
    return {
        "count": len(rows),
        "takes": [_summarize(note) for note in rows],
    }


def list_recent_takes(user, since="", until="", updated_since="", limit=DEFAULT_LIMIT):
    """List recent takes, newest first, with an optional date filter."""
    notes = _apply_created_range(_base_notes(user), since, until)
    notes = _apply_updated_since(notes, updated_since)
    rows = list(notes[:_clamp_limit(limit)])
    return {
        "count": len(rows),
        "takes": [_summarize(note) for note in rows],
    }


def get_take(user, take_id):
    """Get one take with its full text, date, length, album and star."""
    note = _get_note(user, take_id)
    data = _summarize(note)
    data["text"] = note.display_text
    data.pop("preview", None)
    return data


def list_albums(user):
    """List albums with take counts."""
    albums = list(Album.objects.filter(user=user).prefetch_related("notes"))
    return {
        "starred_count": Note.objects.filter(user=user, is_starred=True).count(),
        "albums": [
            {
                "id": str(album.id),
                "name": album.name,
                "take_count": album.take_count,
                "updated_at": _iso(album.last_updated),
            }
            for album in albums
        ],
    }


def update_take(user, take_id, album="", starred=None):
    """Move a take to an album and/or star or unstar it."""
    note = _get_note(user, take_id)
    changed = []
    album_changed = False
    album_name = (album or "").strip()
    if album_name:
        target = _resolve_album(user, album_name)
        if not target.notes.filter(pk=note.pk).exists():
            target.notes.add(note)
            album_changed = True
            changed.append(f"added to album {target.name!r}")
        else:
            changed.append(f"already in album {target.name!r}")
    saved_star = False
    if starred is not None:
        flag = _as_bool(starred, "starred")
        if note.is_starred != flag:
            note.is_starred = flag
            note.save(update_fields=["is_starred", "updated_at"])
            saved_star = True
            changed.append("starred" if flag else "unstarred")
        else:
            changed.append("already starred" if flag else "already unstarred")
    if album_changed and not saved_star:
        note.touch()
    if not changed:
        raise ToolError("Pass album (id or name) and/or starred true/false.")
    note.refresh_from_db()
    result = _summarize(note)
    result["changed"] = changed
    return result


def create_album(user, name):
    """Create an album."""
    title = (name or "").strip()
    if not title:
        raise ToolError("Album name is required.")
    album = Album.create_for_user(user, title)
    return {
        "id": str(album.id),
        "name": album.name,
        "take_count": 0,
        "updated_at": _iso(album.created_at),
    }


def call_tool(user, name, arguments):
    args = arguments or {}
    if not isinstance(args, dict):
        raise ToolError("Tool arguments must be an object.")
    handlers = {
        "search_takes": search_takes,
        "list_recent_takes": list_recent_takes,
        "get_take": get_take,
        "list_albums": list_albums,
        "update_take": update_take,
        "create_album": create_album,
    }
    handler = handlers.get(name)
    if handler is None:
        raise ToolError(f"Unknown tool {name!r}. Use tools/list to see the Ramble tools.")
    return handler(user, **_kwargs_for(handler, args))


def tool_definitions():
    return [
        {
            "name": "search_takes",
            "description": (
                "Search the user's takes by words, album, starred, and date range. "
                "Use this for questions like 'what did I say about pricing last week?'. "
                "Returns compact previews — call get_take for full text. "
                "Pass updated_since to pick up only takes that changed after a timestamp."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Words to match in the take text.",
                    },
                    "album": {
                        "type": "string",
                        "description": "Album id or name. Use starred/favourites for favourites.",
                    },
                    "starred": {
                        "type": "boolean",
                        "description": "If true, only starred takes. If false, only unstarred.",
                    },
                    "since": {
                        "type": "string",
                        "description": "Earliest created date, YYYY-MM-DD or ISO timestamp.",
                    },
                    "until": {
                        "type": "string",
                        "description": "Latest created date, YYYY-MM-DD or ISO timestamp.",
                    },
                    "updated_since": {
                        "type": "string",
                        "description": "Only takes whose updated timestamp is on or after this.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max takes to return (default 20, max 50).",
                    },
                },
            },
            "annotations": {"readOnlyHint": True, "idempotentHint": True},
        },
        {
            "name": "list_recent_takes",
            "description": (
                "List recent takes, newest first. Optional since/until created-date filter. "
                "This is what a daily or weekly digest should call. "
                "Pass updated_since to sync only what is new. "
                "Returns previews — call get_take for full text."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "since": {
                        "type": "string",
                        "description": "Earliest created date, YYYY-MM-DD or ISO timestamp.",
                    },
                    "until": {
                        "type": "string",
                        "description": "Latest created date, YYYY-MM-DD or ISO timestamp.",
                    },
                    "updated_since": {
                        "type": "string",
                        "description": "Only takes whose updated timestamp is on or after this.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max takes to return (default 20, max 50).",
                    },
                },
            },
            "annotations": {"readOnlyHint": True, "idempotentHint": True},
        },
        {
            "name": "get_take",
            "description": (
                "Get one take by id, with full text, created and updated timestamps, "
                "length, albums, and whether it is starred."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "take_id": {
                        "type": "string",
                        "description": "The take's stable id from search or list_recent_takes.",
                    }
                },
                "required": ["take_id"],
            },
            "annotations": {"readOnlyHint": True, "idempotentHint": True},
        },
        {
            "name": "list_albums",
            "description": "List the user's albums with take counts, plus how many takes are starred.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True, "idempotentHint": True},
        },
        {
            "name": "update_take",
            "description": (
                "File a take without using the web app: add it to an album and/or star or unstar it. "
                "Takes can belong to more than one album; this adds membership, it does not remove others. "
                "Pass album (id or name) and/or starred true/false. You can do both in one call."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "take_id": {
                        "type": "string",
                        "description": "The take's stable id.",
                    },
                    "album": {
                        "type": "string",
                        "description": "Album id or name to add the take to.",
                    },
                    "starred": {
                        "type": "boolean",
                        "description": "True to star, false to unstar.",
                    },
                },
                "required": ["take_id"],
            },
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": True,
                "destructiveHint": False,
            },
        },
        {
            "name": "create_album",
            "description": "Create a new album. Returns its id so you can move takes into it.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Album name."}
                },
                "required": ["name"],
            },
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": False,
                "destructiveHint": False,
            },
        },
    ]


def _kwargs_for(handler, args):
    accepted = {
        name
        for name in inspect.signature(handler).parameters
        if name != "user"
    }
    kwargs = {}
    for key, value in args.items():
        if key in accepted:
            kwargs[key] = value
    if "take_id" in accepted and "take_id" not in kwargs and args.get("id"):
        kwargs["take_id"] = args["id"]
    return kwargs


def _base_notes(user):
    return Note.objects.filter(user=user).prefetch_related("albums")


def _get_note(user, take_id):
    if not take_id:
        raise ToolError("take_id is required.")
    try:
        pk = UUID(str(take_id).strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ToolError("take_id must be a UUID.") from exc
    note = _base_notes(user).filter(id=pk).first()
    if note is None:
        raise ToolError(f"No take with id {take_id}.")
    return note


def _apply_album(notes, user, album):
    name = (album or "").strip()
    if not name:
        return notes
    if name.lower() in STARRED_ALBUM_NAMES:
        return notes.filter(is_starred=True)
    try:
        pk = UUID(name)
    except ValueError:
        matches = list(Album.objects.filter(user=user, name__iexact=name))
        if not matches:
            raise ToolError(f"No album named {name!r}. Use list_albums to see names.")
        return notes.filter(albums__in=matches).distinct()
    found = Album.objects.filter(user=user, id=pk).first()
    if found is None:
        raise ToolError(f"No album with id {name}.")
    return notes.filter(albums=found).distinct()


def _resolve_album(user, album):
    name = album.strip()
    if name.lower() in STARRED_ALBUM_NAMES:
        raise ToolError("Favourites is not an album. Pass starred true to star a take.")
    try:
        pk = UUID(name)
    except ValueError:
        matches = list(Album.objects.filter(user=user, name__iexact=name))
        if not matches:
            raise ToolError(f"No album named {name!r}. Use list_albums, or create_album first.")
        if len(matches) > 1:
            raise ToolError(
                f"Several albums named {name!r}. Pass an album id from list_albums instead."
            )
        return matches[0]
    found = Album.objects.filter(user=user, id=pk).first()
    if found is None:
        raise ToolError(f"No album with id {name}.")
    return found


def _apply_starred(notes, starred):
    if starred is None or starred == "":
        return notes
    return notes.filter(is_starred=_as_bool(starred, "starred"))


def _apply_created_range(notes, since, until):
    start = _parse_datetime(since, "since")
    if start is not None:
        notes = notes.filter(created_at__gte=start)
    finish = _parse_until(until)
    if finish is not None:
        moment, exclusive = finish
        if exclusive:
            notes = notes.filter(created_at__lt=moment)
        else:
            notes = notes.filter(created_at__lte=moment)
    return notes


def _apply_updated_since(notes, updated_since):
    start = _parse_datetime(updated_since, "updated_since")
    if start is None:
        return notes
    return notes.filter(updated_at__gte=start)


def _parse_datetime(value, field):
    text = (value or "").strip()
    if not text:
        return None
    dt = parse_datetime(text)
    if dt is not None:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    day = parse_date(text)
    if day is None:
        raise ToolError(
            f"{field} must be YYYY-MM-DD or an ISO timestamp, not {text!r}."
        )
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(day, time.min), tz)


def _parse_until(value):
    text = (value or "").strip()
    if not text:
        return None
    dt = parse_datetime(text)
    if dt is not None:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt, False
    day = parse_date(text)
    if day is None:
        raise ToolError(
            f"until must be YYYY-MM-DD or an ISO timestamp, not {text!r}."
        )
    tz = timezone.get_current_timezone()
    nxt = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
    return nxt, True


def _as_bool(value, field):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ToolError(f"{field} must be true or false.")


def _clamp_limit(value):
    if value is None or value == "":
        return DEFAULT_LIMIT
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError("limit must be a number.") from exc
    return max(1, min(number, MAX_LIMIT))


def _summarize(note):
    if note.is_processing:
        status = "developing"
    elif note.transcription_failed:
        status = "failed"
    else:
        status = "ready"
    preview = note.list_preview_text.replace("\n", " ").strip()
    if len(preview) > PREVIEW_CHARS:
        preview = preview[: PREVIEW_CHARS - 1].rstrip() + "…"
    return {
        "id": str(note.id),
        "created_at": _iso(note.created_at),
        "updated_at": _iso(note.updated_at),
        "duration_seconds": round(float(note.duration or 0), 1),
        "starred": note.is_starred,
        "albums": [
            {"id": str(album.id), "name": album.name}
            for album in note.membership_albums
        ],
        "status": status,
        "preview": preview,
    }


def _iso(value):
    if value is None:
        return None
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    return local.isoformat()


def as_tool_result(data, is_error=False):
    if is_error:
        text = data if isinstance(data, str) else json.dumps(data, default=str)
        payload = {"error": text} if isinstance(data, str) else data
    else:
        payload = data
        text = json.dumps(data, indent=2, default=str)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": is_error,
    }
