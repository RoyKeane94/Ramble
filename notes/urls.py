from django.urls import path

from core.views import (
    blog_create,
    blog_delete,
    blog_detail,
    blog_edit,
    blog_list,
    support,
)

from . import views

app_name = "notes"

urlpatterns = [
    path("", views.home, name="home"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("support/", support, name="support"),
    path("blog/", blog_list, name="blog"),
    path("blog/new/", blog_create, name="blog_create"),
    path("roll/", views.note_list, name="list"),
    path("library/", views.note_library, name="library"),
    path("albums/", views.album_list, name="albums"),
    path("albums/new/", views.album_create, name="album_create"),
    path("albums/<uuid:pk>/delete/", views.album_delete, name="album_delete"),
    path("notes/<uuid:pk>/", views.note_detail, name="detail"),
    path("notes/<uuid:pk>/delete/", views.note_delete, name="delete"),
    path("notes/<uuid:pk>/star/", views.note_star, name="star"),
    path("notes/<uuid:pk>/edit/", views.note_edit, name="edit"),
    path("notes/<uuid:pk>/albums/", views.note_albums, name="albums_for_note"),
    # Published posts live at /<slug>/ — keep these last so they don't shadow app routes.
    path("<slug:slug>/edit/", blog_edit, name="blog_edit"),
    path("<slug:slug>/delete/", blog_delete, name="blog_delete"),
    path("<slug:slug>/", blog_detail, name="blog_detail"),
]
