from django.contrib import admin
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path

from core.views import page_not_found, permission_denied, server_error

handler404 = page_not_found
handler403 = permission_denied
handler500 = server_error


def healthz(_request):
    connection.ensure_connection()
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/", include("notes.api_urls")),
    path("api/", include("core.api_urls")),
    path("api/auth/", include("accounts.api_urls")),
    path("", include("accounts.urls")),
    path("", include("notes.urls")),
]
