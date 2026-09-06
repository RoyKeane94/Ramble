from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import AlbumViewSet, NoteViewSet

router = DefaultRouter()
router.register("notes", NoteViewSet, basename="api-notes")
router.register("albums", AlbumViewSet, basename="api-albums")

urlpatterns = [
    path("", include(router.urls)),
]
