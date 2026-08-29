from django.shortcuts import render

from .logging import log_web_error


def page_not_found(request, exception):
    log_web_error(
        request=request,
        message=str(exception) or "Page not found",
        status_code=404,
        error_type=type(exception).__name__,
        exc=exception,
    )
    return render(request, "errors/404.html", status=404)


def permission_denied(request, exception):
    log_web_error(
        request=request,
        message=str(exception) or "Permission denied",
        status_code=403,
        error_type=type(exception).__name__,
        exc=exception,
    )
    return render(request, "errors/403.html", status=403)


def server_error(request):
    return render(request, "errors/500.html", status=500)
