from django.urls import path

from . import api

urlpatterns = [
    path("register/", api.register),
    path("login/", api.login),
    path("logout/", api.logout),
    path("me/", api.me),
]
