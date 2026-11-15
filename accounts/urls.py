from django.urls import path

from .views import (
    RambleLoginView,
    RambleLogoutView,
    billing_portal,
    change_password,
    crm_delete,
    crm_edit,
    crm_list,
    kpi_dashboard,
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
    path("kpi/", kpi_dashboard, name="kpi"),
    path("crm/", crm_list, name="crm"),
    path("crm/<int:pk>/edit/", crm_edit, name="crm_edit"),
    path("crm/<int:pk>/delete/", crm_delete, name="crm_delete"),
]
