from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import SupportRequestForm
from .logging import log_web_error


def _log_and_render(request, *, template, status_code, message, exception):
    log_web_error(
        request=request,
        message=message,
        status_code=status_code,
        error_type=type(exception).__name__,
        exc=exception,
    )
    return render(request, template, status=status_code)


def page_not_found(request, exception):
    return _log_and_render(
        request,
        template="errors/404.html",
        status_code=404,
        message=str(exception) or "Page not found",
        exception=exception,
    )


def permission_denied(request, exception):
    return _log_and_render(
        request,
        template="errors/403.html",
        status_code=403,
        message=str(exception) or "Permission denied",
        exception=exception,
    )


def bad_request(request, exception):
    return _log_and_render(
        request,
        template="errors/400.html",
        status_code=400,
        message=str(exception) or "Bad request",
        exception=exception,
    )


def server_error(request):
    return render(request, "errors/500.html", status=500)


def support(request):
    if request.method == "POST":
        form = SupportRequestForm(request.POST)
        if form.is_valid():
            support_request = form.save(commit=False)
            if request.user.is_authenticated:
                support_request.user = request.user
            support_request.save()
            messages.success(
                request,
                "Thanks — we received your message and will reply by email.",
            )
            return redirect("notes:support")
    else:
        initial = {}
        if request.user.is_authenticated:
            initial["email"] = request.user.email
        form = SupportRequestForm(initial=initial)

    return render(request, "pages/support.html", {"form": form})
