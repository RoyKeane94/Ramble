from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .develop import DevelopError, develop_note
from .models import Album, Note
from .serializers import AlbumSerializer, NoteSerializer


class NoteViewSet(viewsets.ModelViewSet):
    serializer_class = NoteSerializer
    lookup_field = "id"

    def get_queryset(self):
        return Note.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        instance = self.get_object_or_none()
        if instance is None:
            data = {**request.data}
            data.setdefault("id", str(self.kwargs.get(self.lookup_field)))
            data.setdefault("next_action_text", "")
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return super().update(request, *args, **kwargs)

    def get_object_or_none(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        return queryset.filter(**filter_kwargs).first()


class AlbumViewSet(viewsets.ModelViewSet):
    serializer_class = AlbumSerializer
    lookup_field = "id"

    def get_queryset(self):
        return Album.objects.filter(user=self.request.user).prefetch_related("notes")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        instance = self.get_object_or_none()
        if instance is None:
            data = {**request.data}
            data.setdefault("id", str(self.kwargs.get(self.lookup_field)))
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return super().update(request, *args, **kwargs)

    def get_object_or_none(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        return queryset.filter(**filter_kwargs).first()


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def develop_take(request):
    audio = request.FILES.get("audio")
    if audio is None:
        return Response({"detail": "Audio is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        duration = float(request.data.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    created_raw = str(request.data.get("created_at") or "").strip()
    if created_raw.endswith("Z"):
        created_raw = created_raw[:-1] + "+00:00"
    created_at = parse_datetime(created_raw) if created_raw else None
    audio_bytes = audio.read()
    try:
        note = develop_note(
            request=request,
            audio_bytes=audio_bytes,
            content_type=audio.content_type,
            duration=duration,
            note_id=request.data.get("id"),
            created_at=created_at,
        )
    except DevelopError as exc:
        return Response({"detail": str(exc)}, status=exc.status)

    return Response(NoteSerializer(note).data, status=status.HTTP_200_OK)
