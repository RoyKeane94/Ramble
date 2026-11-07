import logging

from django.conf import settings

from .logging import log_web_error
from .traffic import record_page_view

logger = logging.getLogger(__name__)


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
