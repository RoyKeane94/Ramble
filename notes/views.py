from collections import Counter, OrderedDict
from datetime import timedelta
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Album, Note

# Month section headers only when that month has more takes than this.
MONTH_GROUP_THRESHOLD = 8


def home(request):
    if request.user.is_authenticated:
        return redirect("notes:list")

    joined = False
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        if email and "@" in email:
            joined = True

    return render(request, "pages/home.html", {"joined": joined})


def privacy(request):
    return render(request, "pages/legal.html", {"page_title": "Privacy"})


def terms(request):
    return render(request, "pages/legal.html", {"page_title": "Terms of use"})


def group_notes_for_roll(notes):
    """Today/Yesterday/day for thin months; month headers when a month is dense."""
    note_list = list(notes)
    month_counts = Counter()
    for note in note_list:
        local = timezone.localtime(note.created_at)
        month_counts[(local.year, local.month)] += 1

    grouped = OrderedDict()
    for note in note_list:
        local = timezone.localtime(note.created_at)
        dense = month_counts[(local.year, local.month)] > MONTH_GROUP_THRESHOLD
        note.show_row_day = dense
        header = note.month_header if dense else note.day_header_compact
        grouped.setdefault(header, []).append(note)
    return grouped


def _note_export_dict(note):
    transcripts = {}
    gpt = note.gpt_transcribe_transcript.strip()
    gpt_tidied = note.gpt_transcribe_tidied_text.strip()
    whisper = note.whisper_1_transcript.strip()
    whisper_tidied = note.whisper_1_tidied_text.strip()
    if gpt or gpt_tidied:
        transcripts["gpt_transcribe"] = {"raw": gpt, "tidied": gpt_tidied}
    if whisper or whisper_tidied:
        key = "universal_3_pro" if note.chosen_transcription_model.strip() == "universal-3-pro" else "whisper_1"
        transcripts[key] = {"raw": whisper, "tidied": whisper_tidied}
    if not transcripts and note.gpt_transcript.strip():
        transcripts["gpt_transcribe"] = {"raw": note.gpt_transcript.strip(), "tidied": ""}

    return {
        "id": str(note.id),
        "created_at": timezone.localtime(note.created_at).isoformat(),
        "updated_at": timezone.localtime(note.updated_at).isoformat(),
        "duration_seconds": note.duration,
        "is_starred": note.is_starred,
        "is_edited": note.is_edited,
        "edited_at": timezone.localtime(note.edited_at).isoformat() if note.edited_at else None,
        "albums": note.membership_names,
        "transcriptions": transcripts,
        "gpt_transcript": note.gpt_transcript,
        "gpt_tidied_text": note.gpt_tidied_text,
        "tidied_text": note.tidied_text,
        "edited_text": note.edited_text,
        "display_text": note.display_text,
        "chosen_transcription_model": note.chosen_transcription_model,
        "transcription_route_summary": note.transcription_route_summary,
        "next_action_text": note.next_action_text,
        "processing_failed": note.transcription_failed,
        "processing_error": note.processing_error,
    }


@login_required
@require_GET
def notes_export_json(request):
    notes = Note.objects.filter(user=request.user).prefetch_related("albums").order_by("-created_at")
    payload = {
        "exported_at": timezone.localtime(timezone.now()).isoformat(),
        "note_count": notes.count(),
        "notes": [_note_export_dict(note) for note in notes],
    }
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
    response["Content-Disposition"] = 'attachment; filename="ramble-export.json"'
    return response


@login_required
def note_list(request):
    album_param = request.GET.get("album", "recents")
    query = request.GET.get("q", "").strip()
    notes = Note.objects.filter(user=request.user).prefetch_related("albums")
    has_recents = notes.exists()
    current_album = None
    album_title = "Recents"
    from_albums = False

    if album_param == "starred":
        if not notes.filter(is_starred=True).exists():
            return redirect("notes:list")
        notes = notes.filter(is_starred=True)
        album_title = "Favourites"
        from_albums = True
    elif album_param == "today":
        now = timezone.localtime(timezone.now())
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        notes = notes.filter(created_at__gte=start, created_at__lt=start + timedelta(days=1))
        album_title = "Today"
    elif album_param not in ("", "recents"):
        try:
            album_id = UUID(album_param)
        except (TypeError, ValueError):
            album_param = "recents"
        else:
            current_album = Album.objects.filter(user=request.user, id=album_id).first()
            if current_album:
                notes = notes.filter(albums=current_album).distinct()
                album_title = current_album.name
                from_albums = True
            else:
                album_param = "recents"

    if query:
        notes = notes.filter(Q_from_query(query))

    if album_param == "today":
        today_notes = list(notes)
        for note in today_notes:
            note.show_row_day = False
        grouped = OrderedDict([("Today", today_notes)]) if today_notes else OrderedDict()
    else:
        grouped = group_notes_for_roll(notes)

    return render(
        request,
        "notes/list.html",
        {
            "grouped_notes": grouped.items(),
            "album": album_param,
            "album_title": album_title,
            "current_album": current_album,
            "query": query,
            "has_recents": has_recents,
            "has_results": notes.exists(),
            "search_open": bool(query) or request.GET.get("search") == "1",
            "nav_section": "albums" if from_albums else ("today" if album_param == "today" else "recents"),
        },
    )


def Q_from_query(query):
    from django.db.models import Q

    return (
        Q(tidied_text__icontains=query)
        | Q(raw_transcript__icontains=query)
        | Q(original_transcript__icontains=query)
        | Q(boosted_transcript__icontains=query)
        | Q(gpt_transcript__icontains=query)
        | Q(gpt_transcribe_transcript__icontains=query)
        | Q(whisper_1_transcript__icontains=query)
        | Q(gpt_transcribe_tidied_text__icontains=query)
        | Q(whisper_1_tidied_text__icontains=query)
        | Q(gpt_tidied_text__icontains=query)
        | Q(edited_text__icontains=query)
    )


@login_required
def album_list(request):
    notes = Note.objects.filter(user=request.user)
    favourites = notes.filter(is_starred=True)
    now = timezone.localtime(timezone.now())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = notes.filter(created_at__gte=start, created_at__lt=start + timedelta(days=1))
    albums = list(Album.objects.filter(user=request.user).prefetch_related("notes"))
    roll = reverse("notes:list")

    tiles = [
        {
            "title": "Recents",
            "count": notes.count(),
            "updated_label": _updated_label(notes.first().created_at if notes.exists() else None),
            "href": roll,
            "tone": 0,
        },
        {
            "title": "Today",
            "count": today.count(),
            "updated_label": _updated_label(today.first().created_at if today.exists() else None),
            "href": f"{roll}?album=today",
            "tone": 1,
        },
    ]

    if favourites.exists():
        tiles.append(
            {
                "title": "Favourites",
                "count": favourites.count(),
                "updated_label": _updated_label(favourites.first().created_at),
                "href": f"{roll}?album=starred",
                "tone": 2,
            }
        )

    for index, album in enumerate(albums):
        tiles.append(
            {
                "title": album.name,
                "count": album.take_count,
                "updated_label": album.updated_label,
                "href": f"{roll}?album={album.id}",
                "tone": index % 4,
            }
        )

    return render(
        request,
        "notes/albums.html",
        {
            "tiles": tiles,
            "nav_section": "albums",
        },
    )


@login_required
@require_POST
def album_create(request):
    name = request.POST.get("name", "").strip()
    if name:
        next_index = Album.objects.filter(user=request.user).aggregate(m=Max("sort_index"))["m"]
        Album.objects.create(
            user=request.user,
            name=name[:200],
            sort_index=(next_index if next_index is not None else -1) + 1,
        )
    return redirect("notes:albums")


@login_required
@require_POST
def album_delete(request, pk):
    album = get_object_or_404(Album, pk=pk, user=request.user)
    album.delete()
    return redirect("notes:albums")


def _updated_label(when):
    if when is None:
        return None
    local = timezone.localtime(when)
    today = timezone.localtime(timezone.now()).date()
    date = local.date()
    if date == today:
        return f"Updated {local.strftime('%H:%M')}"
    if date == today - timedelta(days=1):
        return "Updated Yesterday"
    return f"Updated {local.strftime('%-d %b %Y')}"


@login_required
def note_detail(request, pk):
    note = get_object_or_404(
        Note.objects.prefetch_related("albums"),
        pk=pk,
        user=request.user,
    )
    editing = request.GET.get("edit") == "1"
    managing_albums = request.GET.get("albums") == "1"
    albums = list(Album.objects.filter(user=request.user))
    album_ids = set(note.albums.values_list("id", flat=True))
    album_rows = [
        {
            "album": album,
            "contained": album.id in album_ids,
            "count": album.take_count,
        }
        for album in albums
    ]
    return render(
        request,
        "notes/detail.html",
        {
            "note": note,
            "editing": editing,
            "managing_albums": managing_albums,
            "album_rows": album_rows,
            "nav_section": "recents",
        },
    )


@login_required
def note_edit(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
    if request.method == "POST":
        note.edited_text = request.POST.get("text", "")
        note.edited_at = timezone.now()
        note.save(update_fields=["edited_text", "edited_at", "updated_at"])
        return redirect("notes:detail", pk=pk)
    return redirect("notes:detail", pk=pk)


@login_required
def note_delete(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
    if request.method == "POST":
        note.delete()
        return redirect("notes:list")
    return redirect("notes:detail", pk=pk)


@login_required
def note_star(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
    if request.method == "POST":
        note.is_starred = not note.is_starred
        note.save(update_fields=["is_starred", "updated_at"])
    return redirect("notes:detail", pk=pk)


@login_required
def note_albums(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
    if request.method != "POST":
        return redirect(f"{reverse('notes:detail', kwargs={'pk': pk})}?albums=1")

    action = request.POST.get("action", "").strip()
    if action == "create":
        name = request.POST.get("name", "").strip()
        if name:
            next_index = (
                Album.objects.filter(user=request.user).aggregate(m=Max("sort_index"))["m"]
            )
            album = Album.objects.create(
                user=request.user,
                name=name[:200],
                sort_index=(next_index if next_index is not None else -1) + 1,
            )
            album.notes.add(note)
    elif action == "toggle":
        album = get_object_or_404(
            Album, pk=request.POST.get("album_id"), user=request.user
        )
        if album.notes.filter(pk=note.pk).exists():
            album.notes.remove(note)
        else:
            album.notes.add(note)

    return redirect(f"{reverse('notes:detail', kwargs={'pk': pk})}?albums=1")
