from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import (
    AlbumViewSet,
    NoteViewSet,
    develop_take,
    transcription_config,
    transcription_stream_token,
)

router = DefaultRouter()
router.register("notes", NoteViewSet, basename="api-notes")
router.register("albums", AlbumViewSet, basename="api-albums")

urlpatterns = [
    path("transcription/config/", transcription_config, name="api-transcription-config"),
    path(
        "transcription/stream-token/",
        transcription_stream_token,
        name="api-transcription-stream-token",
    ),
    path("notes/develop/", develop_take, name="api-notes-develop"),
    path("", include(router.urls)),
]
