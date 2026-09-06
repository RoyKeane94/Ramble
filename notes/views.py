from collections import OrderedDict
from datetime import timedelta
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import Album, Note


def home(request):
    if request.user.is_authenticated:
        return redirect("notes:list")
    return render(request, "pages/home.html")


@login_required
def note_list(request):
    album_param = request.GET.get("album", "recents")
    query = request.GET.get("q", "").strip()
    notes = Note.objects.filter(user=request.user)
    has_recents = notes.exists()
    has_starred = notes.filter(is_starred=True).exists()
    current_album = None
    album_title = "Recents"

    if album_param == "starred":
        notes = notes.filter(is_starred=True)
        album_title = "Favourites"
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
            else:
                album_param = "recents"

    if query:
        notes = notes.filter(
            Q_from_query(query)
        )

    grouped = OrderedDict()
    for note in notes:
        grouped.setdefault(note.list_header, []).append(note)

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
            "has_starred": has_starred,
            "has_results": notes.exists(),
            "search_open": bool(query) or request.GET.get("search") == "1",
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
        | Q(gpt_tidied_text__icontains=query)
        | Q(edited_text__icontains=query)
    )


@login_required
def album_list(request):
    notes = Note.objects.filter(user=request.user)
    favourites = notes.filter(is_starred=True)
    albums = list(Album.objects.filter(user=request.user).prefetch_related("notes"))
    roll = reverse("notes:list")

    tiles = [
        {
            "title": "Recents",
            "count": notes.count(),
            "updated_label": _updated_label(notes.first().created_at if notes.exists() else None),
            "href": f"{roll}?album=recents",
            "tone": 0,
        },
        {
            "title": "Favourites",
            "count": favourites.count(),
            "updated_label": _updated_label(
                favourites.first().created_at if favourites.exists() else None
            ),
            "href": f"{roll}?album=starred",
            "tone": 1,
        },
    ]

    for index, album in enumerate(albums):
        tiles.append(
            {
                "title": album.name,
                "count": album.take_count,
                "updated_label": album.updated_label,
                "href": f"{roll}?album={album.id}",
                "tone": (index + 2) % 4,
            }
        )

    return render(request, "notes/albums.html", {"tiles": tiles})


def _updated_label(when):
    if when is None:
        return None
    local = timezone.localtime(when)
    today = timezone.localtime(timezone.now()).date()
    date = local.date()
    if date == today:
        time = local.strftime("%-I:%M %p").replace("AM", "am").replace("PM", "pm")
        return f"Updated {time}"
    if date == today - timedelta(days=1):
        return "Updated Yesterday"
    return f"Updated {local.strftime('%-d %b %Y')}"


@login_required
def note_detail(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
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
