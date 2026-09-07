import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Note(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    tidied_text = models.TextField(blank=True, default="")
    raw_transcript = models.TextField(blank=True, default="")
    original_transcript = models.TextField(blank=True, default="")
    boosted_transcript = models.TextField(blank=True, default="")
    gpt_transcript = models.TextField(blank=True, default="")
    gpt_tidied_text = models.TextField(blank=True, default="")
    next_action_text = models.TextField(blank=True, default="")
    edited_text = models.TextField(blank=True, default="")
    edited_at = models.DateTimeField(null=True, blank=True)
    duration = models.FloatField(default=0)
    is_starred = models.BooleanField(default=False)
    is_processing = models.BooleanField(default=False)
    is_refining = models.BooleanField(default=False)
    is_polishing = models.BooleanField(default=False)
    tidy_pending = models.BooleanField(default=False)
    did_gpt_tidy = models.BooleanField(default=False)
    did_gpt_transcribe_tidy = models.BooleanField(default=False)
    processing_stage = models.CharField(max_length=120, blank=True, default="")
    processing_log = models.TextField(blank=True, default="")
    processing_failed = models.BooleanField(default=False)
    processing_error = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.preview_line[:80]

    @property
    def is_developing(self):
        return self.is_processing

    @property
    def developing_subtitle(self):
        return None

    @property
    def has_tidied(self):
        return self.did_gpt_tidy and bool(self.tidied_text.strip())

    @property
    def has_gpt_transcribe_tidy(self):
        return self.did_gpt_transcribe_tidy and bool(self.gpt_tidied_text.strip())

    @property
    def has_whisper_tidied(self):
        return self.did_gpt_transcribe_tidy and bool(self.gpt_tidied_text.strip())

    @property
    def is_edited(self):
        return self.edited_at is not None

    @property
    def source_text(self):
        if self.has_whisper_tidied:
            return self.gpt_tidied_text
        whisper = self.gpt_transcript.strip()
        if whisper:
            return self.gpt_transcript
        if self.has_tidied:
            return self.tidied_text
        return self.boosted_transcript

    @property
    def transcription_failed(self):
        if self.processing_failed:
            return True
        if self.is_processing or self.is_edited:
            return False
        if self.display_text.strip():
            return False
        return self.duration > 0

    @property
    def failure_message(self):
        error = self.processing_error.strip()
        return error if error else "Transcription failed."

    @property
    def list_preview_text(self):
        if self.is_processing:
            return "Developing…"
        if self.transcription_failed:
            return "Transcription failed"
        text = self.display_text.strip()
        return text if text else "Empty take"

    @property
    def has_line_breaks(self):
        if self.transcription_failed:
            return False
        return "\n" in self.list_preview_text

    @property
    def preview_line(self):
        if self.is_processing:
            return "Developing…"
        if self.transcription_failed:
            return "Transcription failed"
        if self.is_edited:
            text = self.edited_text.strip()
            if text:
                return text.replace("\n", " ")
            return "Empty take"
        if self.has_whisper_tidied:
            return self.gpt_tidied_text.replace("\n", " ")
        whisper = self.gpt_transcript.strip()
        if whisper:
            return whisper.replace("\n", " ")
        return "Empty take"

    @property
    def display_text(self):
        if self.is_edited:
            return self.edited_text
        return self.source_text

    @property
    def todo_items(self):
        items = []
        for action in self.next_action_text.splitlines():
            action = action.strip()
            if not action:
                continue
            lower = action.lower()
            for prefix in ("to do —", "to do –", "to do -", "to do:", "to do ·", "to do "):
                if lower.startswith(prefix):
                    action = action[len(prefix):].strip()
                    break
            if action:
                items.append(action)
        return items

    @property
    def todo_preview_line(self):
        items = self.todo_items
        if not items:
            return None
        return f"To do · {items[0]}"

    @property
    def edited_label(self):
        if not self.is_edited or not self.edited_at:
            return None
        local = timezone.localtime(self.edited_at)
        return local.strftime("%-d %b %Y · %-I:%M %p").replace("AM", "am").replace("PM", "pm")

    @property
    def duration_label(self):
        total = int(self.duration)
        return f"{total // 60}:{total % 60:02d}"

    @property
    def time_label(self):
        local = timezone.localtime(self.created_at)
        return local.strftime("%-I:%M %p").replace("AM", "am").replace("PM", "pm")

    @property
    def day_header(self):
        local = timezone.localtime(self.created_at)
        today = timezone.localtime(timezone.now()).date()
        date = local.date()
        if date == today:
            return "Today"
        if date == today - timedelta(days=1):
            return "Yesterday"
        return local.strftime("%-d %B %Y")

    @property
    def day_header_compact(self):
        """Today / Yesterday / 2 Sep — for thin rolls."""
        local = timezone.localtime(self.created_at)
        today = timezone.localtime(timezone.now()).date()
        date = local.date()
        if date == today:
            return "Today"
        if date == today - timedelta(days=1):
            return "Yesterday"
        return local.strftime("%-d %b")

    @property
    def row_day_label(self):
        """Day stamp for rows under a month header."""
        local = timezone.localtime(self.created_at)
        return local.strftime("%-d %b")

    @property
    def month_header(self):
        local = timezone.localtime(self.created_at)
        return local.strftime("%B %Y")

    @property
    def list_header(self):
        return self.day_header_compact


class Album(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="albums",
    )
    name = models.CharField(max_length=200)
    sort_index = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    notes = models.ManyToManyField(Note, related_name="albums", blank=True)

    class Meta:
        ordering = ["sort_index", "created_at"]

    def __str__(self):
        return self.name

    @property
    def take_count(self):
        return self.notes.count()

    @property
    def last_updated(self):
        latest = self.notes.order_by("-created_at").values_list("created_at", flat=True).first()
        return latest or self.created_at

    @property
    def updated_label(self):
        local = timezone.localtime(self.last_updated)
        today = timezone.localtime(timezone.now()).date()
        date = local.date()
        if date == today:
            time = local.strftime("%-I:%M %p").replace("AM", "am").replace("PM", "pm")
            return f"Updated {time}"
        if date == today - timedelta(days=1):
            return "Updated Yesterday"
        return f"Updated {local.strftime('%-d %b %Y')}"
