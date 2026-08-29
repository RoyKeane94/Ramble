from django.urls import path

from .api import report_app_error

urlpatterns = [
    path("errors/", report_app_error, name="api-report-error"),
]
