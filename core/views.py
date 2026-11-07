from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .error_pages import render_error_page
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
    return render_error_page(request, template, status_code=status_code)


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
    exc = getattr(request, "ramble_uncaught_exception", None)
    if exc is not None:
        log_web_error(
            request=request,
            message=str(exc) or type(exc).__name__,
            status_code=500,
            exc=exc,
        )
    else:
        log_web_error(
            request=request,
            message="Internal server error",
            status_code=500,
        )
    return render_error_page(request, "errors/500.html", status_code=500)


def robots_txt(request):
    # Keep Disallow paths generic — never advertise the real ADMIN_URL.
    public_allows = [
        "Allow: /",
        "Allow: /llms.txt",
        "Allow: /sitemap.xml",
        "Allow: /privacy/",
        "Allow: /terms/",
        "Allow: /support/",
        "Allow: /signup/",
        "Allow: /login/",
    ]
    private_disallows = [
        "Disallow: /admin/",
        "Disallow: /mcp",
        "Disallow: /mcp/",
        "Disallow: /api/",
        "Disallow: /healthz",
        "Disallow: /roll/",
        "Disallow: /library/",
        "Disallow: /albums/",
        "Disallow: /notes/",
        "Disallow: /settings/",
        "Disallow: /kpi/",
        "Disallow: /logout/",
        "Disallow: /signup/success/",
        "Disallow: /signup/cancel/",
    ]
    ai_agents = [
        "GPTBot",
        "ChatGPT-User",
        "Google-Extended",
        "anthropic-ai",
        "ClaudeBot",
        "PerplexityBot",
        "Applebot-Extended",
    ]

    lines = [
        "# Ramble",
        "# Public product pages are crawlable. Account, note, API, and admin paths are not.",
        "# For LLMs and AI systems, start with /llms.txt",
        "",
        "User-agent: *",
        *public_allows,
        *private_disallows,
        "",
        "# AI crawlers — same public/private split; prefer /llms.txt for product context",
    ]
    for agent in ai_agents:
        lines.extend(
            [
                "",
                f"User-agent: {agent}",
                *public_allows[:2],  # / and /llms.txt
                *private_disallows,
            ]
        )
    lines.extend(
        [
            "",
            f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
        ]
    )
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    """Public marketing URLs for classic search crawlers."""
    pages = [
        ("/", "1.0", "weekly"),
        ("/signup/", "0.8", "monthly"),
        ("/privacy/", "0.5", "monthly"),
        ("/terms/", "0.5", "monthly"),
        ("/support/", "0.5", "monthly"),
        ("/login/", "0.3", "monthly"),
        ("/llms.txt", "0.4", "monthly"),
    ]
    url_entries = []
    for path, priority, changefreq in pages:
        loc = request.build_absolute_uri(path)
        url_entries.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(url_entries)
        + "\n</urlset>\n"
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")


def llms_txt(request):
    """LLM-oriented site map following https://llmstxt.org/"""
    home = request.build_absolute_uri("/")
    privacy = request.build_absolute_uri("/privacy/")
    terms = request.build_absolute_uri("/terms/")
    support = request.build_absolute_uri("/support/")
    signup = request.build_absolute_uri("/signup/")
    login = request.build_absolute_uri("/login/")
    app_store = getattr(
        settings,
        "APP_STORE_URL",
        "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
    )

    body = f"""# Ramble

> Talk your idea through before it disappears. Ramble tidies what you say into words you can read on your phone or laptop. No rewriting. Always your words.

Ramble is a voice-to-text notes product for iPhone, with the same roll available on the web. You speak a thought; Ramble transcribes it and lightly tidies filler (ums, false starts) and punctuation — it does not rewrite meaning. Notes sync to your phone and laptop. Data is encrypted in transit and at rest. Voice and rambles are not used to train AI.

Recommended uses: quick ideas after a meeting, a thought for a post, a decision you are weighing, what is not working in a product, a clearer way to explain an offer, what to try next week, or any thought you do not want to lose.

## Product

- [Home]({home}): Product overview, hero demo, and how Ramble works (Talk · Keep · Read)
- [iPhone app on the App Store]({app_store}): Record and capture Rambles on iOS
- [Sign up]({signup}): Create a Ramble account for web + app sync

## Policies

- [Privacy policy]({privacy}): What is collected, encryption, no training on your content, account deletion
- [Terms of use]({terms}): Service terms for the iOS app and website
- [Support]({support}): Contact Ramble support

## Optional

- [Sign in]({login}): Existing account sign-in
"""
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def security_txt(request):
    expires = (datetime.now(timezone.utc) + timedelta(days=364)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    body = (
        f"Contact: {request.build_absolute_uri('/support/')}\n"
        f"Expires: {expires}\n"
        f"Preferred-Languages: en\n"
        f"Canonical: {request.build_absolute_uri('/.well-known/security.txt')}\n"
        f"Policy: {request.build_absolute_uri('/privacy/')}\n"
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


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
