from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    path("", views.home, name="home"),
    path("roll/", views.note_list, name="list"),
    path("notes/<uuid:pk>/", views.note_detail, name="detail"),
]
