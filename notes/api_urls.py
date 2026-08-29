from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import NoteViewSet

router = DefaultRouter()
router.register("notes", NoteViewSet, basename="api-notes")

urlpatterns = [
    path("", include(router.urls)),
]
