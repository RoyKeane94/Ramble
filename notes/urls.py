from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    path("", views.home, name="home"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("roll/", views.note_list, name="list"),
    path("albums/", views.album_list, name="albums"),
    path("albums/new/", views.album_create, name="album_create"),
    path("albums/<uuid:pk>/delete/", views.album_delete, name="album_delete"),
    path("notes/<uuid:pk>/", views.note_detail, name="detail"),
    path("notes/<uuid:pk>/delete/", views.note_delete, name="delete"),
    path("notes/<uuid:pk>/star/", views.note_star, name="star"),
    path("notes/<uuid:pk>/edit/", views.note_edit, name="edit"),
    path("notes/<uuid:pk>/albums/", views.note_albums, name="albums_for_note"),
]
