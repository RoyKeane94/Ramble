from django.conf import settings

from .logging import log_web_error


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
        return response


class WebErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        request.ramble_uncaught_exception = exception
        return None
