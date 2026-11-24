"""Render blog body text with safe links."""

from __future__ import annotations

import html
import re

from django.utils.safestring import mark_safe

# [label](https://example.com) or [label](/relative/path)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# Bare http(s) URLs; trailing punctuation is left outside the link.
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_TRAILING_PUNCT = ".,;:)]}\"'"


def _allowed_href(url: str) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    lower = url.lower()
    if lower.startswith(("http://", "https://", "mailto:")):
        return url
    # Same-site paths only (no protocol-relative //evil.com).
    if url.startswith("/") and not url.startswith("//"):
        return url
    return None


def render_blog_body(raw: str) -> str:
    """Escape text, turn markdown/bare URLs into links, keep paragraph breaks."""
    text = raw or ""
    tokens: list[str] = []

    def stash(snippet: str) -> str:
        tokens.append(snippet)
        return f"\x00{len(tokens) - 1}\x00"

    def link_html(label: str, href: str) -> str:
        return (
            f'<a class="text-link blog-link" href="{html.escape(href, quote=True)}" '
            f'rel="noopener noreferrer">{html.escape(label)}</a>'
        )

    def replace_md(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        href = _allowed_href(url)
        if not href:
            return match.group(0)
        return stash(link_html(label, href))

    text = _MD_LINK_RE.sub(replace_md, text)

    def replace_bare(match: re.Match[str]) -> str:
        url = match.group(0)
        trailing = ""
        while url and url[-1] in _TRAILING_PUNCT:
            trailing = url[-1] + trailing
            url = url[:-1]
        href = _allowed_href(url)
        if not href:
            return match.group(0)
        return stash(link_html(url, href)) + trailing

    text = _BARE_URL_RE.sub(replace_bare, text)
    text = html.escape(text)
    for index, snippet in enumerate(tokens):
        text = text.replace(f"\x00{index}\x00", snippet)

    blocks = re.split(r"\n{2,}", text.strip())
    paragraphs = []
    for block in blocks:
        if not block.strip():
            continue
        paragraphs.append("<p>" + block.replace("\n", "<br>") + "</p>")
    return mark_safe("\n".join(paragraphs))
