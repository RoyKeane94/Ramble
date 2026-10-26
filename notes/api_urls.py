from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import AlbumViewSet, NoteViewSet, develop_take

router = DefaultRouter()
router.register("notes", NoteViewSet, basename="api-notes")
router.register("albums", AlbumViewSet, basename="api-albums")

urlpatterns = [
    path("notes/develop/", develop_take, name="api-notes-develop"),
    path("", include(router.urls)),
]
