from django.conf import settings


def nav_page(request):
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", "") if match else ""
    return {"nav_page": url_name or ""}


def public_site(_request):
    return {"PUBLIC_BASE_URL": getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")}
