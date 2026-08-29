from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "created_at", "is_starred", "duration", "did_gpt_tidy")
    list_filter = ("is_starred", "did_gpt_tidy")
    search_fields = ("tidied_text", "boosted_transcript", "user__email")
    readonly_fields = ("id", "updated_at")
