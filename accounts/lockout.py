from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

LOCKOUT_MESSAGE = (
    "Too many failed sign-in attempts. Please try again in 15 minutes."
)


def axes_lockout_response(request, credentials_or_response=None, credentials=None):
    """Visible lockout for site, admin, and API logins.

    Supports both axes callable signatures:
    ``(request, credentials)`` and ``(request, original_response, credentials)``.
    """
    if credentials is None:
        credentials = credentials_or_response

    status = getattr(settings, "AXES_HTTP_RESPONSE_CODE", 429)
    accept = request.headers.get("Accept", "")
    path = request.path

    if path.startswith("/api/") or "application/json" in accept:
        return JsonResponse({"detail": LOCKOUT_MESSAGE}, status=status)

    admin_prefix = f"/{settings.ADMIN_URL.strip('/')}/"
    if path.startswith(admin_prefix):
        return HttpResponse(
            f"<html><body><h1>Locked out</h1><p>{LOCKOUT_MESSAGE}</p></body></html>",
            status=status,
            content_type="text/html; charset=utf-8",
        )

    from .forms import EmailAuthenticationForm

    return render(
        request,
        "accounts/login.html",
        {
            "form": EmailAuthenticationForm(request),
            "lockout_message": LOCKOUT_MESSAGE,
        },
        status=status,
    )
