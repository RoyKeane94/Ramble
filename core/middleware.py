import logging

from django.conf import settings
from django.http import HttpResponsePermanentRedirect

from .logging import log_web_error
from .traffic import record_page_view

logger = logging.getLogger(__name__)


class CanonicalHostRedirectMiddleware:
    """301 alternate hosts (www, Railway) onto PUBLIC_BASE_URL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0].lower()
        redirect_hosts = getattr(settings, "CANONICAL_REDIRECT_HOSTS", frozenset())
        canonical_host = getattr(settings, "CANONICAL_HOST", "")
        if canonical_host and host in redirect_hosts:
            return HttpResponsePermanentRedirect(
                f"https://{canonical_host}{request.get_full_path()}"
            )
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        if csp:
            response.headers.setdefault("Content-Security-Policy", csp)
        permissions_policy = getattr(settings, "PERMISSIONS_POLICY", "")
        if permissions_policy:
            response.headers.setdefault("Permissions-Policy", permissions_policy)
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("Link", '</llms.txt>; rel="describedby"')
        return response


class TrafficMiddleware:
    """Count anonymous views of public pages. Failures never affect the response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            record_page_view(request, response)
        except Exception:
            logger.exception("Failed to record traffic")
        return response


class WebErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        request.ramble_uncaught_exception = exception
        return None
