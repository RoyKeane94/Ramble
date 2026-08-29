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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.preview_line[:80]

    @property
    def is_developing(self):
        return self.is_processing or self.is_refining

    @property
    def developing_subtitle(self):
        if not self.is_developing:
            return None
        stage = self.processing_stage.strip()
        if stage:
            return stage
        if self.is_processing:
            return "Transcribing"
        if self.is_refining:
            return "Refining"
        return None

    @property
    def has_tidied(self):
        return self.did_gpt_tidy and bool(self.tidied_text.strip())

    @property
    def has_gpt_transcribe_tidy(self):
        return self.did_gpt_transcribe_tidy and bool(self.gpt_tidied_text.strip())

    @property
    def preview_line(self):
        if self.is_processing:
            if self.developing_subtitle:
                return f"Developing… · {self.developing_subtitle}"
            return "Developing…"
        if self.is_refining:
            if self.developing_subtitle:
                return f"Refining… · {self.developing_subtitle}"
            return "Refining…"
        if self.has_tidied:
            return self.tidied_text.replace("\n", " ")
        boosted = self.boosted_transcript.strip()
        if boosted:
            return boosted.replace("\n", " ")
        return "Empty take"

    @property
    def display_text(self):
        if self.has_tidied:
            return self.tidied_text
        if self.has_gpt_transcribe_tidy:
            return self.gpt_tidied_text
        return self.boosted_transcript

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
    def list_header(self):
        local = timezone.localtime(self.created_at)
        today = timezone.localtime(timezone.now()).date()
        date = local.date()
        if date == today:
            return "Today"
        if date == today - timedelta(days=1):
            return "Yesterday"
        return local.strftime("%B %Y")
