from django.http import HttpResponse
from django.template.loader import get_template


def render_error_page(request, template_name, *, status_code):
    """
    Render an error template without running context processors.

    Processors such as minute_usage must not run on error pages — a failure there
    would prevent the error page from rendering at all.
    """
    user = getattr(request, "user", None)
    context = {
        "request": request,
        "user": user,
        "nav_page": "",
    }
    template = get_template(template_name)
    html = template.render(context, request=None)
    return HttpResponse(html, status=status_code)
