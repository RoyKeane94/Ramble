from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path

from core.views import (
    bad_request,
    llms_txt,
    page_not_found,
    permission_denied,
    robots_txt,
    security_txt,
    server_error,
    sitemap_xml,
)
from accounts.views import stripe_webhook
from ramble_mcp.oauth_views import (
    oauth_authorization_server,
    oauth_authorize,
    oauth_protected_resource,
    oauth_register,
    oauth_revoke,
    oauth_token,
)
from ramble_mcp.views import grok_mcp_endpoint, mcp_endpoint

handler400 = bad_request
handler404 = page_not_found
handler403 = permission_denied
handler500 = server_error


def healthz(_request):
    connection.ensure_connection()
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("robots.txt", robots_txt),
    path("sitemap.xml", sitemap_xml),
    path("llms.txt", llms_txt),
    path(".well-known/security.txt", security_txt),
    path(".well-known/oauth-protected-resource", oauth_protected_resource),
    path(".well-known/oauth-protected-resource/<path:resource_path>", oauth_protected_resource),
    path(".well-known/oauth-authorization-server", oauth_authorization_server),
    path("oauth/authorize", oauth_authorize, name="oauth_authorize"),
    path("oauth/token", oauth_token, name="oauth_token"),
    path("oauth/register", oauth_register, name="oauth_register"),
    path("oauth/revoke", oauth_revoke, name="oauth_revoke"),
    path("mcp", mcp_endpoint),
    path("mcp/", mcp_endpoint),
    path("mcp/grok", grok_mcp_endpoint),
    path("mcp/grok/", grok_mcp_endpoint),
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
    path("api/", include("notes.api_urls")),
    path("api/", include("core.api_urls")),
    path("api/auth/", include("accounts.api_urls")),
    path("api/stripe/webhook/", stripe_webhook, name="stripe_webhook"),
    path("", include("accounts.urls")),
    path("", include("notes.urls")),
]
