from django.urls import path

from .api import report_app_error, report_model_usage

urlpatterns = [
    path("errors/", report_app_error, name="api-report-error"),
    path("usage/", report_model_usage, name="api-report-usage"),
]
