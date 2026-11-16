import inspect
import json
from datetime import datetime, time, timedelta
from urllib.parse import urlparse
from uuid import UUID

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.forms import CrmContactForm
from accounts.models import CrmContact
from notes.models import Album, Note
from notes.search import text_search_q

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
PREVIEW_CHARS = 240
STARRED_ALBUM_NAMES = {"starred", "favourites", "favorites"}
CRM_FIELDS = (
    "first_name",
    "business_name",
    "contact_type",
    "region",
    "country",
    "website",
    "email",
    "email_source",
    "personalisation_detail",
    "response",
    "response_reason",
    "tracking_slug",
)
CRM_TOOL_NAMES = frozenset(
    {
        "list_crm_contacts",
        "get_crm_contact",
        "create_crm_contact",
        "update_crm_contact",
        "delete_crm_contact",
    }
)
WEBHOOK_TOOL_NAMES = frozenset(
    {
        "save_take_ready_webhook",
        "clear_take_ready_webhook",
        "get_take_ready_webhook_status",
    }
)


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


def webhook_allowed(surface="claude"):
    """Take-ready webhook tools live on the Grok Bot MCP surface only."""
    return surface == "grok"


def crm_allowed(user, auth_method="oauth", surface="claude"):
    """CRM is superuser-only on the Grok Bot MCP token path, not Claude."""
    return bool(
        user
        and user.is_superuser
        and auth_method == "mcp_token"
        and surface == "grok"
    )


def list_crm_contacts(user, query="", limit=DEFAULT_LIMIT):
    """List outreach CRM contacts, optionally filtered by a search string."""
    del user  # access checked by call_tool
    from django.db.models import Q

    contacts = CrmContact.objects.all()
    q = (query or "").strip()
    if q:
        contacts = contacts.filter(
            Q(first_name__icontains=q)
            | Q(business_name__icontains=q)
            | Q(contact_type__icontains=q)
            | Q(region__icontains=q)
            | Q(country__icontains=q)
            | Q(website__icontains=q)
            | Q(email__icontains=q)
            | Q(email_source__icontains=q)
            | Q(personalisation_detail__icontains=q)
            | Q(response__icontains=q)
            | Q(response_reason__icontains=q)
            | Q(tracking_slug__icontains=q)
        )
    capped = _clamp_limit(limit)
    rows = list(contacts[:capped])
    return {
        "contacts": [_serialize_crm_contact(row) for row in rows],
        "count": len(rows),
        "total": contacts.count(),
    }


def get_crm_contact(user, contact_id=None, tracking_slug=""):
    """Get one CRM contact by id or tracking_slug."""
    del user
    return _serialize_crm_contact(_get_crm_contact(contact_id, tracking_slug))


def create_crm_contact(
    user,
    first_name="",
    business_name="",
    contact_type="",
    region="",
    country="",
    website="",
    email="",
    email_source="",
    personalisation_detail="",
    response="",
    response_reason="",
    tracking_slug="",
):
    """Create a CRM outreach contact (same fields as /crm/)."""
    del user
    form = CrmContactForm(
        {
            "first_name": first_name or "",
            "business_name": business_name or "",
            "contact_type": contact_type or "",
            "region": region or "",
            "country": country or "",
            "website": website or "",
            "email": email or "",
            "email_source": email_source or "",
            "personalisation_detail": personalisation_detail or "",
            "response": response or "",
            "response_reason": response_reason or "",
            "tracking_slug": tracking_slug or "",
        }
    )
    if not form.is_valid():
        raise ToolError(_crm_form_error(form))
    return _serialize_crm_contact(form.save())


def update_crm_contact(
    user,
    contact_id=None,
    tracking_slug="",
    first_name=None,
    business_name=None,
    contact_type=None,
    region=None,
    country=None,
    website=None,
    email=None,
    email_source=None,
    personalisation_detail=None,
    response=None,
    response_reason=None,
    new_tracking_slug=None,
):
    """Update fields on an existing CRM contact. Omit a field to leave it unchanged."""
    del user
    contact = _get_crm_contact(contact_id, tracking_slug)
    data = {field: getattr(contact, field) for field in CRM_FIELDS}
    updates = {
        "first_name": first_name,
        "business_name": business_name,
        "contact_type": contact_type,
        "region": region,
        "country": country,
        "website": website,
        "email": email,
        "email_source": email_source,
        "personalisation_detail": personalisation_detail,
        "response": response,
        "response_reason": response_reason,
        "tracking_slug": new_tracking_slug,
    }
    for key, value in updates.items():
        if value is not None:
            data[key] = value
    form = CrmContactForm(data, instance=contact)
    if not form.is_valid():
        raise ToolError(_crm_form_error(form))
    return _serialize_crm_contact(form.save())


def delete_crm_contact(user, contact_id=None, tracking_slug=""):
    """Delete a CRM contact by id or tracking_slug."""
    del user
    contact = _get_crm_contact(contact_id, tracking_slug)
    payload = _serialize_crm_contact(contact)
    contact.delete()
    return {"deleted": True, "contact": payload}


def save_take_ready_webhook(user, url, key):
    """Store this account's Grok Bot webhook so Ramble can ping on new takes."""
    cleaned_url = (url or "").strip()
    cleaned_key = (key or "").strip()
    if not cleaned_url or not cleaned_key:
        raise ToolError("Both url and key are required.")
    parsed = urlparse(cleaned_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ToolError("url must be an https webhook URL.")
    if len(cleaned_url) > 500:
        raise ToolError("url is too long.")
    if len(cleaned_key) > 200:
        raise ToolError("key is too long.")
    user.save_take_ready_webhook(cleaned_url, cleaned_key)
    return {
        "configured": True,
        "saved_at": _iso(user.take_ready_webhook_saved_at),
        "hint": (
            "Ramble will POST {event: take.ready, take_id} once when a take first becomes ready. "
            "On that ping, call get_take with take_id (or list_recent_takes) over MCP."
        ),
    }


def clear_take_ready_webhook(user):
    """Remove the stored take-ready webhook for this account."""
    user.clear_take_ready_webhook()
    return {"configured": False}


def get_take_ready_webhook_status(user):
    """Whether a take-ready webhook is configured (does not return the key)."""
    return {
        "configured": user.has_take_ready_webhook,
        "saved_at": _iso(user.take_ready_webhook_saved_at)
        if user.take_ready_webhook_saved_at
        else None,
        "url_host": urlparse(user.take_ready_webhook_url).netloc
        if user.has_take_ready_webhook
        else None,
    }


def call_tool(user, name, arguments, auth_method="oauth", surface="claude"):
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
        "save_take_ready_webhook": save_take_ready_webhook,
        "clear_take_ready_webhook": clear_take_ready_webhook,
        "get_take_ready_webhook_status": get_take_ready_webhook_status,
        "list_crm_contacts": list_crm_contacts,
        "get_crm_contact": get_crm_contact,
        "create_crm_contact": create_crm_contact,
        "update_crm_contact": update_crm_contact,
        "delete_crm_contact": delete_crm_contact,
    }
    handler = handlers.get(name)
    if handler is None:
        raise ToolError(f"Unknown tool {name!r}. Use tools/list to see the Ramble tools.")
    if name in WEBHOOK_TOOL_NAMES and not webhook_allowed(surface):
        raise ToolError(
            "Webhook tools are only available on the Grok Bot MCP URL (/mcp/grok)."
        )
    if name in CRM_TOOL_NAMES and not crm_allowed(
        user, auth_method=auth_method, surface=surface
    ):
        raise ToolError(
            "CRM tools are only available to superusers via the Grok Bot MCP token at /mcp/grok."
        )
    return handler(user, **_kwargs_for(handler, args))


def tool_definitions(user=None, auth_method="oauth", surface="claude"):
    tools = [
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
    if webhook_allowed(surface):
        tools.extend(_webhook_tool_definitions())
    if crm_allowed(user, auth_method=auth_method, surface=surface):
        tools.extend(_crm_tool_definitions())
    return tools


def _webhook_tool_definitions():
    return [
        {
            "name": "save_take_ready_webhook",
            "description": (
                "Register this account's Grok Bot routine webhook so Ramble can send one wake-up "
                "signal when a new take becomes ready. Create a webhook-triggered routine first, "
                "then pass its POST url and Bearer key. Ramble never sends transcript text — only "
                "{event: take.ready, take_id}; pull the take with get_take over MCP."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "HTTPS POST URL from the routine's Webhook section.",
                    },
                    "key": {
                        "type": "string",
                        "description": "Bearer key from the routine's Webhook section (not the full header).",
                    },
                },
                "required": ["url", "key"],
            },
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": True,
                "destructiveHint": False,
            },
        },
        {
            "name": "clear_take_ready_webhook",
            "description": "Remove the stored take-ready webhook so Ramble stops pinging on new takes.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": True,
                "destructiveHint": True,
            },
        },
        {
            "name": "get_take_ready_webhook_status",
            "description": (
                "Check whether a take-ready webhook is configured for this account. "
                "Does not return the secret key."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True, "idempotentHint": True},
        },
    ]


def _crm_tool_definitions():
    contact_props = {
        "first_name": {"type": "string"},
        "business_name": {"type": "string"},
        "contact_type": {"type": "string", "description": "Type / role label."},
        "region": {"type": "string"},
        "country": {"type": "string"},
        "website": {"type": "string"},
        "email": {"type": "string"},
        "email_source": {"type": "string"},
        "personalisation_detail": {"type": "string"},
        "response": {
            "type": "string",
            "description": "Outreach response: signed_up, declined, revisit, or empty.",
            "enum": ["", "signed_up", "declined", "revisit"],
        },
        "response_reason": {
            "type": "string",
            "description": "Optional reason for the response.",
        },
        "tracking_slug": {
            "type": "string",
            "description": "Unique tracking slug. Auto-derived from name/email if omitted on create.",
        },
    }
    id_props = {
        "contact_id": {"type": "integer", "description": "CRM contact id."},
        "tracking_slug": {"type": "string", "description": "Unique tracking slug."},
    }
    return [
        {
            "name": "list_crm_contacts",
            "description": (
                "List Ramble CRM outreach contacts (same as /crm/). "
                "Optional query matches name, business, email, region, slug, and notes."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional search text."},
                    "limit": {"type": "integer", "description": f"Max rows (default {DEFAULT_LIMIT}, max {MAX_LIMIT})."},
                },
            },
            "annotations": {"readOnlyHint": True, "idempotentHint": True},
        },
        {
            "name": "get_crm_contact",
            "description": "Get one CRM contact by contact_id or tracking_slug.",
            "inputSchema": {
                "type": "object",
                "properties": id_props,
            },
            "annotations": {"readOnlyHint": True, "idempotentHint": True},
        },
        {
            "name": "create_crm_contact",
            "description": "Create a CRM outreach contact. Provide at least a name, business, or email so a tracking slug can be derived if omitted.",
            "inputSchema": {
                "type": "object",
                "properties": contact_props,
            },
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": False,
                "destructiveHint": False,
            },
        },
        {
            "name": "update_crm_contact",
            "description": (
                "Update a CRM contact. Identify with contact_id or tracking_slug. "
                "Pass only fields to change. Use new_tracking_slug to rename the slug."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    **id_props,
                    "first_name": {"type": "string"},
                    "business_name": {"type": "string"},
                    "contact_type": {"type": "string"},
                    "region": {"type": "string"},
                    "country": {"type": "string"},
                    "website": {"type": "string"},
                    "email": {"type": "string"},
                    "email_source": {"type": "string"},
                    "personalisation_detail": {"type": "string"},
                    "response": {
                        "type": "string",
                        "description": "Outreach response: signed_up, declined, revisit, or empty.",
                        "enum": ["", "signed_up", "declined", "revisit"],
                    },
                    "response_reason": {
                        "type": "string",
                        "description": "Optional reason for the response.",
                    },
                    "new_tracking_slug": {
                        "type": "string",
                        "description": "New unique tracking slug (optional).",
                    },
                },
            },
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": True,
                "destructiveHint": False,
            },
        },
        {
            "name": "delete_crm_contact",
            "description": "Delete a CRM contact by contact_id or tracking_slug.",
            "inputSchema": {
                "type": "object",
                "properties": id_props,
            },
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": True,
                "destructiveHint": True,
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


def _get_crm_contact(contact_id=None, tracking_slug=""):
    slug = (tracking_slug or "").strip()
    if contact_id not in (None, ""):
        try:
            pk = int(contact_id)
        except (TypeError, ValueError) as exc:
            raise ToolError("contact_id must be an integer.") from exc
        contact = CrmContact.objects.filter(pk=pk).first()
        if contact is None:
            raise ToolError(f"No CRM contact with id {pk}.")
        return contact
    if slug:
        contact = CrmContact.objects.filter(tracking_slug=slug).first()
        if contact is None:
            raise ToolError(f"No CRM contact with tracking_slug {slug!r}.")
        return contact
    raise ToolError("Pass contact_id or tracking_slug.")


def _serialize_crm_contact(contact):
    return {
        "id": contact.id,
        "first_name": contact.first_name,
        "business_name": contact.business_name,
        "contact_type": contact.contact_type,
        "region": contact.region,
        "country": contact.country,
        "website": contact.website,
        "email": contact.email,
        "email_source": contact.email_source,
        "personalisation_detail": contact.personalisation_detail,
        "response": contact.response,
        "response_label": contact.get_response_display() if contact.response else "",
        "response_reason": contact.response_reason,
        "tracking_slug": contact.tracking_slug,
        "tracking_url": contact.tracking_url,
        "created_at": _iso(contact.created_at),
        "updated_at": _iso(contact.updated_at),
    }


def _crm_form_error(form):
    parts = []
    for field, errors in form.errors.items():
        label = "contact" if field == "__all__" else field
        parts.append(f"{label}: {'; '.join(errors)}")
    return "; ".join(parts) or "Invalid CRM contact."


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
