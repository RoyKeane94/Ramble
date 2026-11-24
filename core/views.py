from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .error_pages import render_error_page
from .forms import BlogPostForm, SupportRequestForm
from .logging import log_web_error
from .models import BlogPost


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


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
        "Allow: /blog/",
        "Allow: /signup/",
        "Allow: /login/",
    ]
    private_disallows = [
        "Disallow: /admin/",
        "Disallow: /mcp",
        "Disallow: /mcp/",
        "Disallow: /oauth/",
        "Disallow: /api/",
        "Disallow: /healthz",
        "Disallow: /roll/",
        "Disallow: /library/",
        "Disallow: /albums/",
        "Disallow: /notes/",
        "Disallow: /settings/",
        "Disallow: /kpi/",
        "Disallow: /blog/new/",
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
    # lastmod = date the page content last really changed (W3C Datetime / YYYY-MM-DD).
    pages = [
        ("/", "2026-11-23"),
        ("/signup/", "2026-11-09"),
        ("/privacy/", "2026-10-04"),
        ("/terms/", "2026-11-06"),
        ("/support/", "2026-10-06"),
        ("/blog/", "2026-11-24"),
    ]
    url_entries = []
    for path, lastmod in pages:
        loc = request.build_absolute_uri(path)
        url_entries.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            "  </url>"
        )
    for post in BlogPost.objects.filter(is_published=True).exclude(published_at=None):
        lastmod = (post.updated_at or post.published_at).date().isoformat()
        loc = request.build_absolute_uri(post.get_absolute_url())
        url_entries.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
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
    return render(
        request,
        "llms.txt",
        {
            "home": request.build_absolute_uri("/"),
            "privacy": request.build_absolute_uri("/privacy/"),
            "terms": request.build_absolute_uri("/terms/"),
            "support": request.build_absolute_uri("/support/"),
            "blog": request.build_absolute_uri("/blog/"),
            "signup": request.build_absolute_uri("/signup/"),
            "login": request.build_absolute_uri("/login/"),
            "app_store": getattr(
                settings,
                "APP_STORE_URL",
                "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
            ),
        },
        content_type="text/plain; charset=utf-8",
    )


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


def blog_list(request):
    posts = BlogPost.objects.filter(is_published=True)
    drafts = []
    if request.user.is_authenticated and request.user.is_superuser:
        drafts = list(BlogPost.objects.filter(is_published=False))
    return render(
        request,
        "pages/blog_list.html",
        {
            "posts": posts,
            "drafts": drafts,
            "nav_section": "blog",
        },
    )


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)
    if not post.is_published:
        if not (request.user.is_authenticated and request.user.is_superuser):
            raise Http404()
    return render(
        request,
        "pages/blog_detail.html",
        {
            "post": post,
            "nav_section": "blog",
        },
    )


@login_required
def blog_create(request):
    _require_superuser(request)
    form = BlogPostForm()
    if request.method == "POST":
        form = BlogPostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, "Post saved.")
            return redirect(post.get_absolute_url())
    return render(
        request,
        "pages/blog_edit.html",
        {
            "form": form,
            "editing": None,
            "nav_section": "blog",
        },
    )


@login_required
def blog_edit(request, slug):
    _require_superuser(request)
    post = get_object_or_404(BlogPost, slug=slug)
    form = BlogPostForm(instance=post)
    if request.method == "POST":
        form = BlogPostForm(request.POST, instance=post)
        if form.is_valid():
            post = form.save()
            messages.success(request, "Post updated.")
            return redirect(post.get_absolute_url())
    return render(
        request,
        "pages/blog_edit.html",
        {
            "form": form,
            "editing": post,
            "nav_section": "blog",
        },
    )


@login_required
@require_POST
def blog_delete(request, slug):
    _require_superuser(request)
    post = get_object_or_404(BlogPost, slug=slug)
    post.delete()
    messages.success(request, "Post deleted.")
    return redirect("notes:blog")
