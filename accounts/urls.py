from django.urls import path

from .views import (
    RambleLoginView,
    RambleLogoutView,
    billing_portal,
    change_password,
    settings,
    signup,
    signup_cancel,
    signup_success,
)

urlpatterns = [
    path("login/", RambleLoginView.as_view(), name="login"),
    path("logout/", RambleLogoutView.as_view(), name="logout"),
    path("signup/", signup, name="signup"),
    path("signup/success/", signup_success, name="signup_success"),
    path("signup/cancel/", signup_cancel, name="signup_cancel"),
    path("settings/", settings, name="settings"),
    path("settings/billing/", billing_portal, name="billing_portal"),
    path("settings/change-password/", change_password, name="change_password"),
]
