from django import template

from core.blog import render_blog_body

register = template.Library()


@register.filter(name="blog_body")
def blog_body(value):
    """Render blog post body with safe markdown and bare URL links."""
    return render_blog_body(value or "")
