from rest_framework import serializers

from .models import Album, Note


class NoteSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField()
    next_action_text = serializers.CharField(required=False, allow_blank=True, default="")

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
            "next_action_text",
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
            "processing_failed",
            "processing_error",
        )
        read_only_fields = ("updated_at",)

    def validate_next_action_text(self, value):
        return "" if value is None else value

    def create(self, validated_data):
        validated_data.setdefault("next_action_text", "")
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "next_action_text" in validated_data and validated_data["next_action_text"] is None:
            validated_data["next_action_text"] = ""
        return super().update(instance, validated_data)


class AlbumSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField()
    note_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        write_only=False,
    )
    take_count = serializers.SerializerMethodField()
    last_updated = serializers.SerializerMethodField()

    class Meta:
        model = Album
        fields = (
            "id",
            "name",
            "sort_index",
            "created_at",
            "note_ids",
            "take_count",
            "last_updated",
        )

    def get_take_count(self, instance):
        return instance.take_count

    def get_last_updated(self, instance):
        return instance.last_updated

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["note_ids"] = [str(note_id) for note_id in instance.notes.values_list("id", flat=True)]
        return data

    def create(self, validated_data):
        note_ids = validated_data.pop("note_ids", [])
        album = Album.objects.create(**validated_data)
        self._set_notes(album, note_ids)
        return album

    def update(self, instance, validated_data):
        note_ids = validated_data.pop("note_ids", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if note_ids is not None:
            self._set_notes(instance, note_ids)
        return instance

    def _set_notes(self, album, note_ids):
        notes = Note.objects.filter(user=album.user, id__in=note_ids)
        album.notes.set(notes)
