from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Note


def home(request):
    if request.user.is_authenticated:
        return redirect("notes:list")
    return render(request, "pages/home.html")


@login_required
def note_list(request):
    album = request.GET.get("album", "recents")
    query = request.GET.get("q", "").strip()
    notes = Note.objects.filter(user=request.user)
    has_recents = notes.exists()
    has_starred = notes.filter(is_starred=True).exists()

    if album == "starred":
        notes = notes.filter(is_starred=True)
    else:
        album = "recents"

    if query:
        notes = notes.filter(
            Q(tidied_text__icontains=query)
            | Q(raw_transcript__icontains=query)
            | Q(original_transcript__icontains=query)
            | Q(boosted_transcript__icontains=query)
            | Q(gpt_transcript__icontains=query)
            | Q(gpt_tidied_text__icontains=query)
            | Q(edited_text__icontains=query)
        )

    grouped = OrderedDict()
    for note in notes:
        grouped.setdefault(note.list_header, []).append(note)

    return render(
        request,
        "notes/list.html",
        {
            "grouped_notes": grouped.items(),
            "album": album,
            "query": query,
            "has_recents": has_recents,
            "has_starred": has_starred,
            "has_results": notes.exists(),
            "search_open": bool(query),
        },
    )


@login_required
def note_detail(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
    editing = request.GET.get("edit") == "1"
    return render(request, "notes/detail.html", {"note": note, "editing": editing})


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
