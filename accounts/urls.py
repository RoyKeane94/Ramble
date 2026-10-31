from django.urls import path

from .views import RambleLoginView, RambleLogoutView, change_password, settings

urlpatterns = [
    path("login/", RambleLoginView.as_view(), name="login"),
    path("logout/", RambleLogoutView.as_view(), name="logout"),
    path("settings/", settings, name="settings"),
    path("settings/change-password/", change_password, name="change_password"),
]
