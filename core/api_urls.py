from django.urls import path

from .api import report_app_error, report_model_usage
from .traffic import traffic_beacon, traffic_live

urlpatterns = [
    path("errors/", report_app_error, name="api-report-error"),
    path("usage/", report_model_usage, name="api-report-usage"),
    path("traffic/", traffic_beacon, name="api-traffic"),
    path("traffic/live/", traffic_live, name="api-traffic-live"),
]
