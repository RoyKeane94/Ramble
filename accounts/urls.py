from django.urls import path

from .views import (
    RambleLoginView,
    RambleLogoutView,
    billing_portal,
    change_password,
    crm_delete,
    crm_edit,
    crm_email_approve,
    crm_email_save,
    crm_field_update,
    crm_list,
    crm_tracking_open_confirm,
    crm_tracking_open_start,
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
    path("crm/<int:pk>/field/", crm_field_update, name="crm_field_update"),
    path("crm/<int:pk>/delete/", crm_delete, name="crm_delete"),
    path("crm/<int:pk>/email/", crm_email_save, name="crm_email_save"),
    path("crm/<int:pk>/email/approve/", crm_email_approve, name="crm_email_approve"),
    path(
        "t/<slug:slug>/open/start/",
        crm_tracking_open_start,
        name="crm_tracking_open_start",
    ),
    path(
        "t/<slug:slug>/open/confirm/",
        crm_tracking_open_confirm,
        name="crm_tracking_open_confirm",
    ),
]
