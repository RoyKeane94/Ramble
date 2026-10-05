def nav_page(request):
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", "") if match else ""
    return {"nav_page": url_name or ""}
