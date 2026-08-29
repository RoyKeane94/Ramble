from .logging import log_web_error


class WebErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        log_web_error(
            request=request,
            message=str(exception) or type(exception).__name__,
            status_code=500,
            exc=exception,
        )
        return None
