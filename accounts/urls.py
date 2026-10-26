from django.urls import path

from .views import RambleLoginView, RambleLogoutView, RegisterView, change_password, settings

urlpatterns = [
    path("login/", RambleLoginView.as_view(), name="login"),
    path("register/", RegisterView.as_view(), name="register"),
    path("logout/", RambleLogoutView.as_view(), name="logout"),
    path("settings/", settings, name="settings"),
    path("settings/change-password/", change_password, name="change_password"),
]
