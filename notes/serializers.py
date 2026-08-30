from rest_framework import serializers

from .models import Note


class NoteSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField()

    class Meta:
        model = Note
        fields = (
            "id",
            "created_at",
            "updated_at",
            "tidied_text",
            "raw_transcript",
            "original_transcript",
            "boosted_transcript",
            "gpt_transcript",
            "gpt_tidied_text",
            "edited_text",
            "edited_at",
            "duration",
            "is_starred",
            "is_processing",
            "is_refining",
            "is_polishing",
            "tidy_pending",
            "did_gpt_tidy",
            "did_gpt_transcribe_tidy",
            "processing_stage",
            "processing_log",
        )
        read_only_fields = ("updated_at",)
