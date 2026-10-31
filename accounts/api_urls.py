from django.urls import path

from . import api

urlpatterns = [
    path("login/", api.login),
    path("logout/", api.logout),
    path("me/", api.me),
    path("account/", api.delete_account),
]
