from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    path("", views.home, name="home"),
    path("roll/", views.note_list, name="list"),
    path("notes/<uuid:pk>/", views.note_detail, name="detail"),
    path("notes/<uuid:pk>/delete/", views.note_delete, name="delete"),
    path("notes/<uuid:pk>/star/", views.note_star, name="star"),
    path("notes/<uuid:pk>/edit/", views.note_edit, name="edit"),
]
